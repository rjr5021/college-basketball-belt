#!/usr/bin/env python3
"""
Instagram posts for the belt network's accounts (2026-10-01, Bob: "lets set up
thebeltholders now, hockey is here" / "can we link up collegebbbelt now too?") --
every belt game gets a preview and a result. One file, byte-identical in the
belt-holders repo (@thebeltholders: NHL, NFL, ...) and the college-basketball-belt
repo (@collegebbbelt: cbb, wcbb); which account, brand and belts it serves comes
from that repo's ig_data.json "_site" block.

For each enabled belt (IG_LEAGUES, default "nhl"):
  * "Belt on the Line" -- once on game day, from 10 AM ET (or as soon as the job
    runs after that) until an hour before the game;
  * "Belt Defended" / "New Champion" -- within minutes of the final.

Each post is a 1080x1350 card in the same design as @CollegeFBBelt's posts
(see the college-football-belt repo's ig_cards.py), a caption written by Claude
from the facts below only, the arena as the location, and the two team accounts
plus the national TV network tagged on the photo.

Where the facts come from (no lineage file is needed -- the x-posts job doesn't
build the site):
  * holder, reign, defenses, next game, win probability: the live site's
    https://beltholders.com/api/network.json (the same feed x_posts.py reads);
  * belt-game numbers and challenger history: /<league>/api/games.json and
    /<league>/api/reigns.json on the live site;
  * the game itself (arena, TV, logos, colors, final score, box score, the
    winner's next game): ESPN's public JSON -- with NO custom User-Agent, which
    ESPN's edge rejects from GitHub's runners (403).
  * handles, arena location IDs, overrides: ig_data.json (hand-checked).

    python ig_posts.py           # one pass: preview if due, result if a belt game just ended
    python ig_posts.py --check   # token check + sample cards (committed to data/ig/check/), posts nothing
    IG_DRY_RUN=1 python ig_posts.py   # build and print, post nothing

Needs IG_ACCESS_TOKEN + IG_BUSINESS_ACCOUNT_ID (the @thebeltholders Instagram
account, "API setup with Instagram login" token) and IG_LIVE=1 to post; without
them it renders and prints only. ANTHROPIC_API_KEY writes the captions (a plain
fallback caption is used without it). State: data/ig/state.json.
"""

import base64
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")
STATE = os.path.join(HERE, "data", "ig", "state.json")
STATE_REL = "data/ig/state.json"
IMAGES_REL = "data/ig/images"
CHECK_REL = "data/ig/check"
TEMPLATE_DIR = os.path.join(HERE, "ig_templates")
DATA_PATH = os.path.join(HERE, "ig_data.json")
SITE_CFG = (json.load(open(DATA_PATH)) if os.path.exists(DATA_PATH) else {}).get("_site") or {}
NETWORK = SITE_CFG.get("network", "https://beltholders.com/api/network.json")
BRAND = SITE_CFG.get("brand", "Belt Holders")
HANDLE = SITE_CFG.get("handle", "@thebeltholders")
DOMAIN = SITE_CFG.get("domain", "beltholders.com")
ABOUT = SITE_CFG.get("about", "beltholders.com, which tracks lineal championship belts in pro sports")
LEAGUES = [x for x in (os.environ.get("IG_LEAGUES") or SITE_CFG.get("leagues", "nhl")).replace(",", " ").split() if x]
REQUIRED = ("IG_ACCESS_TOKEN", "IG_BUSINESS_ACCOUNT_ID")
DRY = os.environ.get("IG_DRY_RUN") == "1"
LIVE = (not DRY) and os.environ.get("IG_LIVE", "1") == "1" and all(os.environ.get(k) for k in REQUIRED)
PREVIEW_FROM_HOUR = 10                 # ET
PREVIEW_UNTIL_BEFORE = timedelta(hours=1)
FB_GRAPH = "https://graph.facebook.com/v25.0"
IG_GRAPH = "https://graph.instagram.com"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
CAPTION_MODELS = ["claude-sonnet-4-5", "claude-haiku-4-5-20251001"]
W, H = 1080, 1350

ESPN = {"nfl": "football/nfl", "nba": "basketball/nba", "nhl": "hockey/nhl", "mlb": "baseball/mlb",
        "wnba": "basketball/wnba", "mls": "soccer/usa.1", "nwsl": "soccer/usa.nwsl", "epl": "soccer/eng.1",
        "laliga": "soccer/esp.1", "seriea": "soccer/ita.1", "bundesliga": "soccer/ger.1", "ligue1": "soccer/fra.1",
        "eredivisie": "soccer/ned.1", "cfl": "football/cfl",
        "cbb": "basketball/mens-college-basketball", "wcbb": "basketball/womens-college-basketball"}
SPORT = {"nfl": "football", "cfl": "football", "nba": "basketball", "wnba": "basketball", "nhl": "hockey",
         "pwhl": "hockey", "mlb": "baseball", "cbb": "basketball", "wcbb": "basketball"}
EST = {"nhl": 1917, "nfl": 1920, "nba": 1946, "mlb": 1876}
COLLEGE = {"cbb", "wcbb", "cfb"}
EMOJI = {"hockey": "🏒", "basketball": "🏀", "football": "🏈", "baseball": "⚾"}


def the(lg, name):
    """'the Panthers' for pro nicknames, plain 'Michigan' for colleges."""
    return name if lg in COLLEGE else f"the {name}"


def cap1(text):
    return text[:1].upper() + text[1:]


def vb(lg, plural, singular):
    """Pro nicknames are plural ('the Panthers hold'), schools singular ('Michigan holds')."""
    return singular if lg in COLLEGE else plural


def poss(name):
    return name + ("'" if name.endswith("s") else "'s")


def unit(lg):
    return "program" if lg in COLLEGE else "franchise"


# ------------------------------------------------------------------ basics --

def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"couldn't fetch {url}: {last}")


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def esc(s):
    return html.escape(str(s), quote=True)


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def d(iso):
    return date.fromisoformat(str(iso)[:10])


def now_et():
    return datetime.now(ET)


def espn_dt(s):
    s = (s or "").replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):
        s = s.replace("+", ":00+", 1)
    return datetime.fromisoformat(s)


def clock(dt_utc):
    t = dt_utc.astimezone(ET)
    h, m, ap = t.strftime("%I").lstrip("0"), t.strftime("%M"), t.strftime("%p")
    return f"{h} {ap}" if m == "00" else f"{h}:{m} {ap}"


def day_part(dt_utc):
    t = dt_utc.astimezone(ET)
    wd = t.strftime("%A")
    if t.hour < 12:
        return f"{wd} morning"
    if t.hour < 17:
        return f"{wd} afternoon"
    if t.hour < 19:
        return f"{wd} evening"
    return f"{wd} night"


def short_date(dd):
    return f"{dd:%a} {dd:%b} {dd.day}"


def tile_date(dd):
    return f"{dd:%b} {dd.day}"


def summary(line):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write(f"- {line}\n")


