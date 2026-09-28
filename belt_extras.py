"""
Everything the deeper pages need beyond the raw lineage, computed once per
build from the full game list and the engine's output:

  * each belt game numbered, tied to its reign, with the era names and the
    game's note (OT, SO, forfeit)
  * one summary per season (who carried the belt in and out, how often it moved)
  * rivalries: every pair of franchises that met with the belt on the line
  * a preview of the holder's next title defense (form, head-to-head, stakes)
  * extra records (droughts, busiest seasons, biggest title-change margins)

Pure data; build_site.py turns it into pages.
"""

from collections import Counter, defaultdict
from datetime import date


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _result(g, team):
    mine = g["home_points"] if g["home"] == team else g["away_points"]
    theirs = g["away_points"] if g["home"] == team else g["home_points"]
    return ("W" if mine > theirs else "L" if mine < theirs else "T"), mine, theirs


def annotate(league, games, belt_games, reigns):
    """Number belt games, attach reign numbers, era names and notes."""
    name = league["team_name"]
    by_id = {str(g["id"]): g for g in games}
    # reign lookup: walk reigns and belt games together in date order
    by_team = defaultdict(list)
    for r in reigns:
        by_team[r["team"]].append(r)

    def reign_for(team, d):
        for r in by_team.get(team, []):
            if r["start_date"] <= d and (r.get("end_date") is None or d <= r["end_date"]):
                return r
        return None

    for i, bg in enumerate(belt_games, 1):
        bg["n"] = i
        s = bg["season"]
        g = by_id.get(str(bg.get("game_id")), {})
        bg["note"] = g.get("note") or ""
        holder = bg.get("holder")
        if holder:
            r = reign_for(holder, bg["date"])
            bg["reign"] = r["index"] if r else None
            bg["holder_name"] = name(holder, s)
        else:
            bg["reign"] = 1
            bg["holder_name"] = None
        bg["opponent_name"] = name(bg["opponent"], s)
        bg["new_holder_name"] = name(bg["new_holder"], s)
        hp, ap = (int(x) for x in bg["score"].split("-"))
        bg["margin"] = abs(hp - ap)
    for r in reigns:
        r["belt_games"] = []
    reign_by_index = {r["index"]: r for r in reigns}
    for bg in belt_games:
        # a title change belongs to the loser's reign (its last game) and opens the winner's
        if bg.get("reign") in reign_by_index:
            reign_by_index[bg["reign"]]["belt_games"].append(bg["n"])
        if bg["outcome"] in ("changed", "established"):
            nr = reign_for(bg["new_holder"], bg["date"])
            if nr and nr["start_date"] == bg["date"]:
                nr.setdefault("opened_by", bg["n"])


def seasons(league, games, belt_games, reigns, today):
    label = league.get("season_label") or str
    out = []
    by_season = defaultdict(list)
    for bg in belt_games:
        by_season[bg["season"]].append(bg)
    all_seasons = sorted({g["season"] for g in games})
    holder_before = None
    for s in all_seasons:
        bgs = by_season.get(s, [])
        if not bgs:
            continue
        entering = bgs[0]["holder"] or bgs[0]["new_holder"]
        ending = bgs[-1]["new_holder"]
        changes = [b for b in bgs if b["outcome"] == "changed"]
        holders = []
        for b in [bgs[0]] + changes:
            h = b["new_holder"] if b in changes else entering
            if not holders or holders[-1] != h:
                holders.append(h)
        defs = Counter(b["holder"] for b in bgs if b["outcome"].startswith("retained") and b["holder"])
        best = defs.most_common(1)[0] if defs else (None, 0)
        post = [b for b in changes if b["season_type"] != "regular"]
        out.append({
            "season": s, "label": label(s), "entering": entering, "ending": ending,
            "games": len(bgs), "changes": len(changes), "postseason_changes": len(post),
            "holders": holders, "distinct_holders": len(set(holders)),
            "most_defenses": {"team": best[0], "defenses": best[1]},
            "first_n": bgs[0]["n"], "last_n": bgs[-1]["n"], "in_progress": s == all_seasons[-1] and any(
                g["season"] == s and g["date"] >= today for g in games),
        })
    return out


def rivalries(league, belt_games, min_meetings=2):
    pairs = {}
    for bg in belt_games:
        if not bg.get("holder"):
            continue
        a, b = sorted((bg["holder"], bg["opponent"]))
        p = pairs.setdefault(f"{a}|{b}", {"a": a, "b": b, "meetings": 0, "wins": Counter(), "ties": 0,
                                          "changes": 0, "first": bg["date"], "last": bg["date"], "games": []})
        p["meetings"] += 1
        p["last"] = bg["date"]
        p["games"].append(bg["n"])
        hp, ap = (int(x) for x in bg["score"].split("-"))
        if hp == ap:
            p["ties"] += 1
        else:
            winner = bg["home"] if hp > ap else bg["away"]
            p["wins"][winner] += 1
        if bg["outcome"] == "changed":
            p["changes"] += 1
    out = []
    for p in pairs.values():
        if p["meetings"] < min_meetings:
            continue
        p["a_wins"], p["b_wins"] = p["wins"].get(p["a"], 0), p["wins"].get(p["b"], 0)
        del p["wins"]
        out.append(p)
    out.sort(key=lambda p: -p["meetings"])
    return out


