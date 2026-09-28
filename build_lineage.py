#!/usr/bin/env python3
"""
Compute the College Basketball Belt lineage with the shared engine and write
data/lineage.json for build_site.py.

    python3 build_lineage.py

belt_engine.py is the same file the College Football Belt and Belt Holders
use -- copy it over whenever the football repo's copy changes.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import date

import belt_engine
import belt_extras as X
import cbb_data as D


def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def main(today=None):
    today = today or date.today().isoformat()
    games, upcoming, names, teams, elig = D.load(today)
    inv = {v: k for k, v in names.items()}
    seed_team, seed_opp = inv[D.SEED["team_name"]], inv.get(D.SEED["opponent_name"])
    start = {"team": seed_team, "start_date": D.SEED["date"], "won_from": seed_opp,
             "won_score": D.SEED["score"], "defenses": 0, "last_game_date": D.SEED["date"], "seed": True}
    latest = max(g["season"] for g in games)
    recent = {t for g in games if g["season"] >= latest - 1 for t in (g["home"], g["away"])}
    belt_games, reigns, vacancies = belt_engine.resolve_vacancies(
        games, "holder", seed_team, start, recent, today, first_game_date=D.SEED["date"])
    by_id = {g["id"]: g for g in games}

    season_by_date = {}
    for g in games:
        season_by_date.setdefault(g["date"], g["season"])

    def season_at(d):
        if d in season_by_date:
            return season_by_date[d]
        earlier = [x for x in season_by_date if x <= d]
        return season_by_date[max(earlier)] if earlier else D.FIRST_SEASON

    counts = Counter()
    for i, r in enumerate(reigns):
        counts[r["team"]] += 1
        r["reign_no"] = counts[r["team"]]
        r["index"] = i + 1
        r["days"] = max(0, days_between(r["start_date"], r.get("end_date") or today))
        r["season"] = season_at(r["start_date"]) if not r.get("seed") else 1949
        r["name"] = names.get(r["team"], r["team"])
        if r.get("won_from"):
            r["won_from_name"] = names.get(r["won_from"], r["won_from"])
        if r.get("lost_to"):
            r["lost_to_name"] = names.get(r["lost_to"], r["lost_to"])

    for bg in belt_games:
        g = by_id.get(bg["game_id"], {})
        bg["holder_name"] = names.get(bg["holder"]) if bg.get("holder") else None
        bg["opponent_name"] = names.get(bg["opponent"])
        bg["new_holder_name"] = names.get(bg["new_holder"])
        bg["tournament"] = g.get("tournament", "")
        if g.get("tournament") == "NCAA":
            bg["round"] = D.ncaa_round(g.get("notes"))[0]

    current = reigns[-1]
    holder = current["team"]

    # next title defense
    next_game = None
    for g in upcoming:
        if holder in (g["home"], g["away"]):
            ch = g["away"] if g["home"] == holder else g["home"]
            next_game = {"date": g["date"], "kickoff": g.get("kickoff"), "holder": holder,
                         "challenger": ch, "challenger_name": names.get(ch, ch),
                         "holder_home": g["home"] == holder, "neutral": g["neutral"],
                         "venue": g.get("venue"), "city": g.get("city"), "state": g.get("state")}
            break

    # records
    total_days, n_reigns, n_def = defaultdict(int), Counter(), Counter()
    for r in reigns:
        total_days[r["team"]] += r["days"]
        n_reigns[r["team"]] += 1
        n_def[r["team"]] += r.get("defenses", 0)
    changes = [bg for bg in belt_games if bg["outcome"] == "changed"]
    records = {
        "most_days": sorted(total_days.items(), key=lambda kv: -kv[1])[:10],
        "most_reigns": n_reigns.most_common(10),
        "most_defenses_total": n_def.most_common(10),
        "longest_reigns": [
            {"team": r["team"], "name": r["name"], "start_date": r["start_date"], "season": r["season"],
             "end_date": r.get("end_date"), "defenses": r.get("defenses", 0), "days": r["days"]}
            for r in sorted(reigns, key=lambda r: (-r.get("defenses", 0), -r["days"]))[:10]],
        "ncaa_changes": sum(1 for bg in changes if bg.get("tournament") == "NCAA"),
        "belt_games": len(belt_games),
        "programs": len(n_reigns),
        "changes": len(changes),
    }

    # March: who carried the belt into each NCAA tournament and how it ended
    march = []
    seasons = sorted({g["season"] for g in games})
    ncaa_by_season = defaultdict(list)
    for g in games:
        if g["tournament"] == "NCAA":
            ncaa_by_season[g["season"]].append(g)
    for s in seasons:
        ng = ncaa_by_season.get(s)
        if not ng:
            continue
        first = min(g["date"] for g in ng)
        # holder on the morning of the tournament's first day
        entering = None
        for r in reigns:
            if r["start_date"] < first and (r.get("end_date") is None or r["end_date"] >= first):
                entering = r
        final = max(ng, key=lambda g: (D.ncaa_round(g["notes"])[1] == 6, g["date"]))
        champ = final["home"] if final["home_points"] > final["away_points"] else final["away"]
        field = {t for g in ng for t in (g["home"], g["away"])}
        lost_round, lost_to = None, None
        sbg = [bg for bg in belt_games if bg["season"] == s and bg["date"] >= first]
        if entering:
            for bg in sbg:
                if bg["holder"] == entering["team"] and bg["outcome"] == "changed":
                    lost_round = bg.get("round") or ("NIT" if bg.get("tournament") == "NIT" else bg.get("tournament") or "Postseason")
                    lost_to = bg["new_holder_name"]
                    break
        season_changes = [bg for bg in belt_games if bg["season"] == s and bg["outcome"] == "changed"]
        end_holder = None
        for r in reigns:
            if season_at(r["start_date"]) <= s:
                end_holder = r
        march.append({
            "season": s, "label": D.season_label(s),
            "entering": entering["name"] if entering else None,
            "entering_team": entering["team"] if entering else None,
            "in_field": bool(entering and entering["team"] in field),
            "lost_round": lost_round, "lost_to": lost_to,
            "champion": names.get(champ), "champion_team": champ,
            "end_holder": end_holder["name"] if end_holder else None,
            "changes_after_start": sum(1 for bg in sbg if bg["outcome"] == "changed"),
            "season_changes": len(season_changes),
        })

    # title changes per month in the last completed season (Nov..Apr)
    last_done = max(s for s in seasons if ncaa_by_season.get(s))
    by_month = Counter()
    for bg in changes:
        if bg["season"] == last_done:
            by_month[int(bg["date"][5:7])] += 1
    months = [(m, by_month.get(m, 0)) for m in (11, 12, 1, 2, 3, 4)]

    lgx = {"key": "cbb", "name": "College Basketball", "season_label": D.season_label,
           "team_name": lambda code, season=None: names.get(code, code)}
    if next_game:
        next_game["season"] = cur_season = max(g["season"] for g in upcoming if holder in (g["home"], g["away"]))
        next_game["stadium"] = ", ".join(x for x in (next_game.get("venue"), next_game.get("city")) if x) or None
    X.annotate(lgx, games, belt_games, reigns)
    records.update(X.extra_records(lgx, belt_games, reigns, recent, today))
    extras = {"seasons": X.seasons(lgx, games, belt_games, reigns, today),
              "rivalries": X.rivalries(lgx, belt_games),
              "preview": X.preview(lgx, games, belt_games, reigns, next_game, today)}

    team_info = {}
    everyone = set(n_reigns) | {t for bg in belt_games for t in (bg.get("holder"), bg["opponent"]) if t}
    for tid in everyone | ({next_game["challenger"]} if next_game else set()):
        p, s2 = D.colors(teams, tid)
        team_info[tid] = {"name": names.get(tid, tid), "primary": p, "secondary": s2,
                          "mascot": D.nickname(teams, tid, names.get(tid, tid))}

    out = {
        "generated": today, "reigns": reigns, "belt_games": belt_games, "vacancies": vacancies,
        "current": current, "next_game": next_game, "records": records, "march": march,
        "last_season": last_done, "last_season_label": D.season_label(last_done), "months": months,
        "teams": team_info, "first_season": D.FIRST_SEASON, "seed": D.SEED, **extras,
    }
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "lineage.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"{len(reigns)} reigns, {len(belt_games)} belt games, {len(vacancies)} vacancies; "
          f"holder {current['name']} since {current['start_date']}"
          + (f"; next {next_game['date']} vs {next_game['challenger_name']}" if next_game else ""))
    return out


if __name__ == "__main__":
    main()
