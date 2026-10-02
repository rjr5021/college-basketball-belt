#!/usr/bin/env python3
"""
Everything the next-belt-game preview needs that isn't in the game files,
fetched once per workflow run (after build_lineage[s].py) and written to
preview_extra.json next to each belt's lineage.json:

  * ESPN's scoreboard entry for the game: start time (UTC), TV, venue and
    whether it's indoors, the betting line, team logos, records, rankings.
    One call per belt.
  * Kickoff weather for outdoor games within 15 days (Open-Meteo: free, no
    key). Two calls, only for the NFL and MLB belts.
  * A short AI-written preview with a pick ("the lean") from the Claude API,
    the same idea as the College Football Belt's. One call per NEW game: the
    result is kept in preview_extra.json (committed by the workflow) and
    reused until the holder's next game changes, so reruns cost nothing.
    Skips itself cleanly when ANTHROPIC_API_KEY isn't set.
  * The lean's ledger (lean_ledger.json): every pick ever made, never
    revised, so the site can grade it.

Shared file: Belt Holders (four belts, data/<lg>/) and the College
Basketball Belt (one belt, data/) run the same copy. Never fails the build.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

ESPN = {"nfl": "football/nfl", "nba": "basketball/nba", "nhl": "hockey/nhl", "mlb": "baseball/mlb",
        "cbb": "basketball/mens-college-basketball", "wnba": "basketball/wnba", "mls": "soccer/usa.1",
        "nwsl": "soccer/usa.nwsl", "epl": "soccer/eng.1", "laliga": "soccer/esp.1", "seriea": "soccer/ita.1",
        "bundesliga": "soccer/ger.1", "ligue1": "soccer/fra.1", "eredivisie": "soccer/ned.1",
        "wcbb": "basketball/womens-college-basketball", "women": "basketball/womens-college-basketball",
        "intl": "soccer/fifa.friendly", "cfl": "football/cfl"}
OUTDOOR_SPORTS = ("nfl", "mlb", "mls", "nwsl", "epl", "laliga", "seriea", "bundesliga", "ligue1", "eredivisie", "intl", "cfl")
MODEL = "claude-sonnet-4-5"   # accurate with numbers; ~1-2 cents per preview
MAX_TOKENS = 900
SITE_BLURB = {
    "cbb": ("The College Basketball Belt", "a lineal championship belt that has passed from team to team on the court "
            "since the 1949 NCAA champion, Kentucky: beat the holder and it's yours"),
    "women": ("The Women's College Basketball Belt", "a lineal championship belt that has passed from team to team on the court "
              "since the 1986 NCAA champion, Texas: beat the holder and it's yours"),
}
DEFAULT_BLURB = ("Belt Holders", "a lineal championship belt for every pro league: the belt passes to whoever beats "
                 "the holder, game by game, going all the way back to the league's first game")

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "ON": "Ontario", "QC": "Quebec",
          "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba"}
WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog", 51: "Light drizzle",
       53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain",
       63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow",
       75: "Heavy snow", 77: "Snow grains", 80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
       85: "Snow showers", 86: "Snow showers", 95: "Thunderstorms", 96: "Thunderstorms", 99: "Thunderstorms"}


def log(*a):
    print(*a, flush=True)


def get_json(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                log(f"  fetch failed: {url} ({e})")
                return None
            time.sleep(2 * (i + 1))


def load(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


# ------------------------------------------------------------- targets --

def targets():
    """(league dict, lineage path, output dir) for every belt in this repo."""
    try:
        from leagues import LIVE
        return [(lg, os.path.join("data", lg["key"], "lineage.json"), os.path.join("data", lg["key"])) for lg in LIVE]
    except ImportError:
        import cbb_league
        out = [(cbb_league.LEAGUE, os.path.join("data", "lineage.json"), "data")]
        w = getattr(cbb_league, "WOMEN", None)
        if w and os.path.exists(os.path.join("data", "women", "lineage.json")):
            out.append((w, os.path.join("data", "women", "lineage.json"), os.path.join("data", "women")))
        return out


def game_key(ng):
    return f"{ng['holder']}|{ng['challenger']}|{ng['date']}"


def start_utc_from_et(ng):
    ko = ng.get("kickoff")
    if not ko or not ZoneInfo:
        return None
    try:
        local = datetime.fromisoformat(f"{ng['date']}T{ko}").replace(tzinfo=ZoneInfo("America/New_York"))
        return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    except ValueError:
        return None


# ---------------------------------------------------------------- ESPN --

def norm(s):
    s = (s or "").lower().replace("&", "and").replace("é", "e")
    s = re.sub(r"\bst\.?\b", "st", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def names_for(lg, code):
    full, short = lg["team_name"](code), lg["short_name"](code)
    return {norm(full), norm(short)}


def team_matches(team, wanted):
    cands = {norm(team.get(k)) for k in ("displayName", "shortDisplayName", "name", "location", "nickname")}
    cands.add(norm(f"{team.get('location', '')} {team.get('name', '')}"))
    return bool(cands & wanted)


def espn_game(lg, ng):
    path = ESPN.get(lg.get("key", "cbb"))
    if not path:
        return None
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={ng['date'].replace('-', '')}"
    if lg.get("key") in ("cbb", "wcbb", "women"):
        url += "&groups=50&limit=500"
    j = get_json(url)
    if not j:
        return None
    hw, cw = names_for(lg, ng["holder"]), names_for(lg, ng["challenger"])
    best = None
    for ev in j.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        teams = [c.get("team") or {} for c in comp.get("competitors", [])]
        h = any(team_matches(t, hw) for t in teams)
        c = any(team_matches(t, cw) for t in teams)
        if h and c:
            best = ev
            break
        if h and not best:
            best = ev
    if not best:
        log(f"  [{lg.get('key')}] no ESPN event matched {ng['holder']} vs {ng['challenger']} on {ng['date']}")
        return None
    comp = (best.get("competitions") or [{}])[0]
    v = comp.get("venue") or {}
    addr = v.get("address") or {}
    tv = []
    for b in comp.get("broadcasts") or []:
        for n in b.get("names") or []:
            if n and n not in tv:
                tv.append(n)
    for b in comp.get("geoBroadcasts") or []:
        n = ((b.get("media") or {}).get("shortName"))
        if n and n not in tv and (b.get("market") or {}).get("type", "National") == "National":
            tv.append(n)
    odds = None
    for o in comp.get("odds") or []:
        if o.get("details") or o.get("overUnder"):
            odds = {"details": o.get("details"), "over_under": o.get("overUnder"),
                    "provider": (o.get("provider") or {}).get("name")}
            break
    teams = {}
    for c in comp.get("competitors", []):
        t = c.get("team") or {}
        code = ng["holder"] if team_matches(t, hw) else ng["challenger"] if team_matches(t, cw) else None
        if not code:
            continue
        rank = (c.get("curatedRank") or {}).get("current")
        rec = next((r.get("summary") for r in (c.get("records") or []) if r.get("summary")), None)
        teams[str(code)] = {"logo": t.get("logo") or ((t.get("logos") or [{}])[0].get("href")),
                            "abbr": t.get("abbreviation"), "record": rec,
                            "rank": rank if isinstance(rank, int) and 0 < rank <= 25 else None,
                            "home_away": c.get("homeAway")}
    st = ((best.get("status") or {}).get("type") or {})
    return {"event_id": best.get("id"), "start_utc": best.get("date"), "state": st.get("state"),
            "tv": tv[:3], "odds": odds, "teams": teams,
            "venue": {"name": v.get("fullName"), "city": addr.get("city"), "state": addr.get("state"),
                      "indoor": v.get("indoor")}}


# ------------------------------------------------------------- weather --

def weather(lg, ng, espn):
    if lg.get("key") not in OUTDOOR_SPORTS or not espn:
        return None
    venue = dict(espn.get("venue") or {})
    if not venue.get("city") and not ng.get("neutral"):      # B-7: the home club's ground (European leagues)
        hv = (lg.get("home_venues") or {}).get(ng["holder"] if ng["holder_home"] else ng["challenger"])
        if hv:
            venue.update({"name": venue.get("name") or hv[0], "city": hv[1], "indoor": False})
    if venue.get("indoor") is not False or not venue.get("city"):
        return None
    start = espn.get("start_utc")
    if not start:
        return None
    when = datetime.strptime(start[:16].replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    if when - datetime.now(timezone.utc) > timedelta(days=15) or when < datetime.now(timezone.utc) - timedelta(hours=6):
        return None
    geo = get_json("https://geocoding-api.open-meteo.com/v1/search?"
                   + urllib.parse.urlencode({"name": venue["city"], "count": 10, "language": "en", "format": "json"}))
    want = STATES.get((venue.get("state") or "").upper(), venue.get("state") or "")
    place = None
    euro = lg.get("key") in ("epl", "laliga", "seriea", "bundesliga", "ligue1", "eredivisie", "intl")
    for r in (geo or {}).get("results") or []:
        # B-7: European leagues and national teams play anywhere; the North American leagues keep the country filter
        if (euro or r.get("country_code") in ("US", "CA", "MX", "GB", "DE")) and (not want or r.get("admin1") == want):
            place = r
            break
    if not place:
        return None
    day = when.strftime("%Y-%m-%d")
    f = get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": place["latitude"], "longitude": place["longitude"],
        "hourly": "temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC",
        "start_date": day, "end_date": day}))
    hrs = ((f or {}).get("hourly") or {})
    times = hrs.get("time") or []
    key = when.strftime("%Y-%m-%dT%H:00")
    if key not in times:
        return None
    i = times.index(key)

    def at(k):
        v = (hrs.get(k) or [None] * len(times))[i]
        return round(v) if isinstance(v, (int, float)) else None

    return {"temp_f": at("temperature_2m"), "feels_like_f": at("apparent_temperature"),
            "precip_chance": at("precipitation_probability"), "wind_mph": at("wind_speed_10m"),
            "condition": WMO.get(at("weather_code")), "as_of": date.today().isoformat(),
            "venue": venue.get("name")}


# ------------------------------------------------------------- the lean --

def form_line(name, rows):
    if not rows:
        return f"{name}: no recent completed games on record."
    bits = [f"{r['result']} {r['score']} {'vs' if r['home'] else 'at'} {r['opp_name']}" + (" (playoffs)" if r.get("postseason") else "")
            for r in rows]
    return f"{name} last {len(rows)} (newest first): " + "; ".join(bits)


def build_prompt(lg, d, ng, espn, wx):
    n = lg["team_name"]
    pv = d.get("preview") or {}
    h, c = n(ng["holder"]), n(ng["challenger"])
    site, blurb = SITE_BLURB.get(lg.get("key"), DEFAULT_BLURB)
    side = "faces (neutral site)" if ng.get("neutral") else ("hosts" if ng["holder_home"] else "travels to")
    h2h = pv.get("h2h") or {}
    lines = [form_line(h, pv.get("holder_form")), form_line(c, pv.get("challenger_form"))]
    for nm, rows in ((h, pv.get("holder_form")), (c, pv.get("challenger_form"))):
        if rows:
            streak, first = 0, rows[0]["result"]
            for r in rows:
                if r["result"] != first:
                    break
                streak += 1
            word = {"W": "won", "L": "lost", "T": "tied"}[first]
            lines.append(f"{nm} have {word} their last {streak} game{'s' if streak > 1 else ''} (most recent: {first} {rows[0]['score']} "
                         f"{'vs' if rows[0]['home'] else 'at'} {rows[0]['opp_name']}).")
    rec = lambda r: f"{r['W']}-{r['L']}" + (f"-{r['T']}" if r.get("T") else "")
    if pv.get("holder_record"):
        lines.append(f"Records this season: {h} {rec(pv['holder_record'])}, {c} {rec(pv['challenger_record'])}.")
    if h2h.get("games"):
        lines.append(f"All-time head to head: {h} {h2h['holder_wins']}, {c} {h2h['challenger_wins']}"
                     + (f", {h2h['ties']} ties" if h2h.get("ties") else "") + f" ({h2h['games']} games).")
        mts = pv.get("meetings") or []
        if mts:
            lines.append("Last meetings: " + "; ".join(
                f"{m['date']}: {n(m['home'])} {m['hp']}-{m['ap']} {n(m['away'])}" for m in mts[:5]) + ".")
    bm = pv.get("belt_meetings") or {}
    lines.append(f"They have met {bm.get('games', 0)} times with the belt on the line." if bm.get("games")
                 else "They have never met with the belt on the line.")
    lines.append(f"{h} have defended the belt {pv.get('holder_streak', 0)} times in this reign.")
    lines.append(f"{c} have held the belt {pv.get('challenger_reigns', 0)} times before." if pv.get("challenger_reigns")
                 else f"{c} have never held the belt.")
    if pv.get("holder_win_prob") is not None:
        # N-3: words, not the percentage -- the number moves between runs while the cached text doesn't
        wp = pv["holder_win_prob"]
        edge = ("a clear favorite" if wp >= 0.65 else "the favorite" if wp >= 0.55 else "in a toss-up" if wp >= 0.45
                else "the underdog" if wp >= 0.35 else "a clear underdog")
        lines.append(f"Our Elo model makes {h} {edge} in this game.")
    # N-3: no betting line and no forecast in the prompt -- both are shown live on the page and change
    # every run, and the cached text used to contradict them.
    stats = "\n".join(lines)
    return f'''You are writing a short preview for "{site}," a site that tracks {blurb}. No committee or poll is involved. The belt is on the line in this {lg['name']} game.

Upcoming game: {h} (current belt holder) {side} {c} on {ng['date']}.

Stats (this is everything you know -- do NOT invent player names, injuries, coaches, trades or any fact not listed here; every claim you make about form, streaks, margins or history must be checkable against these lines, so re-read them before writing. Every number you write must appear verbatim in these lines: do not add up goals or points across games, do not count streaks or margins yourself, and never mention betting lines, odds, over/unders or the weather -- those are shown separately on the page):
{stats}

Write a JSON object with exactly these keys and nothing else:
  "overview": 2-3 sentences on the game and what's at stake for the belt. Plain prose, no markdown.
  "key_matchups": a list of 2-3 short strings, each a storyline worth watching that follows from the stats above.
  "betting_angles": 2-3 sentences on what the numbers suggest (form, head to head, the Elo edge). Analysis only -- never tell the reader what to bet, and no odds or lines.
  "predicted_winner": exactly "{h}" or "{c}", nothing else.
  "predicted_score": your predicted final score as "{h} X, {c} Y" with realistic {lg['name']} numbers.
  "prediction_writeup": 3-5 sentences explaining the pick from the stats above. Plain prose. A for-fun editorial call, not betting advice.

Output ONLY the JSON object, no other text, no markdown code fence.'''


def call_claude(prompt, api_key, retries=4):
    body = json.dumps({"model": MODEL, "max_tokens": MAX_TOKENS,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    delay = 3
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read().decode())
            return "".join(b.get("text", "") for b in resp.get("content", []))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 529) and attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise


def parse(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        j = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            j = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return {"overview": (j.get("overview") or "").strip(),
            "key_matchups": [str(x).strip() for x in (j.get("key_matchups") or []) if str(x).strip()][:3],
            "betting_angles": (j.get("betting_angles") or "").strip(),
            "predicted_winner": (j.get("predicted_winner") or "").strip(),
            "predicted_score": (j.get("predicted_score") or "").strip(),
            "prediction_writeup": (j.get("prediction_writeup") or "").strip()}


# ------------------------------------------------------- fact check (N-3) --
# The model only knows the stats in the prompt, but it still invented totals, streak lengths and
# margins ("three blowouts by 40+"), and it used to quote odds and forecasts that the page refreshes
# every run while the cached text didn't. Now: every number in the output must appear verbatim in
# the prompt (plus 0-10 and the two-digit forms of years, for "2025-26"); a first miss gets one
# rewrite with the offending numbers named; a second miss drops the sentences that carry them.

_NUM_RX = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])")


def _nums(text):
    return {m.group(0).replace(",", "") for m in _NUM_RX.finditer(text or "")}


def allowed_numbers(prompt):
    nums = _nums(prompt)
    out = set(nums) | {str(i) for i in range(0, 11)}
    for n in nums:
        if re.fullmatch(r"(19|20)\d\d", n):
            out.add(n[2:])
    return out


_AI_TEXT_KEYS = ("overview", "betting_angles", "prediction_writeup")


def unknown_numbers(ai, allowed):
    found = set()
    for k in _AI_TEXT_KEYS:
        found |= _nums(ai.get(k)) - allowed
    for item in ai.get("key_matchups") or []:
        found |= _nums(item) - allowed
    return found


def scrub_numbers(ai, allowed):
    """Drop every sentence or bullet that still quotes a number the stats don't contain."""
    dropped = set()

    def keep_sentences(text):
        kept = []
        for sent in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
            unk = _nums(sent) - allowed
            if unk:
                dropped.update(unk)
            elif sent:
                kept.append(sent)
        return " ".join(kept)

    out = dict(ai)
    for k in _AI_TEXT_KEYS:
        out[k] = keep_sentences(ai.get(k))
    out["key_matchups"] = [x for x in (ai.get("key_matchups") or []) if not (_nums(x) - allowed)]
    return out, dropped