def preview(league, games, belt_games, reigns, next_game, today):
    if not next_game:
        return None
    h, c = next_game["holder"], next_game["challenger"]
    done = [g for g in games if g["date"] <= today]
    season = max(g["season"] for g in done) if done else None
    upcoming_season = next_game.get("season")

    def form(team, n=5):
        rows = [g for g in done if team in (g["home"], g["away"])][-n:]
        res = []
        for g in rows:
            r, mine, theirs = _result(g, team)
            opp = g["away"] if g["home"] == team else g["home"]
            res.append({"date": g["date"], "opp": opp, "opp_name": league["team_name"](opp, g["season"]),
                        "home": g["home"] == team, "result": r, "score": f"{mine}–{theirs}",
                        "note": g.get("note") or "", "postseason": g["season_type"] != "regular"})
        return list(reversed(res))

    def record(team, s):
        c_ = Counter(_result(g, team)[0] for g in done if g["season"] == s and team in (g["home"], g["away"]))
        return {"W": c_.get("W", 0), "L": c_.get("L", 0), "T": c_.get("T", 0)}

    h2h = [g for g in done if {g["home"], g["away"]} == {h, c}]
    hw = sum(1 for g in h2h if _result(g, h)[0] == "W")
    cw = sum(1 for g in h2h if _result(g, c)[0] == "W")
    ties = len(h2h) - hw - cw
    last = h2h[-1] if h2h else None
    belt_meet = [bg for bg in belt_games if bg.get("holder") and {bg["holder"], bg["opponent"]} == {h, c}]
    c_reigns = [r for r in reigns if r["team"] == c]
    h_reign = reigns[-1]
    rec_season = upcoming_season if any(g["season"] == upcoming_season for g in done) else season
    return {
        "holder": h, "challenger": c,
        "holder_form": form(h), "challenger_form": form(c),
        "record_season": rec_season,
        "holder_record": record(h, rec_season), "challenger_record": record(c, rec_season),
        "h2h": {"games": len(h2h), "holder_wins": hw, "challenger_wins": cw, "ties": ties,
                "first": h2h[0]["date"] if h2h else None,
                "last": ({"date": last["date"], "result": _result(last, h)[0],
                          "score": "{}–{}".format(*_result(last, h)[1:])} if last else None)},
        "belt_meetings": {"games": len(belt_meet),
                          "holder_side_wins": sum(1 for bg in belt_meet if bg["new_holder"] == bg["holder"] and not bg["outcome"].endswith("(tie)")),
                          "changes": sum(1 for bg in belt_meet if bg["outcome"] == "changed"),
                          "last": belt_meet[-1]["n"] if belt_meet else None},
        "meetings": [{"season": g["season"], "date": g["date"], "home": g["home"], "away": g["away"],
                      "hp": g["home_points"], "ap": g["away_points"], "note": g.get("note") or "",
                      "postseason": g["season_type"] != "regular", "neutral": bool(g.get("neutral"))}
                     for g in h2h[-10:]][::-1],
        "holder_reign_start": h_reign["start_date"],
        "challenger_days": sum(r["days"] for r in c_reigns),
        "challenger_defenses": sum(r.get("defenses", 0) for r in c_reigns),
        "challenger_reigns": len(c_reigns),
        "challenger_last_reign": ({"start": c_reigns[-1]["start_date"], "end": c_reigns[-1].get("end_date"),
                                   "index": c_reigns[-1]["index"]} if c_reigns else None),
        "holder_streak": h_reign.get("defenses", 0),
    }


def extra_records(league, belt_games, reigns, recent, today):
    changes = [bg for bg in belt_games if bg["outcome"] == "changed"]
    by_season = Counter(bg["season"] for bg in changes)
    last_held = {}
    for r in reigns:
        last_held[r["team"]] = r.get("end_date") or today
    droughts = sorted(((t, last_held[t], _days(last_held[t], today)) for t in recent if t in last_held),
                      key=lambda x: -x[2])
    never = sorted(t for t in recent if t not in last_held)
    takeovers = Counter((bg["new_holder"], bg["holder"]) for bg in changes)
    games_by_team = Counter()
    for bg in belt_games:
        if bg.get("holder"):
            games_by_team[bg["holder"]] += 1
            games_by_team[bg["opponent"]] += 1
    season_defs = Counter((bg["holder"], bg["season"]) for bg in belt_games
                          if bg.get("holder") and bg["outcome"].startswith("retained"))
    return {
        "busiest_seasons": by_season.most_common(10),
        "quietest_seasons": sorted(by_season.items(), key=lambda kv: (kv[1], kv[0]))[:10],
        "droughts": [{"team": t, "last": d, "days": n} for t, d, n in droughts[:10]],
        "never_held": never,
        "top_takeovers": [{"winner": w, "loser": l, "times": n} for (w, l), n in takeovers.most_common(10)],
        "biggest_margins": [{"n": bg["n"], "margin": bg["margin"]} for bg in
                            sorted(changes, key=lambda b: -b["margin"])[:10]],
        "most_belt_games": games_by_team.most_common(10),
        "most_defenses_season": [{"team": t, "season": s, "defenses": n} for (t, s), n in season_defs.most_common(10)],
        "ties": sum(1 for bg in belt_games if bg["outcome"].endswith("(tie)")),
    }