def ig_data(lg):
    allx = load_json(DATA_PATH, {}) or {}
    out = dict(allx.get("_all") or {})
    for k, v in (allx.get(lg) or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


# ------------------------------------------------------------------ colors --

def _rgb(hexs):
    h = (hexs or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return None
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(rgb, other, t):
    return tuple(c + (o - c) * t for c, o in zip(rgb, other))


def panel_colors(primary, accents):
    """Dark-enough panel for white type + its gradient stop + a readable,
    lighter accent (the gold of the hand-made cards' winning score)."""
    base = _rgb(primary) or (40, 40, 40)
    white = (255, 255, 255)
    steps = 0
    while contrast(base, white) < 3.4 and steps < 20:
        base = _mix(base, (0, 0, 0), 0.12)
        steps += 1
    dark = _mix(base, (0, 0, 0), 0.42)
    accent = None
    for cand in accents:
        rgb = _rgb(cand)
        if rgb and _lum(rgb) > _lum(base) and contrast(rgb, base) >= 3.2 and contrast(rgb, white) >= 1.25:
            accent = rgb
            break
    return _hex(base), _hex(dark), _hex(accent or (217, 178, 92))


def distinct_right(left_base, right_primary, right_alts):
    """Two red teams shouldn't make one red card: if the right panel would land
    too close to the left one, try that team's other colors, then charcoal."""
    def base(c):
        return _rgb(panel_colors(c, [])[0])
    lb = _rgb(left_base)
    for cand in [right_primary] + list(right_alts or []):
        rb = base(cand) if cand else None
        if rb and sum((a - b) ** 2 for a, b in zip(lb, rb)) ** 0.5 >= 70:
            return cand
    return "#2b2b2b"


def team_colors(espn_team, data):
    o = (data.get("colors") or {}).get(espn_team.get("abbreviation", ""))
    if o:
        return o[0], o[1:]
    p = "#" + espn_team["color"] if espn_team.get("color") else None
    a = ["#" + espn_team["alternateColor"]] if espn_team.get("alternateColor") else []
    return p, a


# ------------------------------------------------------------------- data --

def network_belt(lg):
    net = get_json(NETWORK)
    for b in net.get("belts") or []:
        if b.get("key") == lg:
            return b
    raise RuntimeError(f"no {lg} belt in network.json")


_BELT_URL = {}


def belt_url(lg):
    """The belt's own site section (https://beltholders.com/nhl/, https://collegebasketballbelt.com/women/)."""
    if lg not in _BELT_URL:
        try:
            _BELT_URL[lg] = network_belt(lg).get("url")
        except Exception:  # noqa: BLE001
            _BELT_URL[lg] = None
        _BELT_URL[lg] = (_BELT_URL[lg] or f"https://{DOMAIN}/{lg}/").rstrip("/") + "/"
    return _BELT_URL[lg]


def site_games(lg):
    return (get_json(belt_url(lg) + "api/games.json") or {}).get("belt_games") or []


def site_reigns(lg):
    return (get_json(belt_url(lg) + "api/reigns.json") or {}).get("reigns") or []


def history(reigns, name, before):
    """Reign count, total days, last year held -- all before `before`."""
    n, days, last = 0, 0, None
    for r in reigns:
        if fold(r.get("name")) != fold(name):
            continue
        s = d(r["start_date"])
        if s >= before:
            continue
        e = d(r["end_date"]) if r.get("end_date") else before
        n += 1
        days += max(0, (min(e, before) - s).days)
        y = e.year
        last = y if last is None else max(last, y)
    return n, days, last


def belt_meetings(games, a, b, before):
    out = []
    for g in games:
        names = {fold(g.get("holder_name")), fold(g.get("opponent_name"))}
        if names == {fold(a), fold(b)} and d(g["date"]) < before:
            out.append(g)
    return out


def espn_scoreboard_event(lg, day, holder, opponent):
    j = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[lg]}/scoreboard?dates={day:%Y%m%d}&limit=400")
    hk, ok = fold(holder), fold(opponent)
    for ev in j.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        names = []
        for t in comp.get("competitors") or []:
            tm = t.get("team") or {}
            names.append({fold(tm.get(k)) for k in ("displayName", "shortDisplayName", "name", "location") if tm.get(k)})
        if len(names) == 2 and any(hk in n for n in names) and any(ok in n for n in names):
            return ev
    return None


def espn_summary(lg, event_id):
    return get_json(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[lg]}/summary?event={event_id}")


def comp_of(summ):
    return summ["header"]["competitions"][0]


def side(summ, name):
    for c in comp_of(summ)["competitors"]:
        tm = c["team"]
        if fold(name) in {fold(tm.get(k)) for k in ("displayName", "shortDisplayName", "location", "name") if tm.get(k)}:
            return c
    raise RuntimeError(f"{name} not in ESPN event")


def national_tv(summ):
    out = []
    for b in summ.get("broadcasts") or comp_of(summ).get("broadcasts") or []:
        mkt = ((b.get("market") or {}).get("type") or "").lower()
        name = (b.get("media") or {}).get("shortName") or ""
        if name and mkt in ("national", "") and name not in out:
            out.append(name)
    return out


def venue_of(summ):
    v = (summ.get("gameInfo") or {}).get("venue") or {}
    return v.get("fullName") or "", ((v.get("address") or {}).get("city") or "")


def team_stat(summ, team_id, name):
    for t in (summ.get("boxscore") or {}).get("teams") or []:
        if str(t["team"]["id"]) == str(team_id):
            for s in t.get("statistics") or []:
                if s.get("name") == name:
                    return s.get("displayValue")
    return None


def goalie_line(summ, team_id):
    """(name, saves, goals_against) of the team's goalie with the most TOI."""
    for p in (summ.get("boxscore") or {}).get("players") or []:
        if str(p["team"]["id"]) != str(team_id):
            continue
        for grp in p.get("statistics") or []:
            if grp.get("name") != "goalies":
                continue
            labels = grp.get("labels") or []
            best = None
            for a in grp.get("athletes") or []:
                st = dict(zip(labels, a.get("stats") or []))
                try:
                    sv, ga = int(st.get("SV", 0)), int(st.get("GA", 0))
                except ValueError:
                    continue
                if best is None or sv + ga > best[1] + best[2]:
                    best = ((a.get("athlete") or {}).get("displayName", ""), sv, ga)
            return best
    return None


def skater_goals(summ, team_id):
    out = []
    for p in (summ.get("boxscore") or {}).get("players") or []:
        if str(p["team"]["id"]) != str(team_id):
            continue
        for grp in p.get("statistics") or []:
            if grp.get("name") not in ("forwards", "defenses"):
                continue
            labels = grp.get("labels") or []
            for a in grp.get("athletes") or []:
                st = dict(zip(labels, a.get("stats") or []))
                try:
                    g, ast = int(st.get("G", 0)), int(st.get("A", 0))
                except ValueError:
                    continue
                if g or ast:
                    out.append(((a.get("athlete") or {}).get("displayName", ""), g, ast))
    out.sort(key=lambda x: (x[1], x[1] + x[2]), reverse=True)
    return out


def scoring_plays(summ):
    plays = summ.get("scoringPlays") or [p for p in (summ.get("plays") or []) if p.get("scoringPlay")]
    out = []
    for p in plays:
        per = (p.get("period") or {}).get("number")
        clk = (p.get("clock") or {}).get("displayValue")
        out.append(f"P{per} {clk}: {p.get('text')} ({p.get('awayScore')}-{p.get('homeScore')} away-home)")
    return out[:20]


def leaders(summ, team_id):
    """{category: (name, displayValue)} from ESPN's leaders block."""
    out = {}
    for blk in summ.get("leaders") or []:
        if str((blk.get("team") or {}).get("id")) != str(team_id):
            continue
        for cat in blk.get("leaders") or []:
            if cat.get("leaders"):
                ld = cat["leaders"][0]
                out[cat.get("name")] = ((ld.get("athlete") or {}).get("displayName", ""), ld.get("displayValue", ""))
    return out


def last_name(full):
    parts = [x for x in (full or "").split() if x]
    while len(parts) > 1 and parts[-1].rstrip(".").lower() in ("jr", "sr", "ii", "iii", "iv"):
        parts.pop()
    return parts[-1] if parts else full


def standout(lg, summ, team_id, won_by_shutout):
    """Tile 2 of the result card."""
    if SPORT.get(lg) == "hockey":
        sk = skater_goals(summ, team_id)
        if sk and sk[0][1] >= 2:
            n = sk[0][1]
            return (str(n), f"{last_name(sk[0][0])} · {'hat trick' if n == 3 else 'goals'}"), sk
        gl = goalie_line(summ, team_id)
        if gl:
            return (str(gl[1]), f"{last_name(gl[0])} · {'saves, shutout' if gl[2] == 0 else 'saves'}"), sk
        if sk:
            return (str(sk[0][1] + sk[0][2]), f"{last_name(sk[0][0])} · points"), sk
    if SPORT.get(lg) == "basketball":
        ld = leaders(summ, team_id)
        if ld.get("points"):
            name, val = ld["points"]
            m = re.match(r"\d+", str(val))
            if m:
                return (m.group(0), f"{last_name(name)} · points"), []
    return None, []


def next_game_after(lg, team_id, after):
    try:
        sch = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{ESPN[lg]}/teams/{team_id}/schedule")
    except Exception as e:  # noqa: BLE001
        print(f"  (no schedule: {e})")
        return None
    for ev in sch.get("events") or []:
        try:
            when = espn_dt(ev["date"])
        except Exception:  # noqa: BLE001
            continue
        if when.astimezone(ET).date() <= after:
            continue
        c = ev["competitions"][0]
        me = next((x for x in c["competitors"] if str(x["team"]["id"]) == str(team_id)), None)
        opp = next((x for x in c["competitors"] if str(x["team"]["id"]) != str(team_id)), None)
        if not me or not opp:
            continue
        return {"date": when.astimezone(ET).date(), "dt": when, "home": me.get("homeAway") == "home",
                "opp": opp["team"].get("displayName") or opp["team"].get("location"),
                "opp_short": opp["team"].get("shortDisplayName") or opp["team"].get("name") or "",
                "opp_abbr": opp["team"].get("abbreviation", ""),
                "tv": [((b.get("media") or {}).get("shortName") or "") for b in (c.get("broadcasts") or [])
                       if ((b.get("market") or {}).get("type") or "").lower() == "national"]}
    return None


# ----------------------------------------------------------------- render --

BELT_SVG = """<svg class="belt" viewBox="0 0 260 150" fill="none">
  <defs>
    <linearGradient id="brassG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d9b25c"/><stop offset=".55" stop-color="#a97f38"/><stop offset="1" stop-color="#7d5a25"/></linearGradient>
    <linearGradient id="strapG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3a2d1c"/><stop offset="1" stop-color="#1a130b"/></linearGradient>
    <filter id="sh" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="10" stdDeviation="9" flood-color="#000" flood-opacity=".45"/></filter>
  </defs>
  <g filter="url(#sh)">
    <rect x="0" y="57" width="260" height="36" rx="4" fill="url(#strapG)"/>
    <rect x="0" y="57" width="260" height="3" fill="#a97f38" opacity=".6"/>
    <rect x="0" y="90" width="260" height="3" fill="#a97f38" opacity=".6"/>
    <rect x="18" y="46" width="42" height="58" rx="5" fill="url(#brassG)" stroke="#211a12" stroke-width="2.5"/>
    <rect x="200" y="46" width="42" height="58" rx="5" fill="url(#brassG)" stroke="#211a12" stroke-width="2.5"/>
    <circle cx="39" cy="75" r="9" fill="#211a12" opacity=".85"/>
    <circle cx="221" cy="75" r="9" fill="#211a12" opacity=".85"/>
    <path d="M130 8 L182 30 L182 120 L130 142 L78 120 L78 30 Z" fill="url(#brassG)" stroke="#211a12" stroke-width="3"/>
    <path d="M130 22 L170 39 L170 111 L130 128 L90 111 L90 39 Z" fill="none" stroke="#211a12" stroke-width="2" opacity=".55"/>
  </g>
  <text x="130" y="97" text-anchor="middle" font-family="Big Shoulders Display" font-weight="900" font-size="{fs}" fill="#211a12" letter-spacing="1">{txt}</text>
</svg>"""


def header(lg, belt_name, est=None, right=None):
    est = est or EST.get(lg)
    if not right:
        if fold(belt_name) == fold(BRAND):
            right = f"Est. {est} · Lineal title" if est else "Lineal title"
        else:
            right = f"{belt_name} · Since {est}" if est else belt_name
    return f"""<div class="hdr">
  <div class="brand">
    <svg width="52" height="34" viewBox="0 0 34 22" fill="none"><rect x="0" y="8" width="34" height="6" rx="1" fill="#211a12"/><rect x="3" y="6" width="6" height="10" rx="1" fill="#a97f38"/><rect x="25" y="6" width="6" height="10" rx="1" fill="#a97f38"/><path d="M17 0 L24 4 L24 18 L17 22 L10 18 L10 4 Z" fill="#a97f38" stroke="#211a12" stroke-width="1.5"/><circle cx="17" cy="11" r="3.5" fill="#211a12"/></svg>
    <div class="disp wm" style="white-space:nowrap">{esc(BRAND)}</div>
  </div>
  <div class="mono est" style="white-space:nowrap">{esc(right)}</div>
</div>
<div class="rule"></div>"""


FOOT = (f'<div class="mono foot"><span>{html.escape(HANDLE)}</span><span class="url">{html.escape(DOMAIN)}</span></div>'
        '\n<div class="grain"></div>')

FIT_JS = """() => {
  const fit = (el, min, box) => {
    let fs = parseFloat(getComputedStyle(el).fontSize);
    const over = () => el.scrollWidth > el.clientWidth + 1 || (box && el.scrollHeight > el.clientHeight + 1);
    while (over() && fs > min) { fs -= 1; el.style.fontSize = fs + 'px'; }
    return over();
  };
  const bad = [];
  const rules = [['.h1', 90], ['.when', 15], ['.kicker', 14], ['.role', 13], ['.team', 36], ['.stat', 13],
                 ['.tile .v', 44], ['.tile .l', 12], ['.beltcap', 12], ['.score', 100], ['.est', 12]];
  for (const [sel, min] of rules) for (const el of document.querySelectorAll(sel)) if (fit(el, min, false)) bad.push(sel);
  for (const el of document.querySelectorAll('.note')) if (fit(el, 18, true)) bad.push('.note');
  return bad;
}"""


def belt_svg(text):
    fs = 62 if len(text) <= 2 else (48 if len(text) == 3 else (38 if len(text) == 4 else 32))
    return BELT_SVG.replace("{fs}", str(fs)).replace("{txt}", esc(text))


def chip(img, abbr):
    if img:
        return f'<div class="chip"><img src="file://{esc(img)}" alt=""></div>'
    return f'<div class="chip"><span class="disp abbr">{esc(abbr)}</span></div>'


def two_lines(name):
    words = name.split()
    if len(words) < 2:
        return esc(name)
    best, cut = None, 1
    for i in range(1, len(words)):
        sc = max(len(" ".join(words[:i])), len(" ".join(words[i:])))
        if best is None or sc < best:
            best, cut = sc, i
    return esc(" ".join(words[:cut])) + "<br>" + esc(" ".join(words[cut:]))


def page(body, classes, colors):
    css_vars = ";".join(f"--{k}:{v}" for k, v in colors.items())
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<link rel="stylesheet" href="card.css"><style>:root{{{css_vars}}}</style></head>'
            f'<body><div class="canvas {classes}">{body}</div></body></html>')


