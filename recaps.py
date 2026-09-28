"""
AI recaps for belt games, going forward (not the back catalog): after each
belt game, find it on ESPN's scoreboard, pull the box-score leaders and the
line score from ESPN's game summary, and have Claude write a short recap
from those numbers only. Each game is written once; results live in
recaps.json next to lineage.json (committed by the workflow).

Called from enrich_preview.py. Shared by Belt Holders and the College
Basketball Belt. Never fails the build.
"""

import json
import os
from datetime import date

import enrich_preview as EP

RECAP_FROM = "2026-09-20"   # recaps start with belt games on or after this date
MAX_PER_RUN = 6             # safety valve per belt per run


def _leaders(summary, lg, codes_by_side):
    out = []
    for block in summary.get("leaders") or []:
        team = (block.get("team") or {})
        side = None
        for code, names in codes_by_side.items():
            if EP.team_matches(team, names):
                side = code
        for cat in block.get("leaders") or []:
            for l in (cat.get("leaders") or [])[:1]:
                ath = (l.get("athlete") or {}).get("displayName")
                val = l.get("displayValue")
                if ath and val:
                    out.append({"team": side, "category": cat.get("displayName") or cat.get("name"), "player": ath, "line": val})
    return out[:10]


def _linescore(comp):
    rows = []
    for c in comp.get("competitors") or []:
        ls = [x.get("displayValue") or str(x.get("value", "")) for x in c.get("linescores") or []]
        rows.append({"team": (c.get("team") or {}).get("displayName"), "home_away": c.get("homeAway"),
                     "periods": ls, "score": c.get("score")})
    return rows


def _scoring(summary, limit=14):
    plays = []
    for p in summary.get("scoringPlays") or []:
        txt = p.get("text")
        if txt:
            per = (p.get("period") or {}).get("number")
            clock = (p.get("clock") or {}).get("displayValue")
            plays.append(f"P{per} {clock}: {txt}")
    return plays[:limit]


def fetch_box(lg, bg):
    """ESPN summary numbers for a finished belt game, or None."""
    path = EP.ESPN.get(lg.get("key", "cbb"))
    if not path:
        return None
    ng = {"date": bg["date"], "holder": bg["holder"], "challenger": bg["opponent"]}
    ev = EP.espn_game(lg, ng)
    if not ev or not ev.get("event_id"):
        return None
    s = EP.get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={ev['event_id']}")
    if not s:
        return None
    comp = ((s.get("header") or {}).get("competitions") or [{}])[0]
    sides = {bg["holder"]: EP.names_for(lg, bg["holder"]), bg["opponent"]: EP.names_for(lg, bg["opponent"])}
    return {"event_id": ev["event_id"], "venue": (ev.get("venue") or {}).get("name"),
            "leaders": _leaders(s, lg, sides), "linescore": _linescore(comp), "scoring": _scoring(s),
            "attendance": (s.get("gameInfo") or {}).get("attendance")}


def prompt(lg, bg, box):
    n = lg["team_name"]
    h, o = n(bg["holder"]), n(bg["opponent"])
    hp, ap = (int(x) for x in bg["score"].split("-"))
    home = n(bg["home"])
    outcome = (f"{o} beat {h} and TOOK the belt." if bg["outcome"] == "changed"
               else f"{h} and {o} tied, so {h} KEPT the belt." if bg["outcome"].endswith("(tie)")
               else f"{h} beat {o} and KEPT the belt.")
    away_code = bg["opponent"] if bg["home"] == bg["holder"] else bg["holder"]
    lines = [f"Final: {n(away_code)} {ap} at {home} {hp}" + (" (neutral site)" if bg.get("neutral") else ""),
             f"Belt result: {outcome}"]
    if bg.get("note"):
        lines.append(f"Decided in: {bg['note']}")
    if box:
        for r in box.get("linescore") or []:
            if r.get("periods"):
                lines.append(f"Line score {r['team']}: {' '.join(r['periods'])} = {r['score']}")
        for l in box.get("leaders") or []:
            lines.append(f"Leader ({n(l['team']) if l.get('team') else '?'}, {l['category']}): {l['player']} {l['line']}")
        if box.get("scoring"):
            lines.append("Scoring plays: " + " | ".join(box["scoring"]))
        if box.get("venue"):
            lines.append(f"Venue: {box['venue']}")
    site, blurb = EP.SITE_BLURB.get(lg.get("key"), EP.DEFAULT_BLURB)
    return f'''You are writing a short game recap for "{site}," which tracks {blurb}. This {lg['name']} game had the belt on the line.

Facts (this is everything you know: use ONLY these; do not invent quotes, injuries, records, streaks, or any player or stat not listed):
{chr(10).join(lines)}

Write a JSON object with exactly these keys:
  "headline": a punchy headline under 12 words that says who won and what happened to the belt.
  "recap": 2-3 short paragraphs (as a list of strings) telling how the game went and what it means for the belt, grounded in the facts above. Plain prose, no markdown.

Output ONLY the JSON object.'''


def run(lg, d, out_dir, api_key):
    k = lg.get("key", "cbb")
    path = os.path.join(out_dir, "recaps.json")
    recaps = EP.load(path, {}) or {}
    todo = [bg for bg in d.get("belt_games", []) if bg.get("holder") and bg["date"] >= RECAP_FROM
            and f"{bg['holder']}|{bg['opponent']}|{bg['date']}" not in recaps]
    if not todo:
        return
    if not api_key:
        EP.log(f"[{k}] {len(todo)} belt games need recaps, but there's no ANTHROPIC_API_KEY")
        return
    done = 0
    for bg in todo[:MAX_PER_RUN]:
        key = f"{bg['holder']}|{bg['opponent']}|{bg['date']}"
        box = fetch_box(lg, bg)
        try:
            raw = EP.call_claude(prompt(lg, bg, box), api_key)
        except Exception as e:  # noqa: BLE001
            EP.log(f"[{k}] recap failed for {key}: {e}")
            continue
        try:
            t = raw.strip().strip("`")
            if t.lower().startswith("json"):
                t = t[4:]
            j = json.loads(t[t.index("{"): t.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            j = None
        if not j or not j.get("recap"):
            continue
        body = j["recap"] if isinstance(j["recap"], list) else [str(j["recap"])]
        recaps[key] = {"date": bg["date"], "holder": bg["holder"], "opponent": bg["opponent"], "outcome": bg["outcome"],
                       "headline": (j.get("headline") or "").strip(), "recap": [p.strip() for p in body if str(p).strip()],
                       "leaders": (box or {}).get("leaders") or [], "linescore": (box or {}).get("linescore") or [],
                       "written": date.today().isoformat(), "model": EP.MODEL}
        done += 1
    EP.save(path, recaps)
    EP.log(f"[{k}] wrote {done} recap(s); {len(recaps)} on file")
