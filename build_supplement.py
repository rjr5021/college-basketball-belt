#!/usr/bin/env python3
"""
Fill the gap in the CollegeBasketballData game list before 2000-01: it has
almost none of that era's neutral-site games (holiday tournaments,
conference tournaments, Madison Square Garden doubleheaders). Prof. John
Trono's NCAA Men's Basketball Scores Archive (St. Michael's College) has
every Division I vs. Division I game from 1949-50 through 1999-2000:

    https://academics.smcvt.edu/jtrono/BBallArchive.htm

fetch_trono.py saved the archive to data/trono/. This script:

1. reads every dated Trono file (the regular-season files, which include the
   conference tournaments, plus the small CCA/NCIT/NCT postseason files;
   the NCAA and NIT files have no dates, and our data has those games);
2. works out which of our team ids each Trono team code is, from the games
   both sources share (same date +/- 1 day and same final score), with
   data/trono_codes.json overrides for anything that can't be inferred;
3. writes every Trono game our data doesn't have to
   data/supplement/trono.csv, in the same columns as data/games/*.csv, so
   cbb_data.py loads it with everything else.

A Trono game counts as already present if our data has a game between the
same two teams within 3 days, or a game on the same date (+/- 1) with the
same final score involving one of the two teams. Re-run after fetch_games.py --full or new archive files:

    python3 build_supplement.py
"""

import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

TRONO = os.path.join("data", "trono")
OUT = os.path.join("data", "supplement", "trono.csv")
OVERRIDES = os.path.join("data", "trono_codes.json")
FIELDS = ["id", "date", "start_et", "season", "season_type", "tournament", "status",
          "home", "away", "home_id", "away_id", "home_points", "away_points", "neutral",
          "home_conf", "away_conf", "home_seed", "away_seed", "venue", "city", "state", "notes"]
MONTH = {1: 10, 2: 11, 3: 12, 4: 1, 5: 2, 6: 3, 7: 4}
EXTRA = {"nct": "NCT", "ncit": "NCIT", "cca": "CCA"}
ID_BASE = 900_000_000


def trono_games():
    """[(season, date, code1, pts1, code2, pts2, loc, tournament)]"""
    out = []
    for p in sorted(glob.glob(os.path.join(TRONO, "*.txt"))):
        name = os.path.basename(p)[:-4]
        m = re.match(r"^(\d{2})_(\d{2,4})[._](\w+)$", name)
        if not m:
            continue
        kind = m.group(3).lower()
        if kind != "dts" and kind not in EXTRA:
            continue
        end = int(m.group(2))
        season = end if end > 1000 else (1900 + end if end >= 50 else 2000 + end)
        if name.startswith("49_50"):
            season = 1950
        for line in open(p):
            f = line.split()
            if len(f) < 5 or not f[0].isdigit():
                continue
            code = f[0]
            mo, dy = int(code[:-2]), int(code[-2:])
            if mo not in MONTH:
                continue
            mm = MONTH[mo]
            yy = season - 1 if mm >= 10 else season
            try:
                d = date(yy, mm, dy).isoformat()
                p1, p2 = int(f[2]), int(re.sub(r"\D", "", f[4]))
            except ValueError:
                continue
            loc = (f[5] if len(f) > 5 else "N")[:1].upper()
            out.append((season, d, f[1], p1, f[3], p2, loc, EXTRA.get(kind, "")))
    return out


def our_games():
    rows = []
    for p in sorted(glob.glob(os.path.join("data", "games", "*.csv"))):
        with open(p, newline="", encoding="utf-8") as f:
            rows += [r for r in csv.DictReader(f) if r["status"] == "final" and r["home_points"] != ""]
    return rows


def shift(d, k):
    return (date.fromisoformat(d) + timedelta(days=k)).isoformat()