_PW = False


def ensure_playwright():
    global _PW
    if _PW:
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
    if not os.environ.get("IG_CHROMIUM_PATH"):
        # GitHub's Ubuntu runners already ship Google Chrome with everything it
        # needs; using it skips a browser download and an apt-get of system
        # libraries that once took 7+ minutes (2026-10-01).
        for exe in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium-browser"):
            if os.path.exists(exe):
                os.environ["IG_CHROMIUM_PATH"] = exe
                break
        else:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    _PW = True


def render(html_text, out_jpg):
    ensure_playwright()
    from playwright.sync_api import sync_playwright
    from PIL import Image
    src = os.path.join(TEMPLATE_DIR, "_card.html")
    with open(src, "w") as f:
        f.write(html_text)
    big = out_jpg + ".2x.png"
    try:
        with sync_playwright() as p:
            kw = {"executable_path": os.environ["IG_CHROMIUM_PATH"]} if os.environ.get("IG_CHROMIUM_PATH") else {}
            b = p.chromium.launch(**kw)
            pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
            pg.goto("file://" + src)
            pg.evaluate("document.fonts.ready.then(() => true)")
            pg.wait_for_timeout(400)
            bad = pg.evaluate(FIT_JS)
            fonts = pg.evaluate("() => Array.from(document.fonts).filter(f => f.status === 'loaded').length")
            pg.screenshot(path=big, clip={"x": 0, "y": 0, "width": W, "height": H})
            b.close()
        Image.open(big).convert("RGB").resize((W, H), Image.LANCZOS).save(
            out_jpg, "JPEG", quality=92, optimize=True, progressive=True)
        return list(bad) + ([f"only {fonts} fonts loaded"] if fonts < 4 else [])
    finally:
        for pth in (src, big):
            try:
                os.remove(pth)
            except OSError:
                pass


