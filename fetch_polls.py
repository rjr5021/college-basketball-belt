#!/usr/bin/env python3
"""
Keep data/polls/<season>.csv (the AP Top 25, week by week) current from the
CollegeBasketballData API's /rankings endpoint.

    python3 fetch_polls.py            # backfill if empty; else refresh the current season once a day in season
    python3 fetch_polls.py --full     # refetch every season

One call per season. The backfill is ~80 calls, once; after that it's one
call a day from October to April, so the free tier's monthly quota is safe.
Needs CBBD_API_KEY in the environment (a GitHub Actions secret).
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timezone

import fetch_games as FG

DATA = os.path.join("data", "polls")
META = os.path.join(DATA, "_meta.json")
FIELDS = ["season", "week", "date", "poll", "team_id", "team", "rank", "points", "first"]
FIRST = 1949          # the AP basketball poll began in the 1948-49 season


def pick(g, *names):
    for n in names:
        if g.get(n) not in (None, ""):
            return g[n]
    return ""


def fetch(season):
    got = FG.api("/rankings", season=season) or []
    if got and not getattr(fetch, "shown", False):
        print("  fields:", sorted(got[0].keys()))
        fetch.shown = True
    rows = []
    for g in got:
        poll = str(pick(g, "pollType", "poll", "poll_type"))
        pl = poll.lower().replace("coaches", "")
        if "ap" not in pl and "associated" not in pl:
            continue
        dt = str(pick(g, "pollDate", "date", "poll_date"))[:10]
        rows.append({"season": season, "week": pick(g, "week"), "date": dt, "poll": poll,
                     "team_id": pick(g, "teamId", "team_id"), "team": pick(g, "team", "school"),
                     "rank": pick(g, "ranking", "rank"), "points": pick(g, "points"),
                     "first": pick(g, "firstPlaceVotes", "first_place_votes")})
    rows.sort(key=lambda r: (str(r["date"]), str(r["week"]).zfill(3), str(r["rank"]).zfill(3)))
    return rows


def write(season, rows):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, f"{season}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    polls = len({(r["week"], r["date"]) for r in rows})
    print(f"  season {season}: {polls} AP polls, {len(rows)} rows")


def main():
    if not FG.KEY:
        print("no CBBD_API_KEY; skipping polls")
        return
    today = date.today()
    cur = FG.current_season(today)
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
    for s in seasons:
        try:
            write(s, fetch(s))
        except Exception as e:  # noqa: BLE001
            print(f"  season {s}: {e}")
    if seasons:
        os.makedirs(DATA, exist_ok=True)
        with open(META, "w") as f:
            json.dump({"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}, f)
    print(f"API calls this run: {FG.CALLS}")


if __name__ == "__main__":
    main()
