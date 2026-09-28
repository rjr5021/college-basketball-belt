#!/usr/bin/env python3
"""One-off probe: does CBBD_API_KEY work, and how far back do games go?
Prints counts and field names only -- never the key."""
import json, os, sys, urllib.request, urllib.parse

KEY = os.environ.get("CBBD_API_KEY", "").strip()
if not KEY:
    sys.exit("CBBD_API_KEY is empty -- the secret isn't reaching the workflow.")
BASE = "https://api.collegebasketballdata.com"

def get(path, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

status, data = get("/games", season=2026, team="Duke")
print("key check /games?season=2026&team=Duke ->", status, (len(data) if isinstance(data, list) else data))
if status != 200:
    sys.exit(1)
g = data[0]
print("game fields:", sorted(g.keys()))
print("sample:", {k: g.get(k) for k in list(g.keys())[:14]})

for season in (2026, 2025, 2010, 2003, 2002, 1995, 1990, 1985, 1980, 1970, 1950):
    s, d = get("/games", season=season)
    if s == 200 and isinstance(d, list) and d:
        dates = sorted(x.get("startDate", "") for x in d if x.get("startDate"))
        scored = sum(1 for x in d if x.get("homePoints") is not None)
        print(f"season {season}: {len(d)} games, {scored} with scores, {dates[0][:10] if dates else '?'} .. {dates[-1][:10] if dates else '?'}")
    else:
        print(f"season {season}: status {s}, {d if not isinstance(d, list) else 'empty'}")
