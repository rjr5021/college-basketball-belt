"""
Load the women's game files (data/women/) into the belt engine's game schema,
the same interface cbb_data.py gives the men's belt.

  * data/women/hist.csv: the hand-built 1986-87 to 2002 belt line. It lists every
    game the holder played (all against Division I teams), not full schedules.
  * data/women/games/<season>.csv: ESPN results from 2002-03 on (fetch_women.py).

Which games count: both teams must be Division I that season -- a conference
label in ESPN's data, or 12+ games in the data that season. The hand-built rows
always count.
"""

import csv
import glob
import json
import os
from collections import Counter, defaultdict
from datetime import date

DATA = os.path.join("data", "women")
FIRST_SEASON = 1987          # first season in the data (1986-87)
FULL_FROM = 2003             # every team's games are in the data from 2002-03 on
MIN_GAMES = 12

# The belt starts with the reigning national champion going into 1986-87:
# Texas, 34-0, which beat USC 97-81 in the 1986 NCAA final (March 30, 1986).
SEED = {"team_name": "Texas", "opponent_name": "USC", "date": "1986-03-30",
        "score": "97-81", "note": "1986 NCAA final", "season": 1986,
        "short": "1986 NCAA champion", "long": "Won the 1986 NCAA final over USC, 97–81, to finish 34–0"}

DEFUNCT_COLORS = ("#5b5140", "#cfc4ad")

ROUND_NAMES = {0: "First Four", 1: "1st Round", 2: "2nd Round", 3: "Sweet 16", 4: "Elite 8",
               5: "Final Four", 6: "National Championship"}


def season_label(season):
    return f"{season - 1}–{str(season)[2:]}"


def _rows():
    paths = [os.path.join(DATA, "hist.csv")] + sorted(glob.glob(os.path.join(DATA, "games", "*.csv")))
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_hist"] = p.endswith("hist.csv")
                yield r


def _label_rounds(games):
    """ESPN's older NCAA tournament notes name the regional, not the round. Work the
    round out from the bracket itself: a team's nth tournament game is round n
    (First Four games aside)."""
    by_season = defaultdict(list)
    for g in games:
        if g["tournament"] == "NCAA" and not g.get("_hist"):
            by_season[g["season"]].append(g)
    for s, gs in by_season.items():
        gs.sort(key=lambda g: (g["date"], g["id"]))
        played = Counter()
        for g in gs:
            if "first four" in (g["notes"] or "").lower() or "opening round" in (g["notes"] or "").lower():
                g["notes"] = "First Four"
                continue
            n = max(played[g["home"]], played[g["away"]]) + 1
            played[g["home"]] += 1
            played[g["away"]] += 1
            g["notes"] = ROUND_NAMES.get(min(n, 6), "NCAA tournament")


def load(today=None):
    today = today or date.today().isoformat()
    rows = list(_rows())
    per, conf, names, hist_teams = defaultdict(Counter), defaultdict(set), {}, defaultdict(set)
    for r in rows:
        s = int(r["season"])
        for side in ("home", "away"):
            tid = r[side + "_id"]
            if r[side]:
                names[tid] = r[side]
            if r["_hist"]:
                hist_teams[s].add(tid)
            if r["status"] == "final":
                per[s][tid] += 1
            if r[side + "_conf"]:
                conf[s].add(tid)
    seasons = set(per) | set(conf) | set(hist_teams)
    elig = {s: conf[s] | hist_teams[s] | {t for t, n in per[s].items() if n >= MIN_GAMES} for s in seasons}

    games, upcoming = [], []
    for r in rows:
        s = int(r["season"])
        h, a = r["home_id"], r["away_id"]
        if h not in elig.get(s, ()) or a not in elig.get(s, ()):
            continue
        base = {"id": int(r["id"]), "date": r["date"], "season": s, "week": None,
                "season_type": r["season_type"] or "regular", "home": h, "away": a,
                "neutral": r["neutral"] == "1", "tournament": r["tournament"], "notes": r["notes"],
                "venue": r["venue"], "city": r["city"], "state": r["state"],
                "home_conf": r.get("home_conf") or "", "away_conf": r.get("away_conf") or "", "_hist": r["_hist"]}
        if r["status"] == "final" and r["home_points"] != "":
            games.append({**base, "home_points": int(float(r["home_points"])), "away_points": int(float(r["away_points"]))})
        elif r["status"] == "scheduled" and r["date"] >= today:
            upcoming.append({**base, "kickoff": (r["start_et"] if r["start_et"] and r["start_et"] != "00:00" else None)})
    _label_rounds(games)
    games.sort(key=lambda g: (g["date"], g["season_type"] != "regular", g["id"]))
    upcoming.sort(key=lambda g: (g["date"], g.get("kickoff") or "", g["id"]))

    teams = {}
    tpath = os.path.join(DATA, "teams.json")
    if os.path.exists(tpath):
        with open(tpath, encoding="utf-8") as f:
            for t in json.load(f):
                teams[str(t["id"])] = t
    return games, upcoming, names, teams, elig


def colors(teams, tid):
    t = teams.get(str(tid)) or {}
    p, s = t.get("primaryColor"), t.get("secondaryColor")
    if not p:
        return DEFUNCT_COLORS
    p = "#" + p.lstrip("#").lower()
    s = ("#" + s.lstrip("#").lower()) if s else None
    return p, s


def nickname(teams, tid, fallback):
    t = teams.get(str(tid)) or {}
    return t.get("mascot") or fallback


ROUNDS = [
    ("First Four", "First Four", 0), ("Opening Round", "First Four", 0),
    ("1st Round", "First round", 1), ("First Round", "First round", 1),
    ("2nd Round", "Second round", 2), ("Second Round", "Second round", 2),
    ("Sweet 16", "Sweet 16", 3), ("Regional Semifinal", "Sweet 16", 3),
    ("Elite 8", "Elite Eight", 4), ("Elite Eight", "Elite Eight", 4), ("Regional Final", "Elite Eight", 4),
    ("Final Four", "Final Four", 5), ("National Semifinal", "Final Four", 5),
    ("National Championship", "Title game", 6), ("National Final", "Title game", 6),
]


def ncaa_round(notes):
    for key, label, order in ROUNDS:
        if key.lower() in (notes or "").lower():
            return label, order
    return "NCAA tournament", 0
