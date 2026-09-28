#!/usr/bin/env python3
"""
Player box scores for College Basketball Belt games, from the
CollegeBasketballData API's /games/players endpoint.

One call per belt-game date (a two-day window, since the API's start times
are UTC and ours are Eastern), matched to the belt game by the API's own game
id, which is the id our game data already uses. Both teams' players come back
in the same call. Stored per season with the shared box_store:

    data/cbb/box/<season>.json   {"games": {belt game n: {"gid", "players": [...]}}}
    data/cbb/box/_meta.json      seasons the API has no player data for

Row: [athleteId, name, side h/a, MIN, PTS, REB, AST, STL, BLK, FGM, FGA, 3PM, 3PA, FTM, FTA]
(the same columns as the NBA belt, so the shared player pages work as-is).

    python3 fetch_boxscores.py        # fetch what's missing, newest first, up to CBB_BOX_MAX calls

The first run is a one-time backfill (about one call per belt-game date since
the data starts, ~900 calls); after that it's a call or two per new belt
game. Needs CBBD_API_KEY in the environment.
"""

import json
import os
from collections import defaultdict
from datetime import date, timedelta

import box_store
import fetch_games as FG

LEAGUE = "cbb"
META = os.path.join("data", LEAGUE, "box", "_meta.json")
MAX_CALLS = int(os.environ.get("CBB_BOX_MAX", "1500"))
FIRST = int(os.environ.get("CBB_BOX_FIRST", "1996"))   # probe back this far; empty seasons are remembered
ORDER = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA"]


def pick(d, *names):
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return None


def num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 1)


def made_att(p, *names):
    for n in names:
        v = p.get(n)
        if isinstance(v, dict):
            return num(pick(v, "made", "m")), num(pick(v, "attempted", "attempts", "a"))
    return None, None


def row(p, side):
    fgm, fga = made_att(p, "fieldGoals", "fieldGoalsMade")
    tpm, tpa = made_att(p, "threePointFieldGoals", "threePointers", "threes")
    ftm, fta = made_att(p, "freeThrows")
    reb = p.get("rebounds")
    reb = num(pick(reb, "total")) if isinstance(reb, dict) else num(reb)
    pid = pick(p, "athleteId", "playerId", "id", "athleteSourceId")
    return [pid, pick(p, "name", "athlete", "player") or "?", side,
            num(pick(p, "minutes", "mins")), num(pick(p, "points")), reb, num(pick(p, "assists")),
            num(pick(p, "steals")), num(pick(p, "blocks")), fgm, fga, tpm, tpa, ftm, fta]


def main():
    if not FG.KEY:
        print("no CBBD_API_KEY; skipping box scores")
        return
    with open(os.path.join("data", "lineage.json")) as f:
        d = json.load(f)
    games = box_store.load_all(LEAGUE)
    meta = {}
    if os.path.exists(META):
        with open(META) as f:
            meta = json.load(f)
    empty = set(meta.get("empty_seasons", []))
    today = date.today()
    todo = defaultdict(list)
    for bg in d["belt_games"]:
        if str(bg["n"]) in games or bg["season"] < FIRST or bg["season"] in empty or not bg.get("game_id"):
            continue
        todo[bg["date"]].append(bg)
    dates = sorted(todo, reverse=True)
    print(f"{len(games):,} belt games on file; {sum(len(v) for v in todo.values()):,} to fetch on {len(dates):,} dates; up to {MAX_CALLS} calls")
    tried, hits = defaultdict(int), defaultdict(int)
    shown = False
    for day in dates:
        if FG.CALLS >= MAX_CALLS:
            print("call budget for this run reached; the rest next run")
            break
        season = todo[day][0]["season"]
        if season in empty:
            continue
        dd = date.fromisoformat(day)
        try:
            got = FG.api("/games/players", season=season, startDateRange=FG.iso(dd), endDateRange=FG.iso(dd + timedelta(days=2))) or []
        except Exception as e:  # noqa: BLE001
            print(f"  {day}: {e}")
            continue
        if got and not shown:
            print("  record fields:", sorted(got[0].keys()))
            pl = got[0].get("players") or []
            if pl:
                print("  player fields:", sorted(pl[0].keys()))
            shown = True
        by_gid = defaultdict(list)
        for rec in got:
            by_gid[str(pick(rec, "gameId", "game_id", "id"))].append(rec)
        if not got:
            tried[season] += 1
        matched = 0
        for bg in todo[day]:
            recs = by_gid.get(str(bg["game_id"]), [])
            players = []
            for rec in recs:
                tid = str(pick(rec, "teamId", "team_id") or "")
                home = pick(rec, "isHome")
                side = "h" if (tid == str(bg["home"]) if tid else home) else "a"
                players += [row(p, side) for p in rec.get("players") or []]
            players = [r for r in players if r[0] is not None]
            if players:
                hits[season] += 1
                matched += 1
                games[str(bg["n"])] = {"gid": bg["game_id"], "players": players}
            elif not got and (today - dd).days > 3:
                games[str(bg["n"])] = {"gid": bg["game_id"], "players": []}   # no box scores that day; don't ask again
        if got and not matched:
            print(f"  {day}: {len(got)} records but no match for game ids {[bg['game_id'] for bg in todo[day]]}; "
                  f"sample ids {list(by_gid)[:5]}")
        # an old season with nothing on its first dates: the data doesn't go back that far
        if season < 2010 and tried[season] >= 3 and hits[season] == 0:
            empty.add(season)
            print(f"  season {season}: no player data; skipping it from now on")
    box_store.save_all(LEAGUE, games, {str(bg["n"]): bg["season"] for bg in d["belt_games"]},
                       {"source": "https://collegebasketballdata.com", "cols": ORDER})
    os.makedirs(os.path.dirname(META), exist_ok=True)
    with open(META, "w") as f:
        json.dump({"empty_seasons": sorted(empty)}, f)
    have = [int(k) for k, v in games.items() if v["players"]]
    first = min((bg["season"] for bg in d["belt_games"] if bg["n"] in set(have)), default=None)
    print(f"API calls this run: {FG.CALLS}; {len(have):,} belt games have box scores" + (f", back to the {first} season" if first else ""))


if __name__ == "__main__":
    main()
