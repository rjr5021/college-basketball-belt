"""
The belt against the AP poll: for every AP Top 25 (data/polls/*.csv, from
fetch_polls.py), who held the belt that day and where the poll ranked them.
Returns None when there's no poll data yet.
"""

import bisect
import csv
import glob
import os
from collections import defaultdict


def _polls():
    by = defaultdict(dict)
    for p in sorted(glob.glob(os.path.join("data", "polls", "*.csv"))):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r.get("date") or not r.get("team_id") or not str(r.get("rank", "")).isdigit():
                    continue
                by[(int(r["season"]), r["date"])][str(r["team_id"])] = int(r["rank"])
    return sorted(by.items(), key=lambda kv: kv[0][1])


def compute(reigns):
    polls = _polls()
    if not polls:
        return None
    starts = [r["start_date"] for r in reigns]

    def holder_on(day):
        i = bisect.bisect_right(starts, day) - 1
        if i < 0:
            return None
        r = reigns[i]
        return r["team"] if not r.get("end_date") or day < r["end_date"] else None

    seasons = {}
    n = ranked = top1 = top5 = 0
    runs, run = [], None
    top1_list = []
    for (season, day), ranks in polls:
        h = holder_on(day)
        if h is None:
            continue
        rk = ranks.get(str(h))
        n += 1
        ranked += rk is not None
        top1 += rk == 1
        top5 += rk is not None and rk <= 5
        no1 = next((t for t, v in ranks.items() if v == 1), None)
        s = seasons.setdefault(season, {"season": season, "polls": 0, "ranked": 0, "top1": 0, "best": None, "best_team": None,
                                        "final_no1": None, "final_holder": None, "final_rank": None, "holders": []})
        s["polls"] += 1
        s["ranked"] += rk is not None
        s["top1"] += rk == 1
        if rk is not None and (s["best"] is None or rk < s["best"]):
            s["best"], s["best_team"] = rk, h
        s["final_no1"], s["final_holder"], s["final_rank"] = no1, h, rk
        if h not in s["holders"]:
            s["holders"].append(h)
        if rk == 1:
            top1_list.append([day, h])
        # unranked stretches, per reign
        if rk is None:
            if run and run["team"] == h and run["season"] == season:
                run["last"], run["polls"] = day, run["polls"] + 1
            else:
                run = {"team": h, "season": season, "first": day, "last": day, "polls": 1}
                runs.append(run)
        else:
            run = None
    for s in seasons.values():
        s["no1_held"] = s["final_no1"] in s["holders"] if s["final_no1"] else None
    last_key, last_ranks = polls[-1]
    cur = reigns[-1]["team"] if not reigns[-1].get("end_date") else None
    return {
        "polls": n, "ranked": ranked, "top1": top1, "top5": top5,
        "first": polls[0][0][1], "last": last_key[1], "last_season": last_key[0],
        "current": {"team": cur, "rank": last_ranks.get(str(cur)) if cur else None, "date": last_key[1],
                    "no1": next((t for t, v in last_ranks.items() if v == 1), None)},
        "seasons": [seasons[k] for k in sorted(seasons)],
        "unranked": [[r["team"], r["first"], r["last"], r["polls"]] for r in sorted(runs, key=lambda r: -r["polls"])[:15]],
        "top1_days": top1_list[-10:],
    }


def teams(m):
    """Every team id the page mentions (for lineage team_info)."""
    if not m:
        return set()
    out = {m["current"]["team"], m["current"]["no1"]}
    for s in m["seasons"]:
        out |= {s["final_no1"], s["final_holder"], s["best_team"]} | set(s["holders"])
    out |= {r[0] for r in m["unranked"]}
    return {t for t in out if t}
