#!/usr/bin/env python3
"""
Player box scores for Women's College Basketball Belt games (CBB-7), from the
sportsdataverse wehoop project's ESPN player box files, one per season
(github.com/sportsdataverse/sportsdataverse-data, CC BY 4.0). The same project
already supplies the women's schedules (fetch_women.py), and the game and team
ids are ESPN's, so belt games match by id. No API key, no call budget.

    data/women/box/<season>.json   {"games": {belt game n: {"gid", "players": [...]}}}
    data/women/box/_meta.json      seasons already complete on file (never downloaded again)

Row: [athleteId, name, side h/a, MIN, PTS, REB, AST, STL, BLK, FGM, FGA, 3PM, 3PA, FTM, FTA]
(the men's columns, so the shared player pages and leaders work as-is).

    python3 fetch_women_box.py     # needs pyarrow

A box is kept only when each side's player points add up to the final score; a
partial one is stored empty so it isn't looked up again.
"""

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date

import box_store

LEAGUE = "women"
SRC = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
       "espn_womens_college_basketball_player_boxscores/player_box_{season}.parquet")
META = os.path.join("data", LEAGUE, "box", "_meta.json")
FIRST = 2014          # season 2014 = 2013-14. The files go back to 2003-04, but every box before
                      # 2013-14 is partial (player points don't add up to the score), so those aren't used
COLS = ["minutes", "points", "rebounds", "assists", "steals", "blocks", "field_goals_made", "field_goals_attempted",
        "three_point_field_goals_made", "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted"]
ORDER = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA"]


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "collegebasketballbelt.com box scores"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"{url}: {err}")


def num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:            # NaN
        return None
    return int(f) if f.is_integer() else round(f, 1)


def season_rows(season, want):
    """{game_id: [(team_id, row)]} for the belt games in `want` (a set of game ids)."""
    import pyarrow.parquet as pq
    raw = get(SRC.format(season=season))
    if raw is None:
        return None
    t = pq.read_table(io.BytesIO(raw), columns=["game_id", "team_id", "athlete_id", "athlete_display_name", "did_not_play"] + COLS)
    d = t.to_pydict()
    out = defaultdict(list)
    for i in range(t.num_rows):
        gid = str(d["game_id"][i])
        if gid not in want or d["did_not_play"][i] or d["athlete_id"][i] is None:
            continue
        stats = [num(d[c][i]) for c in COLS]
        out[gid].append((str(d["team_id"][i]), [d["athlete_id"][i], d["athlete_display_name"][i] or "?", None] + stats))
    return out


def current_season(today):
    return today.year + 1 if today.month >= 8 else today.year


def main():
    with open(os.path.join("data", LEAGUE, "lineage.json")) as f:
        lin = json.load(f)
    bgs = [bg for bg in lin["belt_games"] if bg["season"] >= FIRST and bg.get("game_id")]
    by_gid = {str(bg["game_id"]): bg for bg in bgs}
    # re-key what's on file by game id (belt game numbers shift when older games are added)
    games = {str(by_gid[str(g["gid"])]["n"]): g for g in box_store.load_all(LEAGUE).values() if str(g.get("gid")) in by_gid}
    meta = {}
    if os.path.exists(META):
        with open(META) as f:
            meta = json.load(f)
    done = set(meta.get("done_seasons", []))
    cur = current_season(date.today())
    todo = defaultdict(set)
    for bg in bgs:
        if bg["season"] in done or str(bg["n"]) in games:
            continue
        todo[bg["season"]].add(str(bg["game_id"]))
    print(f"{len(games):,} women's belt games on file; {sum(len(v) for v in todo.values()):,} to look up in {len(todo)} season file(s)")
    failed = False
    for season in sorted(todo):
        try:
            rows = season_rows(season, todo[season])
        except Exception as e:  # noqa: BLE001
            print(f"  {season}: {e}")
            failed = True
            continue
        if rows is None:
            print(f"  {season}: no file published")
            if season < cur:
                done.add(season)
            continue
        hit = partial = 0
        for gid in todo[season]:
            bg = by_gid[gid]
            players = [[r[0], r[1], "h" if tid == str(bg["home"]) else "a"] + r[3:] for tid, r in rows.get(gid, [])]
            if not players:
                continue
            hp, ap = (int(x) for x in bg["score"].split("-"))
            pts = {side: sum(r[4] or 0 for r in players if r[2] == side) for side in "ha"}
            if (pts["h"], pts["a"]) == (hp, ap):
                games[str(bg["n"])] = {"gid": bg["game_id"], "players": players}
                hit += 1
            elif season < cur:
                games[str(bg["n"])] = {"gid": bg["game_id"], "players": []}      # partial box: don't ask again
                partial += 1
        print(f"  {season}: {hit} of {len(todo[season])} belt games matched" + (f", {partial} partial box(es) skipped" if partial else ""))
        if season < cur:
            done.add(season)      # a finished season's file won't gain games; don't download it again
    season_of = {str(bg["n"]): bg["season"] for bg in bgs}
    box_store.save_all(LEAGUE, games, season_of,
                       {"source": "https://github.com/sportsdataverse/sportsdataverse-data (wehoop, ESPN; CC BY 4.0)", "cols": ORDER})
    os.makedirs(os.path.dirname(META), exist_ok=True)
    with open(META, "w") as f:
        json.dump({"done_seasons": sorted(done)}, f)
    have = sum(1 for g in games.values() if g["players"])
    print(f"{have:,} women's belt games have box scores")
    return 1 if failed and not have else 0


if __name__ == "__main__":
    sys.exit(main())
