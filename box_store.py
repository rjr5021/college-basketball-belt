"""Belt-game box scores stored one file per season (data/<lg>/box/<season>.json)
so each update only rewrites the seasons that changed."""
import glob
import json
import os


def load_all(league):
    games = {}
    for p in glob.glob(os.path.join("data", league, "box", "*.json")):
        name = os.path.basename(p)
        if not (name[:4].isdigit() or name == "belt_box.json"):
            continue
        with open(p) as f:
            games.update((json.load(f) or {}).get("games") or {})
    return games


def save_all(league, games, season_of, meta):
    """games: {n: {...}}; season_of: {n: season}. Writes only shards whose content changed."""
    by = {}
    for n, g in games.items():
        s = season_of.get(str(n))
        if s is None:
            continue
        by.setdefault(s, {})[str(n)] = g
    folder = os.path.join("data", league, "box")
    os.makedirs(folder, exist_ok=True)
    for s, gs in by.items():
        p = os.path.join(folder, f"{s}.json")
        body = json.dumps({**meta, "games": dict(sorted(gs.items(), key=lambda kv: int(kv[0])))}, separators=(",", ":"))
        if os.path.exists(p):
            with open(p) as f:
                if f.read() == body:
                    continue
        with open(p, "w") as f:
            f.write(body)
    old = os.path.join(folder, "belt_box.json")
    if os.path.exists(old):
        os.remove(old)