def retry_prompt(prompt, unknown):
    return (prompt + "\n\nYour previous draft cited numbers that do not appear in the stats above: "
            + ", ".join(sorted(unknown, key=lambda x: (len(x), x)))
            + ". Rewrite it using only numbers that appear verbatim in the stats. Do not add up points or goals across games, "
              "do not count streaks or margins yourself, and do not quote odds, lines or forecasts.")


def record_pick(ledger_path, key, lg, ng, ai, espn):
    ledger = load(ledger_path, [])
    if any(x.get("key") == key for x in ledger) or not ai.get("predicted_winner"):
        return
    n = lg["team_name"]
    winner = ng["holder"] if ai["predicted_winner"] == n(ng["holder"]) else ng["challenger"] if ai["predicted_winner"] == n(ng["challenger"]) else None
    ledger.append({"key": key, "date": ng["date"], "holder": ng["holder"], "challenger": ng["challenger"],
                   "pick": winner, "score": ai.get("predicted_score"), "made": date.today().isoformat(),
                   "line": (espn or {}).get("odds")})
    save(ledger_path, ledger)


# ----------------------------------------------------------------- main --

def enrich(lg, lineage_path, out_dir, api_key):
    k = lg.get("key", "cbb")
    d = load(lineage_path)
    out_path = os.path.join(out_dir, "preview_extra.json")
    ng = (d or {}).get("next_game")
    if not ng:
        save(out_path, {"key": None})
        log(f"[{k}] no next game")
        return
    key = game_key(ng)
    old = load(out_path, {}) or {}
    same = old.get("key") == key
    espn = espn_game(lg, ng) or (old.get("espn") if same else None)
    wx = weather(lg, ng, espn) or (old.get("weather") if same else None)
    start = (espn or {}).get("start_utc") or start_utc_from_et(ng)
    ai = old.get("ai") if same else None
    if ai and ai.get("model") != MODEL:
        ai = None   # rewrite once with the current model (the ledger keeps the first pick)
    if not ai and api_key:
        try:
            log(f"[{k}] writing the AI preview for {key} ({MODEL})")
            prompt = build_prompt(lg, d, ng, espn, wx)
            allowed = allowed_numbers(prompt)
            ai = parse(call_claude(prompt, api_key))
            attempts, dropped = 1, set()
            if ai:
                unk = unknown_numbers(ai, allowed)
                if unk:
                    log(f"[{k}] fact check: {sorted(unk)} not in the stats; rewriting once")
                    again = parse(call_claude(retry_prompt(prompt, unk), api_key))
                    attempts = 2
                    if again:
                        ai = again
                    unk = unknown_numbers(ai, allowed)
                    if unk:
                        ai, dropped = scrub_numbers(ai, allowed)
                        log(f"[{k}] fact check: dropped sentences citing {sorted(dropped)}")
                if not (ai.get("overview") and ai.get("prediction_writeup")):
                    log(f"[{k}] fact check left too little text; the page builds without the AI preview")
                    ai = None
            if ai:
                ai["written"] = date.today().isoformat()
                ai["model"] = MODEL
                ai["factcheck"] = {"attempts": attempts, "dropped": sorted(dropped)}
        except Exception as e:  # noqa: BLE001
            log(f"[{k}] AI preview failed ({e}); the page builds without it")
            ai = None
    elif not ai:
        log(f"[{k}] no ANTHROPIC_API_KEY; skipping the AI preview")
    if ai:
        record_pick(os.path.join(out_dir, "lean_ledger.json"), key, lg, ng, ai, espn)
    save(out_path, {"key": key, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                    "start_utc": start, "espn": espn, "weather": wx, "ai": ai})
    log(f"[{k}] {key}: espn={'yes' if espn else 'no'} weather={'yes' if wx else 'no'} ai={'yes' if ai else 'no'}")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or None
    for lg, lp, od in targets():
        try:
            enrich(lg, lp, od, api_key)
        except Exception as e:  # noqa: BLE001
            log(f"[{lg.get('key')}] enrich failed: {e}")
        try:
            import recaps
            recaps.run(lg, load(lp) or {}, od, api_key)
        except Exception as e:  # noqa: BLE001
            log(f"[{lg.get('key')}] recaps failed: {e}")


if __name__ == "__main__":
    main()
