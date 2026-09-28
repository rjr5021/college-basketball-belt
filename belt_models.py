"""
Models on top of the lineage, shared by Belt Holders and the College
Basketball Belt:

  * elo()        a plain Elo rating for every team from the full game history
                 (home edge, a pull back toward average between seasons)
  * belt_tree()  every way the next few belt games can go, with probabilities
  * outlook()    Monte Carlo over the remaining schedule: each team's chance of
                 holding the belt when the schedule on file runs out
  * champions()  season by season: did the belt finish with the champion?
  * losers()     the Losers Belt -- same walk, but the team that LOSES to the
                 holder takes it

Tuning (K, home edge, carry-over) is deliberately simple and per sport; the
point is honest rough odds, not a betting model.
"""

import bisect
import random
from collections import Counter, defaultdict

import belt_engine

PARAMS = {  # K, home edge (Elo points), share of the gap to 1500 kept between seasons
    "nfl": (20, 48, 0.67), "nba": (16, 70, 0.7), "nhl": (8, 35, 0.7), "mlb": (4, 24, 0.67), "cbb": (22, 90, 0.7),
}


def elo(key, games):
    k, hfa, keep = PARAMS.get(key, (20, 50, 0.7))
    r = defaultdict(lambda: 1500.0)
    season = None
    for g in games:
        if g["season"] != season:
            if season is not None:
                for t in list(r):
                    r[t] = 1500 + (r[t] - 1500) * keep
            season = g["season"]
        h, a = g["home"], g["away"]
        edge = 0 if g.get("neutral") else hfa
        exp_h = 1 / (1 + 10 ** (-(r[h] + edge - r[a]) / 400))
        hp, ap = g["home_points"], g["away_points"]
        res = 1.0 if hp > ap else 0.0 if hp < ap else 0.5
        margin = abs(hp - ap)
        mult = 1.0 if key in ("mlb", "nhl") else (1 + min(margin, 30) / (60 if key in ("nba", "cbb") else 30))
        delta = k * mult * (res - exp_h)
        r[h] += delta
        r[a] -= delta
    return dict(r), hfa


def win_prob(ratings, hfa, home, away, neutral=False, holder=None):
    """Chance `holder` (home or away) wins; draws split evenly where they exist."""
    rh, ra = ratings.get(home, 1500.0), ratings.get(away, 1500.0)
    p_home = 1 / (1 + 10 ** (-(rh + (0 if neutral else hfa) - ra) / 400))
    return p_home if holder == home else 1 - p_home


def _index(upcoming):
    by = defaultdict(list)
    for g in upcoming:
        for t in (g["home"], g["away"]):
            by[t].append(g)
    for t in by:
        by[t].sort(key=lambda g: (g["date"], g.get("kickoff") or "", str(g.get("id"))))
    keys = {t: [(g["date"], g.get("kickoff") or "", str(g.get("id"))) for g in v] for t, v in by.items()}
    return by, keys


def _next(by, keys, team, after):
    lst = by.get(team)
    if not lst:
        return None
    i = bisect.bisect_right(keys[team], after)
    return lst[i] if i < len(lst) else None


def belt_tree(holder, upcoming, ratings, hfa, depth=4, today=""):
    """Nested dict: the holder's next game, the chance they win it, and the
    subtree for each outcome, `depth` belt games deep."""
    by, keys = _index(upcoming)

    def node(team, after, d):
        if d == 0:
            return None
        g = _next(by, keys, team, after)
        if not g:
            return None
        opp = g["away"] if g["home"] == team else g["home"]
        p = win_prob(ratings, hfa, g["home"], g["away"], g.get("neutral"), holder=team)
        key = (g["date"], g.get("kickoff") or "", str(g.get("id")))
        return {"date": g["date"], "holder": team, "challenger": opp, "home": g["home"], "p": round(p, 3),
                "win": node(team, key, d - 1), "lose": node(opp, key, d - 1)}

    return node(holder, (today, "", ""), depth)


def outlook(holder, upcoming, ratings, hfa, sims=4000, seed=7, today=""):
    """Chance each team holds the belt after the last game on file."""
    by, keys = _index(upcoming)
    rng = random.Random(seed)
    cache = {}
    end = Counter()
    for _ in range(sims):
        team, after = holder, (today, "", "")
        while True:
            g = _next(by, keys, team, after)
            if not g:
                break
            gid = str(g.get("id"))
            if gid not in cache:
                cache[gid] = win_prob(ratings, hfa, g["home"], g["away"], g.get("neutral"), holder=g["home"])
            p_home = cache[gid]
            home_wins = rng.random() < p_home
            winner = g["home"] if home_wins else g["away"]
            team = winner
            after = (g["date"], g.get("kickoff") or "", gid)
        end[team] += 1
    last = max((g["date"] for g in upcoming), default=None)
    return {"through": last, "sims": sims,
            "odds": sorted(((t, round(n / sims, 4)) for t, n in end.items()), key=lambda x: -x[1])}


