#!/usr/bin/env python3
"""
Keep data/games/<season>.csv current from the CollegeBasketballData API.

    python3 fetch_games.py            # incremental: the current season's recent + upcoming games
    python3 fetch_games.py --full     # backfill every season the API has (a few hundred calls, once)

Needs CBBD_API_KEY in the environment (a GitHub Actions secret -- never
committed). Season numbers follow the API: season 2026 = the 2025-26 season.

The API returns at most 3,000 games per request, so big seasons are fetched
month by month (and a month that still hits the cap is split in half).
Every call is counted and printed so the free tier's monthly quota is easy
to keep an eye on.
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = timezone(timedelta(hours=-5))

BASE = "https://api.collegebasketballdata.com"
KEY = os.environ.get("CBBD_API_KEY", "").strip()
CAP = 3000
DATA = os.path.join("data", "games")
FIELDS = ["id", "date", "start_et", "season", "season_type", "tournament", "status",
          "home", "away", "home_id", "away_id", "home_points", "away_points", "neutral",
          "home_conf", "away_conf", "home_seed", "away_seed", "venue", "city", "state", "notes"]
CALLS = 0


def api(path, **params):
    global CALLS
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    last = None
    for i in range(4):
        CALLS += 1
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:200]}"
            if e.code in (401, 403):
                break
        except Exception as e:
            last = str(e)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{path} {params} failed: {last}")


def to_row(g):
    start = g.get("startDate") or ""
    d, t = "", ""
    if start:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ET)
        d = local.date().isoformat()
        t = "" if g.get("startTimeTbd") else local.strftime("%H:%M")
    return {
        "id": g["id"], "date": d, "start_et": t, "season": g.get("season"),
        "season_type": g.get("seasonType") or "", "tournament": g.get("tournament") or "",
        "status": g.get("status") or "",
        "home": g.get("homeTeam") or "", "away": g.get("awayTeam") or "",
        "home_id": g.get("homeTeamId") or "", "away_id": g.get("awayTeamId") or "",
        "home_points": "" if g.get("homePoints") is None else g["homePoints"],
        "away_points": "" if g.get("awayPoints") is None else g["awayPoints"],
        "neutral": "1" if g.get("neutralSite") else "",
        "home_conf": g.get("homeConference") or "", "away_conf": g.get("awayConference") or "",
        "home_seed": g.get("homeSeed") or "", "away_seed": g.get("awaySeed") or "",
        "venue": g.get("venue") or "", "city": g.get("city") or "", "state": g.get("state") or "",
        "notes": (g.get("gameNotes") or "").replace("\n", " ")[:200],
    }


def iso(d):
    return d.strftime("%Y-%m-%dT00:00:00Z")


def fetch_range(season, start, end):
    """Games in [start, end) for a season, splitting the window if it hits the cap."""
    got = api("/games", season=season, startDateRange=iso(start), endDateRange=iso(end))
    if len(got) < CAP or (end - start).days <= 1:
        return got
    mid = start + (end - start) / 2
    mid = date(mid.year, mid.month, mid.day)
    return fetch_range(season, start, mid) + fetch_range(season, mid, end)


def fetch_season(season):
    got = api("/games", season=season)
    if len(got) < CAP:
        return got
    games = []
    d = date(season - 1, 10, 1)
    while d < date(season, 5, 1):
        nxt = date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
        games += fetch_range(season, d, nxt)
        d = nxt
    return games


def path_for(season):
    return os.path.join(DATA, f"{season}.csv")


def read(season):
    p = path_for(season)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(season, rows):
    os.makedirs(DATA, exist_ok=True)
    uniq = {}
    for r in rows:
        uniq[str(r["id"])] = r
    rows = sorted(uniq.values(), key=lambda r: (r["date"], r.get("start_et") or "", str(r["id"])))
    with open(path_for(season), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    final = sum(1 for r in rows if r["status"] == "final")
    print(f"  season {season}: {len(rows):,} games ({final:,} final)")


def current_season(today=None):
    today = today or datetime.now(ET).date()
    return today.year + 1 if today.month >= 7 else today.year


def backfill():
    cur = current_season()
    # find the earliest season the API has: walk back from 1950 until three empty seasons in a row
    earliest, empty, s = 1950, 0, 1949
    while empty < 3 and s > 1890:
        got = api("/games", season=s)
        if got:
            earliest, empty = s, 0
            write(s, [to_row(g) for g in got])
        else:
            empty += 1
        s -= 1
    print(f"  earliest season with games: {earliest}")
    for s in range(1950, cur + 1):
        write(s, [to_row(g) for g in fetch_season(s)])
    teams = api("/teams")
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "teams.json"), "w", encoding="utf-8") as f:
        json.dump(teams, f, indent=1)
    print(f"  teams: {len(teams)}")


def incremental():
    today = datetime.now(ET).date()
    cur = current_season(today)
    start, end = today - timedelta(days=10), today + timedelta(days=35)
    for season in sorted({current_season(start), cur}):
        got = fetch_range(season, start, end)
        rows = read(season)
        fresh = {str(g["id"]) for g in got}
        rows = [r for r in rows if str(r["id"]) not in fresh] + [to_row(g) for g in got]
        write(season, rows)
    if not os.path.exists(os.path.join("data", "teams.json")) or today.weekday() == 0 and datetime.now(ET).hour < 3:
        teams = api("/teams")
        with open(os.path.join("data", "teams.json"), "w", encoding="utf-8") as f:
            json.dump(teams, f, indent=1)


def main():
    if not KEY:
        sys.exit("CBBD_API_KEY is not set")
    full = "--full" in sys.argv or not os.path.isdir(DATA) or not os.listdir(DATA)
    print("backfill" if full else "incremental update")
    try:
        backfill() if full else incremental()
    finally:
        print(f"API calls this run: {CALLS}")


if __name__ == "__main__":
    main()