def fetch_logo(url, workdir, key):
    if not url:
        return None
    path = os.path.join(workdir, f"logo-{fold(key)}.png")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=25) as r, open(path, "wb") as f:
            f.write(r.read())
        return path
    except Exception as e:  # noqa: BLE001
        print(f"  (no logo {url}: {e})")
        return None


def logo_of(team):
    logos = team.get("logos") or []
    if logos:
        return logos[0].get("href")
    return team.get("logo")


# ---------------------------------------------------------------- captions --

STYLE_RESULT = """The belt stays in South Bend. 🏆

Notre Dame 27, Michigan State 10. Third defense of the Irish's 9th reign, now 294 days and counting since they took it from Stanford on Nov. 29.

The Spartans hung around for a half — 17–10 at the break — but the Irish never trailed and never blinked. CJ Carr went 18 of 24 for 234, Micah Gilbert caught 8 balls for 170 (61 of them on the very first snap), Nolan James Jr. ground out 121 and a score, and the defense picked Michigan State off twice and held them to 167 total yards.

Belt game No. 1,638 is in the books. Michigan State's wait since 2018 continues.

Next up: the Irish carry the belt to West Lafayette. At Purdue, Sat Sep 26, 2 PM ET on Peacock. Beat the holder, take the belt.

🔗 Box score, drive chart and the full chain of custody since 1869 → link in bio

#CollegeFootballBelt #NotreDame #GoIrish #MichiganState #CollegeFootball #CFB #FightingIrish #Spartans #NDvsMSU #Purdue"""

STYLE_PREVIEW = """293 days. 2 defenses. One belt. Michigan State gets its shot Saturday night. 🏆

Notre Dame has held the College Football Belt since taking it from Stanford on Nov. 29 — the program's 9th reign since 1869. Michigan State hasn't touched it since 2018, and these two have never met with the belt on the line. Belt game No. 1,638 fixes that.

The numbers say Irish: 97% to defend, −29.5 at DraftKings, and the lean is Notre Dame 42–17.

The belt doesn't read numbers. No committee, no poll — you have to take it from whoever's holding it.

🏈 Sat · 7:30 PM ET · NBC + Peacock · Notre Dame Stadium
🔗 Full preview, head-to-head history and 157 years of chain of custody → link in bio

#CollegeFootballBelt #NotreDame #GoIrish #MichiganState #GoGreen #CollegeFootball #CFB #NDvsMSU #FightingIrish #Spartans"""


