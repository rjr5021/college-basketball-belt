"""
Load the committed CollegeBasketballData files (data/games/*.csv,
data/teams.json) into the belt engine's game schema.

Which games count: both teams must be Division I that season. The API
labels every Division I team with its conference (independents included)
in the modern data; early seasons have gaps in those labels but contain
only major-college schedules, so a team also counts if it played 12 or more
games in the data that season. Non-Division I opponents (who appear for a
game or two a year) never count, so a holder can't lose the belt to them.
"""

import csv
import glob
import json
import os
from collections import Counter, defaultdict
from datetime import date

DATA = "data"
FIRST_SEASON = 1950          # first full season in the data (1949-50)
MIN_GAMES = 12

# The game-by-game record starts with 1949-50, so the belt starts with the
# reigning national champion: Kentucky, 46-36 over Oklahoma A&M in the 1949
# NCAA final (March 26, 1949).
SEED = {"team_name": "Kentucky", "opponent_name": "Oklahoma State", "date": "1949-03-26",
        "score": "46-36", "note": "1949 NCAA final"}

DEFUNCT_COLORS = ("#5b5140", "#cfc4ad")


def season_label(season):
    """API season 1950 -> '1949–50'."""
    return f"{season - 1}–{str(season)[2:]}"


def _rows():
    for p in sorted(glob.glob(os.path.join(DATA, "games", "*.csv"))):
        with open(p, newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f)


def load(today=None):
    today = today or date.today().isoformat()
    rows = list(_rows())
    per, conf, names = defaultdict(Counter), defaultdict(set), {}
    for r in rows:
        s = int(r["season"])
        for side in ("home", "away"):
            tid = r[side + "_id"]
            names[tid] = r[side]
            if r["status"] == "final":
                per[s][tid] += 1
            if r[side + "_conf"]:
                conf[s].add(tid)
    elig = {s: conf[s] | {t for t, n in per[s].items() if n >= MIN_GAMES} for s in set(per) | set(conf)}

    games, upcoming = [], []
    for r in rows:
        s = int(r["season"])
        if s < FIRST_SEASON:
            continue
        h, a = r["home_id"], r["away_id"]
        if h not in elig.get(s, ()) or a not in elig.get(s, ()):
            continue
        base = {"id": int(r["id"]), "date": r["date"], "season": s, "week": None,
                "season_type": r["season_type"] or "regular", "home": h, "away": a,
                "neutral": r["neutral"] == "1", "tournament": r["tournament"], "notes": r["notes"],
                "venue": r["venue"], "city": r["city"], "state": r["state"]}
        if r["status"] == "final" and r["home_points"] != "":
            games.append({**base, "home_points": int(r["home_points"]), "away_points": int(r["away_points"])})
        elif r["status"] == "scheduled" and r["date"] >= today:
            upcoming.append({**base, "kickoff": r["start_et"] or None})
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


ROUNDS = [  # (substring in the API's game notes, label, order)
    ("First Four", "First Four", 0), ("Opening Round", "First Four", 0),
    ("1st Round", "First round", 1), ("First Round", "First round", 1),
    ("2nd Round", "Second round", 2), ("Second Round", "Second round", 2),
    ("Sweet 16", "Sweet 16", 3), ("Regional Semifinal", "Sweet 16", 3),
    ("Elite 8", "Elite Eight", 4), ("Elite Eight", "Elite Eight", 4), ("Regional Final", "Elite Eight", 4),
    ("Final Four", "Final Four", 5), ("National Semifinal", "Final Four", 5),
    ("National Championship", "Title game", 6), ("National Final", "Title game", 6),
    ("Third Place", "Third-place game", 5),
]


def ncaa_round(notes):
    for key, label, order in ROUNDS:
        if key.lower() in (notes or "").lower():
            return label, order
    return "NCAA tournament", 0