def champions(games, reigns, postseason_label="postseason"):
    """Season by season: the winner of the season's last postseason game, and
    who held the belt when the season's games ran out."""
    by_season = defaultdict(list)
    for g in games:
        by_season[g["season"]].append(g)
    out = []
    for s in sorted(by_season):
        gs = by_season[s]
        post = [g for g in gs if g["season_type"] != "regular"]
        if not post:
            continue
        final = post[-1]
        champ = final["home"] if final["home_points"] > final["away_points"] else final["away"] \
            if final["away_points"] > final["home_points"] else None
        last_date = gs[-1]["date"]
        holder = None
        for r in reigns:
            if r["start_date"] <= last_date:
                holder = r["team"]
            else:
                break
        out.append({"season": s, "champion": champ, "holder": holder, "match": champ == holder,
                    "final_date": final["date"]})
    return out


def losers(league_key, games, tie_rule, recent, today, gap_days):
    """The Losers Belt: invert every score and walk the same engine."""
    inv = [{**g, "home_points": g["away_points"], "away_points": g["home_points"]} for g in games]
    bgs, reigns, vac = belt_engine.resolve_vacancies(inv, tie_rule, None, None, recent, today,
                                                    gap_threshold_days=gap_days, first_game_date=inv[0]["date"])
    counts = Counter()
    from datetime import date as _d
    for i, r in enumerate(reigns, 1):
        counts[r["team"]] += 1
        r["reign_no"] = counts[r["team"]]
        r["index"] = i
        r["days"] = max(0, (_d.fromisoformat(r.get("end_date") or today) - _d.fromisoformat(r["start_date"])).days)
    days, n = Counter(), Counter()
    for r in reigns:
        days[r["team"]] += r["days"]
        n[r["team"]] += 1
    changes = [b for b in bgs if b["outcome"] == "changed"]
    return {
        "current": reigns[-1], "reigns": len(reigns), "games": len(bgs),
        "most_days": days.most_common(10), "most_reigns": n.most_common(10),
        "longest": [{"team": r["team"], "start": r["start_date"], "end": r.get("end_date"), "defenses": r.get("defenses", 0),
                     "days": r["days"]} for r in sorted(reigns, key=lambda r: (-r.get("defenses", 0), -r["days"]))[:10]],
        "recent": [{"date": b["date"], "new": b["new_holder"], "from": b["holder"], "score": b["score"],
                    "home": b["home"]} for b in changes[-15:]][::-1],
        "all": [[r["index"], r["team"], r["start_date"], r.get("end_date"), r.get("defenses", 0), r["days"]] for r in reigns],
        "first": {"date": bgs[0]["date"], "team": bgs[0]["new_holder"], "opp": bgs[0]["opponent"]} if bgs else None,
    }


def standings(games, reigns):
    """Season by season: the best regular-season record vs. who held the belt
    when the regular season ended."""
    by_season = defaultdict(list)
    for g in games:
        if g["season_type"] == "regular":
            by_season[g["season"]].append(g)
    out = []
    for s in sorted(by_season):
        gs = by_season[s]
        rec = defaultdict(lambda: [0, 0, 0])
        for g in gs:
            h, a, hp, ap = g["home"], g["away"], g["home_points"], g["away_points"]
            if hp > ap:
                rec[h][0] += 1
                rec[a][1] += 1
            elif ap > hp:
                rec[a][0] += 1
                rec[h][1] += 1
            else:
                rec[h][2] += 1
                rec[a][2] += 1
        n_games = sorted((sum(v) for v in rec.values()))
        min_games = n_games[len(n_games) // 2] * 0.6 if n_games else 0

        def pct(v):
            n = sum(v)
            return (v[0] + v[2] / 2) / n if n else 0

        eligible = [(t, v) for t, v in rec.items() if sum(v) >= min_games]
        if not eligible:
            continue
        best_t, best_v = max(eligible, key=lambda tv: (pct(tv[1]), tv[1][0]))
        last = gs[-1]["date"]
        holder = None
        for r in reigns:
            if r["start_date"] <= last:
                holder = r["team"]
            else:
                break
        hv = rec.get(holder, [0, 0, 0])
        rank = 1 + sum(1 for t, v in eligible if pct(v) > pct(hv))
        out.append({"season": s, "best": best_t, "best_rec": best_v, "holder": holder, "holder_rec": hv,
                    "holder_rank": rank, "teams": len(eligible), "match": holder == best_t})
    return out