def claude_caption(kind, facts, lg):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    example = STYLE_RESULT if kind == "result" else STYLE_PREVIEW
    what = "the result of the belt game that just ended" if kind == "result" else "a preview of today's belt game"
    sport = SPORT.get(lg, "soccer")
    emoji = {"hockey": "🏒", "basketball": "🏀", "football": "🏈", "baseball": "⚾"}.get(sport, "⚽")
    prompt = f"""You write the Instagram captions for {HANDLE}, the account for {ABOUT} (whoever beats the holder takes the belt). This post is about {facts.get('belt_name')}.

Write {what}. Match the voice, length and structure of this caption from the sister account @CollegeFBBelt (a college football example -- adapt it to {sport}):

<example>
{example}
</example>

Facts for this post (use ONLY these -- never add a stat, record, streak, injury, quote or storyline that isn't here; if an idea in the example has no matching fact, leave it out):
<facts>
{json.dumps(facts, indent=1, ensure_ascii=False, default=str)}
</facts>

Rules:
- Same shape: a punchy first line ending in 🏆, short paragraphs, then {"a 'Next up' paragraph" if kind == "result" else f"a '{emoji} day · time · TV · arena' line"}, then a '🔗 ... → link in bio' line, then one line of 8-11 hashtags.
- Hashtags: start with {SITE_CFG.get('tags', '#BeltHolders')} and #{facts.get('league_tag')}Belt, then both teams' common tags (e.g. #FlaPanthers style only if you're sure; otherwise the plain team names), #{facts.get('league_tag')} and an ABBRvsABBR tag.
- These are pro (or college) teams: say "franchise" or "club" for pros, never "program" unless it's a college team.
- The italic note and the caption must not misstate when or where anything happened: a preview is about an upcoming game (the holder won the belt earlier, in the game in the facts), never "begins its reign tonight".
- No @mentions, no links, no hype exclamation marks. En dash in scores (4–2).
- Under 1,500 characters.
- Also a two-line italic note for the bottom of the card: a bold first sentence of at most 45 characters, then at most 115 more characters.

Reply with JSON only: {{"caption": "...", "note_bold": "...", "note_rest": "..."}}"""
    body = {"max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}
    for model in CAPTION_MODELS:
        body["model"] = model
        try:
            req = urllib.request.Request(ANTHROPIC_URL, data=json.dumps(body).encode(), headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.loads(r.read().decode())
            text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
            res = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            cap = (res.get("caption") or "").strip()
            first_tag = SITE_CFG.get("tags", "#BeltHolders").split()[0]
            if not cap or len(cap) > 2200 or first_tag not in cap or cap.count("#") > 30:
                raise ValueError("caption failed checks")
            for must in facts.get("must_mention", []):
                if str(must) not in cap:
                    raise ValueError(f"caption is missing {must!r}")
            nb, nr = (res.get("note_bold") or "").strip(), (res.get("note_rest") or "").strip()
            if len(nb) > 60 or len(nb) + len(nr) > 190:
                nb, nr = "", ""
            print(f"  caption written by {model}")
            return {"caption": cap, "note_bold": nb, "note_rest": nr}
        except Exception as e:  # noqa: BLE001
            print(f"  caption via {model} failed ({e})")
    return None


def hashtags(lg, a, a_abbr, b, b_abbr):
    tags = SITE_CFG.get("tags", "#BeltHolders").replace("#", "").split() + [f"{lg.upper()}Belt", a, b, lg.upper(), f"{a_abbr}vs{b_abbr}"]
    out, seen = [], set()
    for t in tags:
        t = re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append("#" + t)
    return " ".join(out)


# -------------------------------------------------------- handles / places --

def handle(data, team_name):
    th = data.get("team_handles") or {}
    h = th.get(team_name) or next((v for k, v in th.items() if fold(k) == fold(team_name)), None)
    return (h or "").lstrip("@") or None


def network_handle(data, nets):
    nh = data.get("network_handles") or {}
    for n in nets:
        if nh.get(n):
            return nh[n].lstrip("@")
    return None


def location(data, venue):
    v = (data.get("locations") or {}).get(venue)
    if not v:
        v = next((x for k, x in (data.get("locations") or {}).items() if fold(k) == fold(venue)), None)
    return str(v) if v else None


def city_for(data, team_name, location_field):
    return (data.get("cities") or {}).get(team_name) or location_field


def tags_for(data, left, right, nets):
    out = []
    for team, x in ((left, 0.27), (right, 0.73)):
        h = handle(data, team)
        if h:
            out.append({"username": h, "x": x, "y": 0.47})
    nh = network_handle(data, nets)
    if nh:
        out.append({"username": nh, "x": 0.5, "y": 0.255})
    return out


# -------------------------------------------------------------- the cards --

def build_preview(lg, belt, workdir):
    """'Belt on the Line' for belt['next'] (today's game)."""
    data = ig_data(lg)
    nx = belt["next"]
    gday = d(nx["date"])
    holder, opp = belt["holder"], nx["opponent"]
    ev = espn_scoreboard_event(lg, gday, holder, opp)
    if not ev:
        raise RuntimeError(f"no ESPN event for {holder} vs {opp} on {gday}")
    summ = espn_summary(lg, ev["id"])
    comp = comp_of(summ)
    hs, os_ = side(summ, holder), side(summ, opp)
    ht, ot = hs["team"], os_["team"]
    kick = espn_dt(comp.get("date") or ev.get("date"))
    venue, _city = venue_of(summ)
    nets = national_tv(summ)
    games, reigns = site_games(lg), site_reigns(lg)
    game_no = (games[-1]["n"] + 1) if games else None
    since = d(belt["since"])
    days_held = (gday - since).days
    defenses = int(belt.get("defenses") or 0)
    reign_no = int(belt.get("reign_no") or 1)
    o_n, o_days, o_last = history(reigns, opp, gday)
    met = belt_meetings(games, holder, opp, gday)
    pct = nx.get("win_prob")
    hshort = belt.get("holder_short") or ht.get("name") or holder
    oshort = nx.get("opponent_short") or ot.get("name") or opp
    won_from = next((r.get("won_from_name") for r in reversed(reigns) if fold(r.get("name")) == fold(holder)), None)

    tiles = []
    if pct is not None:
        tiles.append((f"{round(pct * 100)}<small>%</small>", f"{hshort} to defend · model"))
    tiles.append((f"{o_n}", f"{oshort} reigns all-time"))
    tiles.append((f"{len(met)}", "Belt games, this matchup"))
    when = '<span class="sep">·</span>'.join(
        [f"<b>{esc(short_date(gday))}</b>", f"<b>{esc(clock(kick) + ' ET')}</b>"]
        + ([esc(" + ".join(nets[:2]))] if nets else []) + ([esc(venue)] if venue else []))
    role_r = f"Challenger · last held {o_last}" if o_last else "Challenger · never held it"
    stat_r = (f"<b>{o_n}</b> {'reign' if o_n == 1 else 'reigns'} · <b>{o_days:,}</b> days all-time" if o_n
              else "<b>0</b> reigns · chasing a first")

    facts = {
        "belt_name": belt.get("name"), "league_tag": lg.upper(), "belt_game_number": f"{game_no:,}" if game_no else None,
        "holder": holder, "holder_short": hshort, "challenger": opp, "challenger_short": oshort,
        "holder_reign_number_for_this_team": ordinal(reign_no), "holder_took_belt_from": won_from,
        "holder_took_belt_on": f"{since:%b} {since.day}, {since.year}", "days_held_on_game_day": days_held,
        "defenses_so_far_this_reign": defenses, "this_would_be_defense_number": defenses + 1,
        "challenger_reigns_all_time": o_n, "challenger_days_with_belt_all_time": o_days,
        "challenger_last_held_year": o_last, "previous_belt_games_between_them": len(met),
        "last_belt_meetings": [{"date": g["date"], "holder": g.get("holder_name"), "score_home_away": g.get("score"),
                                "home": g.get("home"), "outcome": g.get("outcome")} for g in met[-3:]],
        "start": f"{kick.astimezone(ET):%a} {clock(kick)} ET", "day_part": day_part(kick),
        "national_tv": " + ".join(nets) or None, "arena": venue, "holder_is_home": bool(nx.get("home")),
        "holder_win_probability": f"{round(pct * 100)}%" if pct is not None else None,
        "belt_history_starts": EST.get(lg),
        "hashtag_suggestion": hashtags(lg, hshort, ht.get("abbreviation"), oshort, ot.get("abbreviation")),
    }
    cap = claude_caption("preview", facts, lg) or {
        "caption": (f"{days_held:,} {'day' if days_held == 1 else 'days'}. {defenses} "
                    f"{'defense' if defenses == 1 else 'defenses'}. One belt. {cap1(the(lg, oshort))} {vb(lg, 'get their', 'gets its')} shot {day_part(kick)}. 🏆\n\n"
                    f"{cap1(the(lg, holder))} {vb(lg, 'hold', 'holds')} {belt.get('name')}" + (f", taken from {the(lg, won_from)} on {since:%b} {since.day}" if won_from else "")
                    + f" — the {unit(lg)}'s {ordinal(reign_no)} reign." + (f" Belt game No. {game_no:,}." if game_no else "") + "\n\n"
                    "No committee, no poll — beat the holder, take the belt.\n\n"
                    f"{EMOJI.get(SPORT.get(lg), '⚽')} {kick.astimezone(ET):%a} · {clock(kick)} ET" + (f" · {' + '.join(nets[:2])}" if nets else "")
                    + (f" · {venue}" if venue else "") + "\n🔗 Preview and the full chain of custody → link in bio\n\n"
                    + facts["hashtag_suggestion"]), "note_bold": "", "note_rest": ""}
    nb = cap.get("note_bold") or (f"{len(met)} belt games between these two." if met else "First belt game between these two.")
    nr = cap.get("note_rest") or (f"{cap1(the(lg, hshort))} took the belt on {since:%b} {since.day}.")

    lp, la = team_colors(ht, data)
    rp, ra = team_colors(ot, data)
    cl = panel_colors(lp, la)
    cr = panel_colors(distinct_right(cl[0], rp, ra), [])
    body = f"""{header(lg, belt.get('name') or lg.upper(), data.get('est'), data.get('header'))}
<div class="mono kicker"><span class="dot"></span>{('Belt game No. ' + f'{game_no:,}' + ' · ') if game_no else ''}{esc(day_part(kick))}</div>
<div class="disp h1">Belt on <span class="thin">the line</span></div>
<div class="mono when">{when}</div>
<div class="card">
  <div class="panel l">
    {chip(fetch_logo(logo_of(ht), workdir, ht.get('abbreviation', 'h')), ht.get('abbreviation', ''))}
    <div class="mono role">Holder · {ordinal(reign_no)} reign</div>
    <div class="disp team">{two_lines(holder)}</div>
    <div class="mono stat"><b>{days_held:,}</b> {'day' if days_held == 1 else 'days'} held · <b>{defenses}</b> {'defense' if defenses == 1 else 'defenses'}</div>
  </div>
  <div class="seam"></div>
  <div class="panel r">
    {chip(fetch_logo(logo_of(ot), workdir, ot.get('abbreviation', 'o')), ot.get('abbreviation', ''))}
    <div class="mono role">{esc(role_r)}</div>
    <div class="disp team">{two_lines(opp)}</div>
    <div class="mono stat">{stat_r}</div>
  </div>
  {belt_svg('VS')}
</div>
<div class="tiles">{''.join(f'<div class="tile"><div class="disp v">{v}</div><div class="mono l">{esc(lab)}</div></div>' for v, lab in tiles[:3])}</div>
<div class="note"><b>{esc(nb)}</b> {esc(nr)}</div>
{FOOT}"""
    out = os.path.join(workdir, f"{lg}-belt-on-the-line-{fold(hshort)}-{fold(oshort)}-{gday}.jpg")
    bad = render(page(body, "preview", {"l1": cl[0], "l2": cl[1], "lacc": cl[2], "r1": cr[0], "r2": cr[1]}), out)
    return {"kind": "preview", "image": out, "caption": cap["caption"], "fit_problems": bad,
            "user_tags": tags_for(data, holder, opp, nets), "location_id": location(data, venue), "venue": venue,
            "alt_text": (f"{belt.get('name')}: belt on the line. {holder} ({days_held} days, {defenses} defenses) vs. {opp}, "
                         f"{short_date(gday)}, {clock(kick)} ET, {venue}."),
            "pending": {"lg": lg, "date": gday.isoformat(), "holder": holder, "holder_short": hshort, "opponent": opp,
                        "opponent_short": oshort, "espn_id": ev["id"], "since": belt["since"], "defenses": defenses,
                        "reign_no": reign_no, "game_no": game_no, "belt_name": belt.get("name")}}


def build_result(p, workdir, summ=None):
    """'Belt Defended' / 'New Champion' for a pending game record `p`."""
    lg = p["lg"]
    data = ig_data(lg)
    summ = summ or espn_summary(lg, p["espn_id"])
    comp = comp_of(summ)
    hs, os_ = side(summ, p["holder"]), side(summ, p["opponent"])
    ht, ot = hs["team"], os_["team"]
    h_pts, o_pts = int(float(hs.get("score") or 0)), int(float(os_.get("score") or 0))
    detail = ((comp.get("status") or {}).get("type") or {}).get("detail") or ""
    m = re.search(r"/(OT|SO|\dOT)", detail)
    extra = m.group(1) if m else ""
    changed = o_pts > h_pts
    tie = o_pts == h_pts
    gday = d(p["date"])
    venue, _city = venue_of(summ)
    nets = national_tv(summ)
    reigns = site_reigns(lg)
    since = d(p["since"])
    days_held = (gday - since).days
    defense_no = int(p.get("defenses") or 0) + 1
    o_n, o_days, o_last = history(reigns, p["opponent"], gday)
    winner, loser = (p["opponent"], p["holder"]) if changed else (p["holder"], p["opponent"])
    wt, lt = (ot, ht) if changed else (ht, ot)
    wshort = (p["opponent_short"] if changed else p["holder_short"]) or wt.get("name")
    lshort = (p["holder_short"] if changed else p["opponent_short"]) or lt.get("name")
    w_pts, l_pts = max(h_pts, o_pts), min(h_pts, o_pts)
    stand, sk = standout(lg, summ, wt["id"], l_pts == 0)
    nxt = next_game_after(lg, wt["id"], gday)
    city = city_for(data, winner, wt.get("location"))
    game_no = p.get("game_no")

    def stat_line(tid):
        if SPORT.get(lg) == "hockey":
            sog = team_stat(summ, tid, "shotsTotal")
            ppg, ppo = team_stat(summ, tid, "powerPlayGoals"), team_stat(summ, tid, "powerPlayOpportunities")
            bits = []
            if sog is not None:
                bits.append(f"<b>{esc(sog)}</b> shots")
            if ppg is not None and ppo is not None:
                bits.append(f"<b>{esc(ppg)}/{esc(ppo)}</b> power play")
            return " · ".join(bits)
        if SPORT.get(lg) == "basketball":
            fg, reb = team_stat(summ, tid, "fieldGoalPct"), team_stat(summ, tid, "totalRebounds")
            bits = []
            if fg is not None:
                bits.append(f"<b>{esc(fg)}%</b> FG")
            if reb is not None:
                bits.append(f"<b>{esc(reb)}</b> rebounds")
            return " · ".join(bits)
        return ""

    if changed:
        h1 = 'New <span class="thin">champion</span>'
        when_tail = f"<b>{esc(wt.get('abbreviation') or winner)}</b>'s {ordinal(o_n + 1)} reign begins"
        role_l, role_r = f"New holder · {ordinal(o_n + 1)} reign", f"Dethroned · {days_held:,} {'day' if days_held == 1 else 'days'}"
        capline = f"Moves to {city}" if city else f"Goes to {the(lg, wshort)}"
        tile1 = (f"{days_held:,}", f"Days {lt.get('abbreviation') or lshort} held it")
    else:
        h1 = 'Belt <span class="thin">defended</span>'
        when_tail = f"<b>{ordinal(defense_no)} defense</b> this reign"
        role_l = "Holder · retains" if not tie else "Holder · retains on a tie"
        role_r = f"Challenger · last held {o_last}" if o_last else "Challenger · never held it"
        capline = f"Stays in {city}" if city else f"Stays with {the(lg, wshort)}"
        tile1 = (f"{days_held:,}", "Days held this reign")
    tiles = [tile1, stand or (f"{w_pts}–{l_pts}", "Final")]
    if nxt:
        where = "vs" if nxt["home"] else "at"
        opp_lab = nxt["opp_short"] if len(nxt["opp_short"] or "") <= 10 else nxt["opp_abbr"]
        tiles.append((tile_date(nxt["date"]), f"Next · {where} {opp_lab}, {clock(nxt['dt'])}"))
    elif game_no:
        tiles.append((f"{game_no:,}", "Belt game No."))

    facts = {
        "belt_name": p.get("belt_name"), "league_tag": lg.upper(),
        "headline": "NEW CHAMPION -- the belt changed hands" if changed else "BELT DEFENDED",
        "final_score": f"{winner} {w_pts}, {loser} {l_pts}" + (f" ({extra})" if extra else ""),
        "date": f"{gday:%a} {gday:%b} {gday.day}", "arena": venue, "winner": winner, "winner_short": wshort,
        "loser": loser, "loser_short": lshort, "belt_game_number": f"{game_no:,}" if game_no else None,
        "holder_going_in": p["holder"], "holder_reign_number_for_team": ordinal(int(p.get("reign_no") or 1)),
        "holder_had_held_it_since": f"{since:%b} {since.day}, {since.year}", "days_holder_had_held_it": days_held,
        "this_was_defense_number": None if changed else defense_no,
        "winner_new_reign_number_for_team": ordinal(o_n + 1) if changed else None,
        "challenger_last_held_year_before_today": o_last,
        "where_the_belt_goes": city,
        "period_by_period": {c["team"].get("abbreviation"): [x.get("displayValue") for x in (c.get("linescores") or [])]
                             for c in comp["competitors"]},
        "scoring": scoring_plays(summ) if SPORT.get(lg) in ("hockey", "football", "soccer", None) else [],
        "winner_leaders": leaders(summ, wt["id"]), "loser_leaders": leaders(summ, lt["id"]),
        "winner_scorers_goals_assists": [{"name": n, "goals": g, "assists": a} for n, g, a in sk[:5]],
        "winner_goalie": dict(zip(("name", "saves", "goals_against"), goalie_line(summ, wt["id"]) or ())) or None,
        "shots": {wshort: team_stat(summ, wt["id"], "shotsTotal"), lshort: team_stat(summ, lt["id"], "shotsTotal")},
        "next_game_for_belt_holder": ({"date": f"{nxt['date']:%a} {nxt['date']:%b} {nxt['date'].day}", "opponent": nxt["opp"],
                                       "home": nxt["home"], "start_et": clock(nxt["dt"]) + " ET",
                                       "national_tv": " + ".join(x for x in nxt["tv"] if x) or None} if nxt else None),
        "hashtag_suggestion": hashtags(lg, wshort, wt.get("abbreviation"), lshort, lt.get("abbreviation")),
        "must_mention": [str(w_pts), str(l_pts)],
    }
    cap = claude_caption("result", facts, lg)
    if not cap:
        nl = ""
        if nxt:
            nl = (f"Next up: {'vs.' if nxt['home'] else 'at'} {the(lg, nxt['opp_short'] or nxt['opp'])}, "
                  f"{nxt['date']:%a} {nxt['date']:%b} {nxt['date'].day}, {clock(nxt['dt'])} ET. Beat the holder, take the belt.\n\n")
        lead = (f"{p.get('belt_name')} has a new home. 🏆\n\n{winner} {w_pts}, {loser} {l_pts}{(' (' + extra + ')') if extra else ''}. "
                f"{cap1(the(lg, wshort))} {vb(lg, 'take', 'takes')} the belt and {vb(lg, 'end', 'ends')} {poss(the(lg, lshort))} run at {days_held:,} {'day' if days_held == 1 else 'days'}.\n\n") if changed else \
               (f"The belt stays with {the(lg, wshort)}. 🏆\n\n{winner} {w_pts}, {loser} {l_pts}{(' (' + extra + ')') if extra else ''}. "
                f"Defense No. {defense_no} of the reign.\n\n")
        cap = {"caption": lead + (f"Belt game No. {game_no:,} is in the books.\n\n" if game_no else "") + nl
               + "🔗 Box score and the full chain of custody → link in bio\n\n" + facts["hashtag_suggestion"],
               "note_bold": "", "note_rest": ""}
    nb = cap.get("note_bold") or (cap1(the(lg, wshort)) + (f" {vb(lg, 'take', 'takes')} the belt." if changed else f" {vb(lg, 'hold', 'holds')} on."))
    nr = cap.get("note_rest") or f"Final: {winner} {w_pts}, {loser} {l_pts}{(' (' + extra + ')') if extra else ''}."

    lp, la = team_colors(wt, data)
    rp, ra = team_colors(lt, data)
    cl = panel_colors(lp, la)
    cr = panel_colors(distinct_right(cl[0], rp, ra), [])
    final_kick = f"Final/{extra}" if extra else "Final"
    body = f"""{header(lg, p.get('belt_name') or lg.upper(), data.get('est'), data.get('header'))}
<div class="mono kicker"><span class="dot"></span>{('Belt game No. ' + f'{game_no:,}' + ' · ') if game_no else ''}{final_kick}</div>
<div class="disp h1">{h1}</div>
<div class="mono when"><b>{esc(short_date(gday))}</b><span class="sep">·</span>{esc(venue)}<span class="sep">·</span>{when_tail}</div>
<div class="card">
  <div class="panel l">
    {chip(fetch_logo(logo_of(wt), workdir, wt.get('abbreviation', 'w')), wt.get('abbreviation', ''))}
    <div class="mono role">{esc(role_l)}</div>
    <div class="disp score">{w_pts}</div>
    <div class="disp team">{esc(winner)}</div>
    <div class="mono stat">{stat_line(wt['id'])}</div>
  </div>
  <div class="seam"></div>
  <div class="panel r">
    {chip(fetch_logo(logo_of(lt), workdir, lt.get('abbreviation', 'l')), lt.get('abbreviation', ''))}
    <div class="mono role">{esc(role_r)}</div>
    <div class="disp score">{l_pts}</div>
    <div class="disp team">{esc(loser)}</div>
    <div class="mono stat">{stat_line(lt['id'])}</div>
  </div>
  {belt_svg(wt.get('abbreviation') or winner[:3].upper())}
  <div class="mono beltcap">{esc(capline)}</div>
</div>
<div class="tiles">{''.join(f'<div class="tile"><div class="disp v">{esc(v)}</div><div class="mono l">{esc(lab)}</div></div>' for v, lab in tiles[:3])}</div>
<div class="note"><b>{esc(nb)}</b> {esc(nr)}</div>
{FOOT}"""
    kind = "new-champion" if changed else "belt-defended"
    out = os.path.join(workdir, f"{lg}-{kind}-{fold(wshort)}-{w_pts}-{fold(lshort)}-{l_pts}-{gday}.jpg")
    bad = render(page(body, "result", {"l1": cl[0], "l2": cl[1], "lacc": cl[2], "r1": cr[0], "r2": cr[1]}), out)
    return {"kind": "result", "image": out, "caption": cap["caption"], "fit_problems": bad,
            "user_tags": tags_for(data, winner, loser, nets), "location_id": location(data, venue), "venue": venue,
            "alt_text": (f"{p.get('belt_name')}: {'new champion' if changed else 'belt defended'}. {winner} {w_pts}, "
                         f"{loser} {l_pts}, {short_date(gday)} at {venue}.")}


# ---------------------------------------------------------- GitHub / Graph --

def gh_repo():
    return os.environ.get("GITHUB_REPOSITORY") or "rjr5021/belt-holders"


def gh_token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        out = subprocess.run(["git", "config", "--get-regexp", r"http\..*\.extraheader"],
                             cwd=HERE, capture_output=True, text=True).stdout
        m = re.search(r"AUTHORIZATION:\s*basic\s+(\S+)", out, re.I)
        if m:
            return base64.b64decode(m.group(1)).decode().split(":", 1)[1]
    except Exception:  # noqa: BLE001
        pass
    return None


def gh_api(method, path, body=None):
    tok = gh_token()
    if not tok:
        raise RuntimeError("no GitHub token (not running in Actions?)")
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "beltholders-ig"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        raise RuntimeError(f"GitHub {method} {path}: {e.code} {e.read().decode()[:300]}")


def gh_put(rel, content, message):
    branch = os.environ.get("GITHUB_REF_NAME") or "main"
    p = f"/repos/{gh_repo()}/contents/{urllib.parse.quote(rel)}"
    for attempt in range(4):
        cur = gh_api("GET", f"{p}?ref={branch}")
        body = {"message": f"{message} [skip ci]", "branch": branch, "content": base64.b64encode(content).decode()}
        if cur and cur.get("sha"):
            body["sha"] = cur["sha"]
        try:
            return gh_api("PUT", p, body)["commit"]["sha"]
        except RuntimeError as e:
            if ("409" in str(e) or "422" in str(e)) and attempt < 3:
                time.sleep(3)
                continue
            raise


def host_image(local, rel_dir, message):
    rel = f"{rel_dir}/{os.path.basename(local)}"
    with open(local, "rb") as f:
        sha = gh_put(rel, f.read(), message)
    url = f"https://raw.githubusercontent.com/{gh_repo()}/{sha}/{rel}"
    for _ in range(12):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20) as r:
                if r.status == 200:
                    return url
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    return url


def graph(method, path, token, params=None):
    params = dict(params or {})
    params["access_token"] = token
    base = IG_GRAPH if token.startswith("IG") else FB_GRAPH
    data = urllib.parse.urlencode(params).encode()
    req = (urllib.request.Request(f"{base}{path}?{data.decode()}") if method == "GET"
           else urllib.request.Request(f"{base}{path}", data=data, method="POST"))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
        except Exception:  # noqa: BLE001
            err = {"message": str(e)}
        raise RuntimeError(f"{err.get('error_user_msg') or err.get('message') or e} "
                           f"(code {err.get('code')}, subcode {err.get('error_subcode')})")


def publish(token, ig_user, image_url, post):
    base = {"image_url": image_url, "caption": post["caption"]}
    extras = {}
    if post.get("alt_text"):
        extras["alt_text"] = post["alt_text"][:990]
    if post.get("user_tags"):
        extras["user_tags"] = json.dumps(post["user_tags"])
    if post.get("location_id"):
        extras["location_id"] = post["location_id"]
    attempts = [dict(extras)]
    for drop in ("location_id", "user_tags", "alt_text"):
        nxt = dict(attempts[-1])
        if drop in nxt:
            nxt.pop(drop)
            attempts.append(nxt)
    errors = []
    for extra in attempts:
        try:
            cid = graph("POST", f"/{ig_user}/media", token, {**base, **extra})["id"]
            for _ in range(30):
                st = graph("GET", f"/{cid}", token, {"fields": "status_code"}).get("status_code")
                if st == "FINISHED":
                    break
                if st == "ERROR":
                    raise RuntimeError("Instagram couldn't process the image")
                time.sleep(3)
            pub = graph("POST", f"/{ig_user}/media_publish", token, {"creation_id": cid})
            dropped = [k for k in extras if k not in extra]
            if dropped:
                summary(f"Instagram post went out without {', '.join(dropped)}: {errors}")
            try:
                link = graph("GET", f"/{pub['id']}", token, {"fields": "permalink"}).get("permalink")
            except Exception:  # noqa: BLE001
                link = None
            return pub["id"], link
        except RuntimeError as e:
            errors.append(str(e))
            print(f"  publish attempt failed: {e}")
            if "code 190" in str(e):
                break
    raise RuntimeError("; ".join(errors))


# ------------------------------------------------------------------- state --

def load_state():
    st = load_json(STATE, {}) or {}
    st.setdefault("previews", [])
    st.setdefault("results", [])
    st.setdefault("pending", {})
    st.setdefault("log", [])
    return st


def save_state(st, message):
    st["previews"] = st["previews"][-60:]
    st["results"] = st["results"][-60:]
    st["log"] = st["log"][-60:]
    text = json.dumps(st, indent=1, sort_keys=True) + "\n"
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        f.write(text)
    if LIVE:
        try:
            gh_put(STATE_REL, text.encode(), message)
        except Exception as e:  # noqa: BLE001
            print(f"  (couldn't push IG state: {e})")


def do_post(label, built):
    print(f"\n--- {label} ---\n{built['caption']}\n"
          f"tags: {[t['username'] for t in built['user_tags']]}  location: {built['venue']} -> {built['location_id']}")
    if built["fit_problems"]:
        print(f"  !! layout: {built['fit_problems']}")
    if built["venue"] and not built["location_id"]:
        summary(f"No Instagram location ID for **{built['venue']}** -- add it to ig_data.json.")
    if not LIVE:
        print(f"  (not live -- not posted; image {built['image']})")
        return None
    url = host_image(built["image"], IMAGES_REL, f"IG card: {os.path.basename(built['image'])}")
    mid, link = publish(os.environ["IG_ACCESS_TOKEN"].strip(), os.environ["IG_BUSINESS_ACCOUNT_ID"].strip(), url, built)
    print(f"  POSTED {label}: {link or mid}")
    summary(f"Posted to Instagram: {label} {link or mid}")
    return link or mid


# --------------------------------------------------------------------- run --

def pending_record(lg, belt):
    """What we need to post the result later -- captured before the game, while
    network.json still shows the holder going in. One ESPN call."""
    nx = belt["next"]
    gday = d(nx["date"])
    ev = espn_scoreboard_event(lg, gday, belt["holder"], nx["opponent"])
    if not ev:
        raise RuntimeError(f"no ESPN event for {belt['holder']} vs {nx['opponent']} on {gday}")
    try:
        games = site_games(lg)
        game_no = games[-1]["n"] + 1 if games else None
    except Exception:  # noqa: BLE001
        game_no = None
    return {"lg": lg, "date": gday.isoformat(), "holder": belt["holder"], "holder_short": belt.get("holder_short") or "",
            "opponent": nx["opponent"], "opponent_short": nx.get("opponent_short") or "", "espn_id": ev["id"],
            "since": belt["since"], "defenses": int(belt.get("defenses") or 0), "reign_no": int(belt.get("reign_no") or 1),
            "game_no": game_no, "belt_name": belt.get("name")}


def one_pass(workdir):
    if not LIVE and not DRY:
        print("Instagram: IG secrets not set (or IG_LIVE=0) -- nothing to do. Run with IG_DRY_RUN=1 to test.")
        return
    st = load_state()
    n = now_et()
    today = n.date()
    for lg in LEAGUES:
        try:
            belt = network_belt(lg)
        except Exception as e:  # noqa: BLE001
            print(f"{lg}: no network data ({e})")
            continue
        nx = belt.get("next") or {}
        if belt.get("ok") and nx.get("date") == today.isoformat() and nx.get("opponent"):
            key = f"{lg}|{belt['holder']}|{nx['opponent']}|{nx['date']}"
            if key not in st["pending"] and key not in st["results"]:
                try:
                    st["pending"][key] = pending_record(lg, belt)
                    save_state(st, f"IG: {lg} belt game today")
                except Exception as e:  # noqa: BLE001
                    print(f"{lg}: couldn't record today's game ({e})")
            # --- preview: game day, from 10 AM until an hour before the game
            start = None
            if nx.get("time_et"):
                hh, mm = (int(x) for x in nx["time_et"].split(":")[:2])
                start = datetime(today.year, today.month, today.day, hh, mm, tzinfo=ET)
            due = n.hour >= PREVIEW_FROM_HOUR and (start is None or n <= start - PREVIEW_UNTIL_BEFORE)
            if due and key not in st["previews"]:
                try:
                    built = build_preview(lg, belt, workdir)
                    res = do_post(f"{lg} preview", built)
                    if LIVE and res:
                        st["previews"].append(key)
                        st["log"].append(f"{n:%Y-%m-%d %H:%M} preview {key} {res}")
                        save_state(st, f"IG: {lg} preview posted")
                except Exception as e:  # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    print(f"{lg} preview failed (not fatal; retried next run): {e}")
                    summary(f"Instagram {lg} preview failed: {e}")
        # --- results for any recorded game that has gone final
        for key, p in list(st["pending"].items()):
            if p.get("lg") != lg or key in st["results"]:
                continue
            if (today - d(p["date"])).days > 2:
                st["pending"].pop(key, None)
                save_state(st, f"IG: {lg} drop stale game")
                continue
            try:
                summ = espn_summary(lg, p["espn_id"])
                typ = (comp_of(summ).get("status") or {}).get("type") or {}
                if not typ.get("completed"):
                    print(f"{key}: not final yet ({typ.get('detail')})")
                    continue
                built = build_result(p, workdir, summ)
                res = do_post(f"{lg} result", built)
                if LIVE and res:
                    st["results"].append(key)
                    st["pending"].pop(key, None)
                    st["log"].append(f"{n:%Y-%m-%d %H:%M} result {key} {res}")
                    save_state(st, f"IG: {lg} result posted")
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"{key} result failed (not fatal; retried next run): {e}")
                summary(f"Instagram {lg} result failed: {e}")


