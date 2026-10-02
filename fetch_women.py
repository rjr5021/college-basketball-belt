#!/usr/bin/env python3
"""
Keep the women's game files current: data/women/games/<season>.csv.

    python3 fetch_women.py           # incremental: this season's results + the next month's schedule (75 days in Aug-Oct)
    python3 fetch_women.py --full    # rebuild every season from 2002-03 on

Sources (no API key needed):
  * 2002-03 on: ESPN results via the sportsdataverse wehoop project's schedule files
    (github.com/sportsdataverse/sportsdataverse-data, CC BY 4.0), one file per season.
  * The latest days and the upcoming schedule: ESPN's public scoreboard.
  * 1986-87 through the 2002 final: data/women/hist.csv, the hand-built belt line
    (every game the holder played), written once and never touched by this script.

Season numbers follow the men's files: season 2024 = the 2023-24 season.
Rows use the same columns as data/games/*.csv.
"""

import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))

DATA = os.path.join("data", "women")
GAMES = os.path.join(DATA, "games")
FIELDS = ["id", "date", "start_et", "season", "season_type", "tournament", "status",
          "home", "away", "home_id", "away_id", "home_points", "away_points", "neutral",
          "home_conf", "away_conf", "home_seed", "away_seed", "venue", "city", "state", "notes"]
SDV = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_womens_college_basketball_schedules"
SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard"
              "?dates={d}&groups=50&limit=500")
FIRST = 2003
TOURNAMENTS = {"22": "NCAA", "37": "WNIT", "62": "WBIT"}


def get(url, as_json=False, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120) as r:
                body = r.read().decode("utf-8", errors="replace")
            return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(3 * (i + 1))
    print("  failed:", url, last)
    return None


def today_et():
    return datetime.now(ET).date()


def current_season(d):
    return d.year + 1 if d.month >= 8 else d.year


def read(season):
    p = os.path.join(GAMES, f"{season}.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(season, rows):
    os.makedirs(GAMES, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["start_et"] or "", int(r["id"])))
    with open(os.path.join(GAMES, f"{season}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {season}: {len(rows)} games")


def load_json(name, default):
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=0, sort_keys=True)


def tf(x):
    return str(x).upper() in ("TRUE", "1")


def from_wehoop(season, teams, confs):
    """Every game in one wehoop season file, in our columns."""
    t = get(f"{SDV}/wbb_schedule_{season}.csv")
    if not t:
        print(f"  no wehoop file for {season}")
        return None
    rows = list(csv.DictReader(io.StringIO(t)))
    local = {}            # conference names as that season's file labels them (WAC, Big Eight, ...)
    for r in rows:
        if tf(r.get("conference_competition")) and r.get("groups_short_name") and r.get("home_conference_id"):
            local[r["home_conference_id"]] = r["groups_short_name"]
    confs.update(local)
    cname = lambda cid: local.get(cid or "", "") or confs.get(cid or "", "")
    out = []
    for r in rows:
        if r.get("season_type") not in ("2", "3"):
            continue
        done = tf(r.get("status_type_completed")) and r.get("home_score") not in ("", "NA", None)
        if tf(r.get("status_type_completed")) and not done:
            continue
        start = datetime.fromisoformat((r.get("date") or r.get("start_date")).replace("Z", "+00:00")).astimezone(ET)
        for side in ("home", "away"):
            tid = r.get(f"{side}_id")
            c, alt = r.get(f"{side}_color"), r.get(f"{side}_alternate_color")
            t0 = teams.setdefault(tid, {"id": tid})
            t0["school"] = r.get(f"{side}_location") or t0.get("school") or ""
            t0["mascot"] = r.get(f"{side}_name") or t0.get("mascot") or ""
            if c and c != "NA":
                t0["primaryColor"], t0["secondaryColor"] = c.lower(), (alt.lower() if alt and alt != "NA" else "ffffff")
        tour = TOURNAMENTS.get(str(r.get("tournament_id") or ""), "")
        out.append({
            "id": r.get("game_id") or r.get("id"), "date": start.date().isoformat(),
            "start_et": start.strftime("%H:%M") if tf(r.get("time_valid")) else "",
            "season": season, "season_type": "postseason" if r["season_type"] == "3" else "regular",
            "tournament": tour, "status": "final" if done else "scheduled",
            "home": r.get("home_location"), "away": r.get("away_location"),
            "home_id": r.get("home_id"), "away_id": r.get("away_id"),
            "home_points": int(float(r["home_score"])) if done else "", "away_points": int(float(r["away_score"])) if done else "",
            "neutral": "1" if tf(r.get("neutral_site")) else "",
            "home_conf": cname(r.get("home_conference_id")), "away_conf": cname(r.get("away_conference_id")),
            "home_seed": "", "away_seed": "", "venue": r.get("venue_full_name") or "",
            "city": r.get("venue_address_city") or "", "state": r.get("venue_address_state") or "",
            "notes": r.get("notes_headline") or ""})
    return [x for x in out if x["status"] == "final" or x["date"] >= today_et().isoformat()]