def main():
    tg = trono_games()
    ours = our_games()
    seasons = {g[0] for g in tg}
    ours = [r for r in ours if int(r["season"]) in seasons]
    print(f"{len(tg):,} dated Trono games; {len(ours):,} of our games in those seasons")
    by_score = defaultdict(list)
    for r in ours:
        hp, ap = int(r["home_points"]), int(r["away_points"])
        for k in (-1, 0, 1):
            by_score[(shift(r["date"], k), max(hp, ap), min(hp, ap))].append(r)
    # ---- 1. infer code -> team id from shared games
    votes = defaultdict(Counter)
    names = {}
    for s, d, c1, p1, c2, p2, loc, t in tg:
        cands = by_score.get((d, max(p1, p2), min(p1, p2)), [])
        if len(cands) != 1 or p1 == p2:
            continue
        r = cands[0]
        hp, ap = int(r["home_points"]), int(r["away_points"])
        s1 = r["home_id"] if hp == p1 else r["away_id"]
        s2 = r["away_id"] if hp == p1 else r["home_id"]
        votes[c1][s1] += 1
        votes[c2][s2] += 1
        names[r["home_id"]], names[r["away_id"]] = r["home"], r["away"]
    codes = {c for g in tg for c in (g[2], g[4])}
    mapping, weak = {}, []
    for c in codes:
        v = votes.get(c)
        if v:
            (tid, n), total = v.most_common(1)[0], sum(v.values())
            mapping[c] = tid
            if n < 5 or n / total < 0.8:
                weak.append((c, names.get(tid), n, total))
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES) as f:
            for c, tid in json.load(f).items():
                if tid:
                    mapping[c] = str(tid)
                else:
                    mapping.pop(c, None)
    unmapped = sorted(codes - set(mapping))
    print(f"{len(codes)} Trono codes: {len(mapping)} mapped, {len(unmapped)} unmapped {unmapped}")
    if weak:
        print("low-confidence codes (code, team, votes, total):", sorted(weak))
    # ---- 2. games we don't have
    pair_days = defaultdict(list)
    conf = defaultdict(Counter)
    for r in ours:
        pair_days[frozenset((r["home_id"], r["away_id"]))].append(r["date"])
        for side in ("home", "away"):
            if r[side + "_conf"]:
                conf[(int(r["season"]), r[side + "_id"])][r[side + "_conf"]] += 1
            names[r[side + "_id"]] = r[side]
    add, skipped = [], Counter()
    for i, (s, d, c1, p1, c2, p2, loc, tour) in enumerate(tg):
        a, b = mapping.get(c1), mapping.get(c2)
        if not a or not b:
            skipped["unmapped team"] += 1
            continue
        if any(abs((date.fromisoformat(d) - date.fromisoformat(x)).days) <= 3 for x in pair_days.get(frozenset((a, b)), [])):
            continue
        if any(a in (r["home_id"], r["away_id"]) or b in (r["home_id"], r["away_id"])
               for r in by_score.get((d, max(p1, p2), min(p1, p2)), [])):
            skipped["same date and score, one team differs"] += 1
            continue
        home, away, hp, ap = (a, b, p1, p2) if loc != "A" else (b, a, p2, p1)
        cf = lambda t: (conf.get((s, t)) or Counter({"": 1})).most_common(1)[0][0]
        add.append({"id": ID_BASE + i, "date": d, "start_et": "", "season": s,
                    "season_type": "postseason" if tour else "regular", "tournament": tour, "status": "final",
                    "home": names.get(home, home), "away": names.get(away, away), "home_id": home, "away_id": away,
                    "home_points": hp, "away_points": ap, "neutral": "1" if loc == "N" else "0",
                    "home_conf": cf(home), "away_conf": cf(away), "home_seed": "", "away_seed": "",
                    "venue": "", "city": "", "state": "", "notes": "Trono archive"})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    add.sort(key=lambda r: (r["date"], r["id"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(add)
    by_loc = Counter(("neutral" if r["neutral"] == "1" else "home/away") for r in add)
    print(f"added {len(add):,} games ({dict(by_loc)}); skipped {dict(skipped)}")


if __name__ == "__main__":
    main()