def check(workdir):
    tok = (os.environ.get("IG_ACCESS_TOKEN") or "").strip()
    uid = (os.environ.get("IG_BUSINESS_ACCOUNT_ID") or "").strip()
    if tok:
        try:
            me = graph("GET", "/me", tok, {"fields": "user_id,username"})
            print(f"Instagram token OK: posts as @{me.get('username')}")
            summary(f"Instagram token OK: posts as @{me.get('username')}")
            if uid and str(me.get("user_id") or me.get("id")) != uid:
                summary(f"IG_BUSINESS_ACCOUNT_ID doesn't match the token's account ({me.get('user_id') or me.get('id')}).")
        except RuntimeError as e:
            print(f"!! token check failed: {e}")
            summary(f"Instagram token check failed: {e}")
    else:
        summary("No IG_ACCESS_TOKEN secret yet.")
    for lg in LEAGUES:
        samples = []
        belt = {}
        try:
            belt = network_belt(lg)
            if (belt.get("next") or {}).get("date"):
                samples.append(("preview", build_preview(lg, belt, workdir)))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            summary(f"{lg} sample preview failed: {e}")
        try:   # the belt's last game, as a result card
            g = site_games(lg)[-1]
            ev = espn_scoreboard_event(lg, d(g["date"]), g["holder_name"], g["opponent_name"])
            reigns = site_reigns(lg)
            r = next(x for x in reversed(reigns) if fold(x.get("name")) == fold(g["holder_name"]) and d(x["start_date"]) <= d(g["date"]))
            p = {"lg": lg, "date": g["date"], "holder": g["holder_name"], "holder_short": "", "opponent": g["opponent_name"],
                 "opponent_short": "", "espn_id": ev["id"], "since": r["start_date"],
                 "defenses": sum(1 for x in site_games(lg) if x.get("holder_name") == g["holder_name"]
                                 and d(r["start_date"]) < d(x["date"]) < d(g["date"]) and str(x.get("outcome", "")).startswith("retained")),
                 "reign_no": r.get("reign_no"), "game_no": g.get("n"), "belt_name": belt.get("name")}
            samples.append(("result", build_result(p, workdir)))
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            summary(f"{lg} sample result failed: {e}")
        for kind, b in samples:
            print(f"\n=== {lg} sample {kind} ===\n{b['caption']}\ntags {b['user_tags']}\nlocation {b['venue']} -> {b['location_id']}\nlayout {b['fit_problems'] or 'ok'}")
            if DRY or not gh_token():
                continue
            fixed = os.path.join(workdir, f"sample-{lg}-{kind}.jpg")
            os.replace(b["image"], fixed)
            try:
                url = host_image(fixed, CHECK_REL, f"IG check: sample {lg} {kind}")
                gh_put(f"{CHECK_REL}/sample-{lg}-{kind}.txt",
                       (f"{b['caption']}\n\n---\ntags: {b['user_tags']}\nlocation: {b['venue']} -> {b['location_id']}\n"
                        f"alt: {b['alt_text']}\nlayout: {b['fit_problems'] or 'ok'}\n").encode(), f"IG check: {lg} {kind} caption")
                summary(f"Sample {lg} {kind}: {url}")
                if tok and uid:
                    params = {"image_url": url, "caption": b["caption"], "alt_text": b["alt_text"][:990]}
                    if b["user_tags"]:
                        params["user_tags"] = json.dumps(b["user_tags"])
                    if b["location_id"]:
                        params["location_id"] = b["location_id"]
                    try:
                        cid = graph("POST", f"/{uid}/media", tok, params)["id"]
                        summary(f"Instagram accepted the sample {lg} {kind} with tags + location (container {cid}, not published).")
                    except RuntimeError as e:
                        summary(f"Instagram rejected the sample {lg} {kind}: {e}")
            except Exception as e:  # noqa: BLE001
                print(f"(couldn't publish the sample: {e})")


def main():
    workdir = tempfile.mkdtemp(prefix="ig-")
    if "--check" in sys.argv:
        check(workdir)
        return
    if not LIVE:
        print("Instagram: not live (no IG secrets, IG_LIVE!=1 or IG_DRY_RUN=1) -- building and printing only.")
    one_pass(workdir)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 -- never fail the job over Instagram
        import traceback
        traceback.print_exc()
        print(f"Instagram step failed (not fatal): {e}")
