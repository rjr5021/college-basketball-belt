#!/usr/bin/env python3
"""
Keep data/women/polls/<season>.csv (the women's AP Top 25, week by week) current
from ESPN's public rankings API (the women's games already come from ESPN; no key).

    python3 fetch_women_polls.py          # backfill if empty; else refresh the current season once a day in season
    python3 fetch_women_polls.py --full   # refetch every season

ESPN has the women's AP poll from 2000-01 on. Polls from 2017-18 on carry their
release dates; earlier ones are undated, and polls.py places them the way it does
the men's undated seasons (week 1 = the day before opening night, the final poll =
the Monday of the NCAA tournament's first week, weekly between).
The backfill is about 26 seasons x 20 weeks of small requests, once; after that
it's one season a day from October to April. Same columns as data/polls/*.csv.
"""

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

DATA = os.path.join("data", "women", "polls")
META = os.path.join(DATA, "_meta.json")
FIELDS = ["season", "week", "date", "poll", "team_id", "team", "rank", "points", "first"]
FIRST = 2001          # season 2001 = 2000-01, the first ESPN has
BASE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/womens-college-basketball/seasons"
CALLS = 0


def get(url, tries=3):
    global CALLS
    err = None
    for i in range(tries):
        CALLS += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (collegebasketballbelt.com polls)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {err}")


def team_id(ref):
    """'.../teams/2579?lang=en' -> '2579'"""
    tail = str((ref or {}).get("$ref") or "").split("/teams/")
    return tail[1].split("?")[0].split("/")[0] if len(tail) > 1 else ""


def names():
    try:
        with open(os.path.join("data", "women", "teams.json"), encoding="utf-8") as f:
            return {str(t["id"]): t.get("name") or t.get("school") or "" for t in json.load(f)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def fetch(season, nm):
    weeks = (get(f"{BASE}/{season}/types/2/weeks") or {}).get("count") or 0
    rows = []
    for w in range(1, weeks + 1):
        poll = None
        for k in (1, 2):                      # /1 is the AP poll; check the type in case ESPN swaps them
            p = get(f"{BASE}/{season}/types/2/weeks/{w}/rankings/{k}")
            if p and str(p.get("type", "")).lower() == "ap":
                poll = p
                break
        if not poll:
            continue
        dt = str(poll.get("date") or "")[:10]
        for r in poll.get("ranks") or []:
            tid = team_id(r.get("team"))
            if not tid or not r.get("current"):
                continue
            rows.append({"season": season, "week": w, "date": dt, "poll": "AP Top 25", "team_id": tid, "team": nm.get(tid, ""),
                         "rank": r["current"], "points": int(r.get("points") or 0), "first": int(r.get("firstPlaceVotes") or 0)})
    rows.sort(key=lambda r: (r["week"], r["rank"]))
    return rows


def write(season, rows):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, f"{season}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  season {season}: {len({r['week'] for r in rows})} AP polls, {len(rows)} rows")


def current_season(today):
    return today.year + 1 if today.month >= 8 else today.year


def main():
    today = date.today()
    cur = current_season(today)
    meta = {}
    if os.path.exists(META):
        with open(META) as f:
            meta = json.load(f)
    have = {int(p[:-4]) for p in os.listdir(DATA) if p[:-4].isdigit()} if os.path.isdir(DATA) else set()
    if "--full" in sys.argv or not have:
        seasons = range(FIRST, cur + 1)
    else:
        last = meta.get("fetched", "")
        in_season = today.month >= 10 or today.month <= 4
        fresh = last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 20 * 3600
        seasons = [] if (fresh or not in_season) else [cur]
    nm = names()
    ok = 0
    for s in seasons:
        try:
            rows = fetch(s, nm)
        except Exception as e:  # noqa: BLE001
            print(f"  season {s}: {e}")
            continue
        if rows:
            write(s, rows)
            ok += 1
        else:
            print(f"  season {s}: no AP polls on ESPN yet")
    if ok:
        os.makedirs(DATA, exist_ok=True)
        with open(META, "w") as f:
            json.dump({"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}, f)
    print(f"ESPN requests this run: {CALLS}")


if __name__ == "__main__":
    main()