def from_scoreboard(day, teams, confs, conf_of):
    j = get(SCOREBOARD.format(d=day.strftime("%Y%m%d")), as_json=True) or {}
    out = []
    for ev in j.get("events", []):
        comp = ev["competitions"][0]
        side = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in side or "away" not in side:
            continue
        start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
        st = ev["status"]["type"]
        stype = (ev.get("season") or {}).get("type")
        if stype not in (2, 3):
            continue
        # N-2: ESPN parks unscheduled tips at midnight ET with timeValid=false; that's TBA, not 12:00 AM.
        _tv = comp.get("timeValid")
        _hhmm = start.strftime("%H:%M")
        _tba = st.get("name") == "STATUS_TBD" or _tv is False or (_tv is None and _hhmm == "00:00")
        row = {"id": ev["id"], "date": start.date().isoformat(), "start_et": "" if _tba else _hhmm,
               "season": (ev.get("season") or {}).get("year") or current_season(start.date()),
               "season_type": "postseason" if stype == 3 else "regular",
               "tournament": TOURNAMENTS.get(str(comp.get("tournamentId") or ""), ""),
               "neutral": "1" if comp.get("neutralSite") else "", "home_seed": "", "away_seed": "",
               "venue": (comp.get("venue") or {}).get("fullName") or "",
               "city": ((comp.get("venue") or {}).get("address") or {}).get("city") or "",
               "state": ((comp.get("venue") or {}).get("address") or {}).get("state") or "",
               "notes": ((comp.get("notes") or [{}])[0] or {}).get("headline") or ""}
        for s in ("home", "away"):
            tm = side[s]["team"]
            tid = str(tm.get("id"))
            row[s] = tm.get("location") or tm.get("displayName")
            row[f"{s}_id"] = tid
            row[f"{s}_conf"] = confs.get(str(tm.get("conferenceId") or ""), "") or conf_of.get(tid, "")
            t0 = teams.setdefault(tid, {"id": tid})
            t0["school"] = row[s]
            t0["mascot"] = tm.get("name") or t0.get("mascot") or ""
            if tm.get("color"):
                t0["primaryColor"], t0["secondaryColor"] = tm["color"].lower(), (tm.get("alternateColor") or "ffffff").lower()
        if st.get("completed"):
            try:
                row["home_points"], row["away_points"] = int(side["home"]["score"]), int(side["away"]["score"])
            except (KeyError, TypeError, ValueError):
                continue
            row["status"] = "final"
        elif st.get("state") == "pre":
            row["status"], row["home_points"], row["away_points"] = "scheduled", "", ""
        else:
            continue
        out.append(row)
    return out


def main():
    full = "--full" in sys.argv
    today = today_et()
    cur = current_season(today)
    teams = {t["id"]: t for t in load_json("teams.json", [])}
    confs = load_json("conferences.json", {})
    have = sorted(int(f[:4]) for f in os.listdir(GAMES) if f.endswith(".csv")) if os.path.isdir(GAMES) else []
    seasons = range(FIRST, cur + 1) if full or not have else ([cur - 1, cur] if today.month <= 5 else [cur])
    for s in seasons:
        rows = from_wehoop(s, teams, confs)
        if rows is None:
            continue
        old = {r["id"]: r for r in read(s)}
        new = {str(r["id"]): r for r in rows}
        # keep scoreboard rows the season file doesn't have yet
        for k, r in old.items():
            if k not in new and (r["status"] == "final" or r["date"] >= today.isoformat()):
                new[k] = r
        write(s, list(new.values()))
    save_json("teams.json", sorted(teams.values(), key=lambda t: int(t["id"]) if str(t["id"]).isdigit() else 0))
    save_json("conferences.json", confs)
    if "--no-scoreboard" in sys.argv:
        return
    # the latest results and the month ahead from ESPN's scoreboard
    conf_of = {}
    for r in read(cur) + read(cur - 1):
        for s in ("home", "away"):
            if r.get(f"{s}_conf"):
                conf_of[r[f"{s}_id"]] = r[f"{s}_conf"]
    if today.month in (8, 9, 10):
        # Preseason: look 75 days ahead so opening week is on file well before it
        # starts. The wehoop season file lags behind ESPN's schedule (2026-10-01:
        # UCLA's Nov 2 opener vs Lehigh, Nov 5 vs UC Irvine and Nov 19 vs Cal Poly
        # were on ESPN but not on file, so the site showed Nov 12 vs Arizona as the
        # next belt game). Before, the long look-ahead only ran on an empty file.
        span = [today + timedelta(days=i) for i in range(-3, 75)]
    else:
        span = [today + timedelta(days=i) for i in range(-3, 31)]
    by_season = {}
    got = 0
    for day in span:
        for r in from_scoreboard(day, teams, confs, conf_of):
            by_season.setdefault(int(r["season"]), []).append(r)
            got += 1
        time.sleep(0.1)
    print(f"  scoreboard: {got} games over {len(span)} days")
    for s, rows in by_season.items():
        cur_rows = {r["id"]: r for r in read(s)}
        for r in rows:
            cur_rows[str(r["id"])] = {**cur_rows.get(str(r["id"]), {}), **{k: str(v) for k, v in r.items()}}
        # drop stale scheduled rows that have passed without a result
        keep = [r for r in cur_rows.values() if r["status"] == "final" or r["date"] >= today.isoformat()]
        write(s, keep)
    save_json("teams.json", sorted(teams.values(), key=lambda t: int(t["id"]) if str(t["id"]).isdigit() else 0))
    save_json("conferences.json", confs)


if __name__ == "__main__":
    main()
