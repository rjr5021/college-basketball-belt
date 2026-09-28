#!/usr/bin/env python3
"""
Build the static collegebasketballbelt.com site from data/lineage.json.

    python3 build_lineage.py && python3 build_site.py

Pages: /  /history/  /records/  /teams/  /teams/<slug>/  /march/
       /rules/  /about/  /privacy/  /404.html  /feed.xml  /sitemap.xml
"""

import html
import json
import os
import re
import shutil
import unicodedata
import urllib.request
from datetime import date, datetime

SITE_URL = "https://collegebasketballbelt.com"
DOMAIN = "collegebasketballbelt.com"
OUT = "site"
ADSENSE_PUBLISHER_ID = ""        # "pub-3317069252410560" once the site is approved in AdSense
GOATCOUNTER_CODE = ""            # e.g. "collegebasketballbelt" once the GoatCounter site exists
STYLES_VERSION = "4"
ORANGE = "#de762c"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
e = html.escape


# ------------------------------------------------------------- helpers ---

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def d_short(iso, year=False):
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{MONTHS[m-1]} {d}" + (f", {y}" if year else "")


def d_long(iso):
    y, m, d = (int(x) for x in iso[:10].split("-"))
    return f"{MONTHS_LONG[m-1]} {d}, {y}"


def weekday(iso):
    return WEEKDAYS[date.fromisoformat(iso[:10]).weekday()]


def tip_12h(hhmm):
    if not hhmm:
        return "Time TBA"
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'} ET"


def season_label(s):
    return f"{s - 1}–{str(s)[2:]}"


def fit(name):
    return f"--fit:{max(len(w) for w in name.split())}"


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def plural(n, word, pl=None):
    return f"{n:,} {word if n == 1 else (pl or word + 's')}"


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


def darken(hexc, f=0.72):
    h = hexc.lstrip("#")
    r, g, b = (int(int(h[i:i + 2], 16) * f) for i in (0, 2, 4))
    return f"#{r:02x}{g:02x}{b:02x}"


def plate(primary, secondary):
    top, bottom = primary, darken(primary)
    ink = "#ffffff" if contrast("#ffffff", bottom) >= contrast("#111111", top) else "#111111"
    accent = secondary if secondary and min(contrast(secondary, top), contrast(secondary, bottom)) >= 3 else (
        "#f0c65a" if ink == "#ffffff" and min(contrast("#f0c65a", top), contrast("#f0c65a", bottom)) >= 3 else ink)
    return top, bottom, ink, accent


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def score_text(score):
    hp, ap = (int(x) for x in score.split("-"))
    return f"{max(hp, ap)}–{min(hp, ap)}"


kickoff_12h = tip_12h


def won_score_text(r):
    return score_text(r["won_score"]) if r.get("won_score") else ""


SUBNAV = [("current", "/", "Current"), ("next", "/next/", "Next defense"), ("outlook", "/outlook/", "Outlook"), ("history", "/history/", "Full history"),
          ("seasons", "/seasons/", "Seasons"), ("records", "/records/", "Records"), ("teams", "/teams/", "Teams"),
          ("rivalries", "/rivalries/", "Rivalries"), ("compare", "/compare/", "Compare"), ("march", "/march/", "March"),
          ("stories", "/stories/", "Stories"), ("more", "/more/", "More")]


def subnav(lg=None, on=None):
    links = "".join(f'<a href="{h}"{" class=on" if k == on else ""}>{t}</a>' for k, h, t in SUBNAV)
    return f'<nav class="subnav mono" aria-label="Belt sections">{links}</nav>'


# ----------------------------------------------------------- data access --

D = {}


def team(tid):
    return D["teams"].get(str(tid), {"name": str(tid), "primary": "#5b5140", "secondary": "#cfc4ad", "mascot": str(tid)})


def tname(tid):
    return team(tid)["name"]


def tcolor(tid):
    t = team(tid)
    return t["primary"], t.get("secondary")


def team_url(tid):
    return f"/teams/{slug(tname(tid))}/"


def how_won(r, short=False):
    if r.get("seed"):
        return "1949 NCAA champion" if short else "Won the 1949 NCAA final over Oklahoma A&M, 46–36"
    if r.get("won_from"):
        return f"Beat {e(r.get('won_from_name') or tname(r['won_from']))} {score_text(r['won_score'])}"
    if r.get("reclaimed_after"):
        return "Reclaimed after the holder left Division I"
    return ""


# ------------------------------------------------------------- chrome ----

LOGO = ('<svg width="40" height="24" viewBox="0 0 40 24" fill="none" aria-hidden="true">'
        '<rect x="0" y="9" width="40" height="6" fill="#a97f38"/>'
        '<rect x="3" y="6" width="7" height="12" fill="#a97f38" stroke="#211a12" stroke-width="1.2"/>'
        '<rect x="30" y="6" width="7" height="12" fill="#a97f38" stroke="#211a12" stroke-width="1.2"/>'
        '<path d="M15 1 H25 L28 4 V20 L25 23 H15 L12 20 V4 Z" fill="#211a12" stroke="#a97f38" stroke-width="2"/>'
        '<circle cx="20" cy="12" r="5" fill="#de762c"/><path d="M15 12 H25 M20 7 V17" stroke="#211a12" stroke-width="1"/></svg>')

NAV = [("belt", "/", "The Belt"), ("history", "/history/", "History"), ("records", "/records/", "Records"),
       ("teams", "/teams/", "Teams"), ("march", "/march/", "March"), ("rules", "/rules/", "Rules")]


def page(title, body, *, path, description, active=None, jsonld=None):
    nav = "".join(f'<a href="{h}"{" class=on" if k == active else ""}>{t}</a>' for k, h, t in NAV)
    canonical = SITE_URL + path
    ads = (f'<meta name="google-adsense-account" content="ca-{ADSENSE_PUBLISHER_ID}">'
           f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-{ADSENSE_PUBLISHER_ID}" crossorigin="anonymous"></script>'
           if ADSENSE_PUBLISHER_ID else "")
    goat = (f'<script data-goatcounter="https://{GOATCOUNTER_CODE}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>'
            if GOATCOUNTER_CODE else "")
    ld = f'<script type="application/ld+json">{json.dumps(jsonld)}</script>' if jsonld else ""
    full_title = title if "College Basketball Belt" in title else f"{title} · The College Basketball Belt"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="The College Basketball Belt">
<meta property="og:title" content="{e(full_title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@CollegeBBBelt">
<link rel="icon" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="College Basketball Belt — title changes" href="/feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;800;900&family=Spectral:ital,wght@0,400;0,500;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/styles.css?v={STYLES_VERSION}">
<script>try{{var t=localStorage.getItem('belt-theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
{ads}{goat}{ld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="/">{LOGO}<span>The College Basketball Belt</span></a>
  <nav class="primary mono" aria-label="Sections">{nav}</nav>
  <div class="topright"><button class="themebtn" type="button" aria-label="Toggle dark mode" onclick="var r=document.documentElement,d=r.dataset.theme==='dark'||(!r.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);r.dataset.theme=d?'light':'dark';try{{localStorage.setItem('belt-theme',r.dataset.theme);}}catch(e){{}}"><svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z"/></svg></button><a class="searchlink" href="/search/" aria-label="Search"><svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="7" cy="7" r="5"/><path d="M11 11 L15 15"/></svg></a><a class="pill mono" href="#alerts">Get belt alerts</a></div>
</header>
<main id="main">
{body}
</main>
{alerts_block()}
<footer class="foot mono">
  <div class="links"><a href="https://collegefootballbelt.com">collegefootballbelt.com</a><a href="https://beltholders.com">beltholders.com</a><a href="https://x.com/CollegeBBBelt">@CollegeBBBelt</a><a href="https://instagram.com/CollegeBBBelt">Instagram</a></div>
  <div class="links"><a href="/privacy/">Privacy</a><a href="/about/">About</a><a href="mailto:hello@collegebasketballbelt.com">Contact</a><a href="/feed.xml">RSS</a><a href="/embed/">Embed a badge</a><span>Not affiliated with the NCAA or any school.</span></div>
</footer>
</body>
</html>
"""


def alerts_block():
    return f"""<section id="alerts" class="alerts">
  <div>
    <h2 class="disp">Get an email when the belt moves</h2>
    <p>One email per title change. Pairs with the football alerts, or on its own.</p>
  </div>
  <form class="alert-form" action="https://blogtrottr.com" method="post" target="_blank">
    <input type="hidden" name="lang" value="en_US">
    <input type="hidden" name="btr_url" value="{SITE_URL}/feed.xml">
    <input type="hidden" name="schedule_type" value="0">
    <label for="alert-email" class="sr">Email address</label>
    <input id="alert-email" type="email" name="btr_email" placeholder="you@example.com" required>
    <button type="submit" class="mono">Sign me up</button>
  </form>
</section>"""


# ------------------------------------------------------------- pieces ----

def holder_plate(d):
    cur = d["current"]
    p, s = tcolor(cur["team"])
    top, bottom, ink, accent = plate(p, s)
    if cur.get("seed"):
        lede = "Picked up the belt as the 1949 national champions."
    elif cur.get("won_from"):
        lede = (f"Took the belt from {e(cur['won_from_name'])}, {score_text(cur['won_score'])}, "
                f"on {d_long(cur['start_date'])}.")
    else:
        lede = f"Holding since {d_long(cur['start_date'])}."
    last = d["march"][-1] if d["march"] else None
    if last and last["champion_team"] == cur["team"] and last["end_holder"] == cur["name"] and cur["start_date"][:4] == str(last["season"]):
        lede += f" Then won the {last['season']} national title with it."
    ng = d.get("next_game")
    box = ""
    if ng:
        prob = (d.get("preview") or {}).get("holder_win_prob")
        first = "First defense" if cur.get("defenses", 0) == 0 else "Next defense"
        lede += f" {first} {weekday(ng['date'])}, {d_short(ng['date'])}."
        where = "vs." if ng["holder_home"] or ng["neutral"] else "at"
        cp, _ = tcolor(ng["challenger"])
        place = ", ".join(x for x in (ng.get("venue"), ng.get("city")) if x)
        box = f"""<aside class="upnext">
      <div class="kicker">Up next · title defense</div>
      <div class="matchup">
        <div><i style="background:{s or accent}"></i><b class="disp">{e(team(cur['team'])['name'])}</b><small>Holder</small></div>
        <span class="disp at">{where}</span>
        <div class="r"><i style="background:{cp}"></i><b class="disp">{e(ng['challenger_name'])}</b><small>Challenger</small></div>
      </div>
      <div class="meta mono"><span>{weekday(ng['date'])} {d_short(ng['date'])} · {tip_12h(ng.get('kickoff'))}</span></div>
      {f'<div class="meta mono"><span>{e(place)}</span></div>' if place else ''}
      {f'<div class="meta mono"><span>Chance to defend: {round(prob * 100)}%</span><a href="/outlook/">Belt tree →</a></div>' if prob is not None else ""}
      <a class="mono prevlink" href="/next/">Game preview →</a>
    </aside>"""
    days = cur["days"]
    return f"""<section class="plate" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="plate-grid">
    <div class="plate-main">
      <div class="kicker dot">Current holder · {ordinal(cur['reign_no'])} reign</div>
      <h1 class="disp holder" style="{fit(cur['name'])}">{e(cur['name'])}</h1>
      <p class="lede">{lede}</p>
      <div class="stats">
        <div><b class="disp">{days:,}</b><span class="mono">{"Day" if days == 1 else "Days"} held</span></div>
        <div><b class="disp">{cur.get('defenses', 0)}</b><span class="mono">{"Defense" if cur.get('defenses', 0) == 1 else "Defenses"}</span></div>
        <div><b class="disp">{cur['reign_no']}</b><span class="mono">Reigns all-time</span></div>
      </div>
    </div>
    {box}
  </div>
</section>"""


def chain_rows(reigns, n=8):
    rows = []
    for r in list(reversed(reigns))[:n]:
        p, _ = tcolor(r["team"])
        if r.get("end_date"):
            same = r["start_date"][:4] == r["end_date"][:4]
            span = f"{d_short(r['start_date'])} – {d_short(r['end_date'])}, {r['end_date'][:4]}" if same else f"{d_short(r['start_date'], True)} – {d_short(r['end_date'], True)}"
            tail = f"{plural(r['days'], 'day')} · {r.get('defenses', 0)} def."
        else:
            span, tail = f"{d_short(r['start_date'], True)} –", "Holding"
        rows.append(f'<li><i style="background:{p}"></i><div><a class="disp" href="{team_url(r["team"])}">{e(r["name"])}</a><small>{how_won(r)}</small></div><span class="mono when">{span}</span><span class="mono tail">{tail}</span></li>')
    return f'<ol class="chain">{"".join(rows)}</ol>'


def record_card(title, rows):
    lis = "".join(f'<li><span>{i}. {e(name)}</span><b class="mono">{val}</b></li>' for i, (name, val) in enumerate(rows, 1))
    return f'<div class="card"><div class="kicker">{e(title)}</div><ol class="lb">{lis}</ol></div>'


def march_result(m):
    if not m["entering"]:
        return "—"
    if not m["lost_round"]:
        return "Kept it all the way: national champions" if m["entering"] == m["champion"] else "Kept it through the postseason"
    if not m["in_field"]:
        return f"Missed the NCAA field; lost it to {e(m['lost_to'])} ({e(m['lost_round'])})"
    return f"Lost it in the {e(m['lost_round'].lower() if m['lost_round'] not in ('Sweet 16', 'Elite Eight', 'Final Four', 'First Four') else m['lost_round'])} to {e(m['lost_to'])}"


def football_card():
    try:
        with urllib.request.urlopen("https://collegefootballbelt.com/api/current.json", timeout=20) as r:
            j = json.loads(r.read().decode())
        holder = j["holder"]
        ng = j.get("next_game") or {}
        line = ""
        if ng.get("opponent"):
            where = "vs." if ng.get("is_home") or ng.get("neutral") else "at"
            line = f"{where.capitalize()} {e(ng['opponent'])}, {weekday(ng['date'])} {d_short(ng['date'])}. On collegefootballbelt.com →"
        else:
            line = "On collegefootballbelt.com →"
        return (f'<a class="card sister" href="https://collegefootballbelt.com"><div class="kicker">Sister belt · football</div>'
                f'<div class="disp big">{e(holder)} holds the football belt</div><p>{line}</p></a>')
    except Exception:
        return ('<a class="card sister" href="https://collegefootballbelt.com"><div class="kicker">Sister belt · football</div>'
                '<div class="disp big">The College Football Belt</div><p>The same idea, since 1869. On collegefootballbelt.com →</p></a>')


# ------------------------------------------------------------- pages -----

def build_home(d):
    rec = d["records"]
    months = d["months"]
    peak = max((n for _, n in months), default=0) or 1
    bars = "".join(f'<div class="bar{" now" if i == len(months) - 1 else ""}" style="height:{max(4, round(100 * n / peak))}%" title="{MONTHS[m-1]}: {n}"></div>' for i, (m, n) in enumerate(months))
    labels = "".join(f"<span>{MONTHS[m-1]}</span>" for m, _ in months)
    total_last = sum(n for _, n in months)
    last = d["march"][-1] if d["march"] else None
    bracket = ""
    if last:
        lost = last["lost_round"] or "Never"
        bracket = f"""<section class="bracket wrap-out">
  <div>
    <div class="kicker">March</div>
    <h2 class="disp">The belt versus the bracket</h2>
    <p>If the holder makes the NCAA tournament, the belt is guaranteed to finish with the national champion: whoever takes it keeps playing until someone knocks them out, and only the champion is never knocked out. If the holder misses the field, the belt can spend March at the NIT.</p>
    <a class="mono more" href="/march/">Every March since 1950 →</a>
  </div>
  <div class="bgrid">
    <div><span class="mono">Entered March {last['season']} with it</span><b class="disp">{e(last['entering'] or '—')}</b></div>
    <div><span class="mono">Lost it in</span><b class="disp">{e(lost)}</b></div>
    <div><span class="mono">Hands in the tournament</span><b class="disp">{last['changes_after_start']}</b></div>
    <div class="hot"><span class="mono">Crowned in April</span><b class="disp">{e(last['champion'])}</b></div>
  </div>
</section>"""
    import features, cbb_league
    body = f"""{subnav(None, "current")}
{features.live_box(cbb_league.LEAGUE, d)}
{holder_plate(d)}
<section class="wrap split">
  <div>
    <div class="head"><h2 class="disp">Chain of custody</h2><a class="mono more" href="/history/">All {len(d['reigns']):,} reigns →</a></div>
    {chain_rows(d['reigns'], 6)}
  </div>
  <div class="card pace">
    <div class="kicker">How fast it moves</div>
    <div class="disp big">Thirty-plus games a year. The belt rarely sits still.</div>
    <p>Football's belt can sit with one team for a season. In hoops, a Tuesday road trip in January can end a reign. In {d['last_season_label']} it changed hands {plural(total_last, 'time')}.</p>
    <div class="bars">{bars}</div>
    <div class="mono barlabels">{labels}</div>
    <div class="mono note">Title changes per month, {d['last_season_label']}</div>
  </div>
</section>
{bracket}
<section class="wrap block three">
  {record_card("Most reigns", [(tname(t), v) for t, v in rec['most_reigns'][:3]])}
  {record_card("Most defenses in one reign", [(f"{r['name']}, {season_label(r['season']) if r['season'] > 1949 else '1949'}", f"{r['defenses']} def.") for r in rec['longest_reigns'][:3]])}
  {football_card()}
</section>
{home_extras()}"""
    cur = d["current"]
    ld = {"@context": "https://schema.org", "@type": "SportsTeam", "name": cur["name"], "sport": "Basketball",
          "award": f"The College Basketball Belt (lineal), {ordinal(cur['reign_no'])} reign since {cur['start_date']}"}
    write("index.html", page(f"The College Basketball Belt: {cur['name']} holds it", body, path="/", active="belt",
                             description=f"{cur['name']} holds the College Basketball Belt, the lineal championship of men's college basketball: beat the holder, take the belt. Every game since 1949–50.",
                             jsonld=ld))


def reign_link(r):
    import site_extras
    from cbb_league import LEAGUE
    D.setdefault("_bg", {bg["n"]: bg for bg in D["belt_games"]})
    return site_extras.reign_url(LEAGUE, D, r)


def home_extras():
    import site_extras
    from cbb_league import LEAGUE
    today = date.today()
    items = site_extras.otd_items({"cbb": D}).get(f"{today:%m-%d}", [])
    otd = (f'<section class="wrap block"><div class="head"><h2 class="disp">Today in belt history</h2><a class="mono more" href="/on-this-day/">All of {MONTHS_LONG[today.month - 1]} {today.day} →</a></div>'
           f'{site_extras.otd_list(items, 6)}</section>') if items else ""
    cards = "".join(f'<a class="storycard" href="/stories/{sl_}/"><b class="disp">{e(t)}</b></a>' for sl_, t in [
        ("longest-reigns", "The longest reigns"), ("droughts", "The longest droughts"),
        ("wildest-seasons", "The wildest seasons"), ("rivalries", "The rivalries that decided it")])
    return otd + f'<section class="wrap block"><div class="head"><h2 class="disp">Stories</h2><a class="mono more" href="/stories/">All stories →</a></div><div class="storygrid">{cards}</div></section>'


def build_history(d):
    rows, last_dec = [], None
    for r in reversed(d["reigns"]):
        dec = int(r["start_date"][:3] + "0")
        if dec != last_dec:
            rows.append(f'<tr class="dec" id="d{dec}"><th colspan="5" class="disp">{dec}s</th></tr>')
            last_dec = dec
        p, _ = tcolor(r["team"])
        rows.append(f"""<tr><td class="mono n"><a href="{reign_link(r)}">{r['index']}</a></td><td><i style="background:{p}"></i><a href="{team_url(r['team'])}">{e(r['name'])}</a><small>{how_won(r, True).lower() if r.get('seed') else how_won(r).replace('Beat', 'beat', 1)}</small></td>
<td class="mono">{d_short(r['start_date'], True)}</td><td class="mono">{d_short(r['end_date'], True) if r.get('end_date') else 'Holding'}</td><td class="mono r">{r.get('defenses', 0)} · {r['days']:,}d</td></tr>""")
    decades = sorted({int(r["start_date"][:3] + "0") for r in d["reigns"]}, reverse=True)
    body = f"""{subnav(None, "history")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Every reign</h1><span class="mono note">{len(d['reigns']):,} reigns · {d['records']['belt_games']:,} belt games since 1949–50</span></div>
  <nav class="jump mono" aria-label="Jump to decade">{"".join(f'<a href="#d{x}">{x}s</a>' for x in decades)}</nav>
  <div class="tablewrap"><table class="history">
    <thead><tr><th class="mono">#</th><th class="mono">Holder</th><th class="mono">Won</th><th class="mono">Lost</th><th class="mono r">Def. · days</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
</section>"""
    write("history/index.html", page("Every College Basketball Belt reign since 1949–50", body, path="/history/", active="history",
                                     description=f"The complete lineal college basketball championship: all {len(d['reigns']):,} reigns since the 1949–50 season."))


def build_records(d):
    rec = d["records"]
    cards = "".join([
        record_card("Most days holding the belt (all reigns)", [(tname(t), f"{v:,}") for t, v in rec["most_days"]]),
        record_card("Most reigns", [(tname(t), v) for t, v in rec["most_reigns"]]),
        record_card("Most defenses in one reign", [(f"{r['name']}, {season_label(r['season']) if r['season'] > 1949 else '1949'}", r["defenses"]) for r in rec["longest_reigns"]]),
        record_card("Most successful defenses (all reigns)", [(tname(t), v) for t, v in rec["most_defenses_total"]]),
        record_card("Most defenses in one season", [(f"{tname(x['team'])}, {season_label(x['season'])}", x["defenses"]) for x in rec.get("most_defenses_season", [])]),
        record_card("Most belt games played", [(tname(t), f"{v:,}") for t, v in rec.get("most_belt_games", [])]),
        record_card("Busiest seasons (title changes)", [(season_label(s_), v) for s_, v in rec.get("busiest_seasons", [])]),
        record_card("Longest waits since last holding it", [(tname(x["team"]), f"{x['days']:,} days") for x in rec.get("droughts", [])]),
        record_card("Most title takeovers from one team", [(f"{tname(x['winner'])} from {tname(x['loser'])}", x["times"]) for x in rec.get("top_takeovers", [])]),
    ])
    body = f"""{subnav(None, "records")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Belt records</h1><span class="mono note">Through {d_long(d['generated'])}</span></div>
  <div class="numbers">
    <div><b class="disp">{len(d['reigns']):,}</b><span class="mono">Reigns</span></div>
    <div><b class="disp">{rec['belt_games']:,}</b><span class="mono">Belt games</span></div>
    <div><b class="disp">{rec['programs']}</b><span class="mono">Programs have held it</span></div>
    <div><b class="disp">{rec['ncaa_changes']}</b><span class="mono">Title changes in the NCAA tournament</span></div>
  </div>
  <p class="intro">{len(rec.get("never_held", []))} current Division I programs have never held the belt.</p>
  <div class="cards4">{cards}</div>
</section>"""
    write("records/index.html", page("College Basketball Belt records", body, path="/records/", active="records",
                                     description="Lineal college basketball championship records: most days held, most reigns, longest reigns."))


def build_teams(d):
    by = {}
    for r in d["reigns"]:
        by.setdefault(r["team"], []).append(r)
    cards = []
    for tid, rs in sorted(by.items(), key=lambda kv: -sum(r["days"] for r in kv[1])):
        p, _ = tcolor(tid)
        days = sum(r["days"] for r in rs)
        cards.append(f'<a class="teamcard" href="{team_url(tid)}"><i style="background:{p}"></i><b class="disp">{e(tname(tid))}</b><span class="mono">{plural(len(rs), "reign")} · {days:,} days · last {rs[-1]["start_date"][:4]}</span></a>')
        build_team(d, tid, rs)
    body = f"""{subnav(None, "teams")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Every program that has held the belt</h1><span class="mono note">{len(by)} programs · sorted by days held</span></div>
  <div class="teamgrid">{"".join(cards)}</div>
</section>"""
    write("teams/index.html", page("Every team that has held the College Basketball Belt", body, path="/teams/", active="teams",
                                   description="Every program that has held the lineal college basketball championship belt since 1949–50."))


def build_team(d, tid, rs):
    name = tname(tid)
    p, s = tcolor(tid)
    top, bottom, ink, accent = plate(p, s)
    days = sum(r["days"] for r in rs)
    defs = sum(r.get("defenses", 0) for r in rs)
    holding = rs[-1].get("end_date") is None
    rows = "".join(
        f"""<li><i style="background:{p}"></i><div><span class="disp">{ordinal(r['reign_no'])} reign</span><small>{how_won(r)}{(' · lost to ' + e(r['lost_to_name'])) if r.get('lost_to_name') else ''}</small></div><span class="mono when">{d_short(r['start_date'], True)} – {d_short(r['end_date'], True) if r.get('end_date') else 'now'}</span><span class="mono tail">{plural(r['days'], 'day')} · {r.get('defenses', 0)} def.</span></li>"""
        for r in reversed(rs))
    body = f"""<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">{'Current holder' if holding else 'The College Basketball Belt'}</div>
    <h1 class="disp holder" style="{fit(name)}">{e(name)}</h1>
    <div class="stats"><div><b class="disp">{len(rs)}</b><span class="mono">Reigns</span></div><div><b class="disp">{days:,}</b><span class="mono">Days held</span></div><div><b class="disp">{defs}</b><span class="mono">Defenses</span></div><div><b class="disp">{rs[0]['start_date'][:4]}</b><span class="mono">First reign</span></div></div>
  </div>
</section>
<section class="wrap block"><div class="head"><h2 class="disp">Every reign</h2></div><ol class="chain">{rows}</ol></section>
{team_extras_html(tid)}"""
    write(f"teams/{slug(name)}/index.html", page(f"{name} and the College Basketball Belt", body, path=team_url(tid), active="teams",
                                                  description=f"{name}: {plural(len(rs), 'reign')} with the lineal college basketball championship belt, {days:,} days held."))


def team_extras_html(tid):
    import site_extras
    from cbb_league import LEAGUE
    D.setdefault("_bg", {bg["n"]: bg for bg in D["belt_games"]})
    return site_extras.team_extras(LEAGUE, D, tid)


def build_march(d):
    rows = []
    for m in reversed(d["march"]):
        rows.append(f"""<tr><td class="mono">{m['label']}</td><td>{e(m['entering'] or '—')}{'' if m['in_field'] or not m['entering'] else '<small>not in the NCAA field</small>'}</td><td>{march_result(m)}</td><td>{e(m['champion'])}</td><td class="mono r">{m['changes_after_start']}</td></tr>""")
    kept = sum(1 for m in d["march"] if m["entering"] and m["entering"] == m["champion"])
    missed = sum(1 for m in d["march"] if m["entering"] and not m["in_field"])
    body = f"""{subnav(None, "march")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt versus the bracket</h1><span class="mono note">Every NCAA tournament since 1950</span></div>
  <p class="intro">Who carried the belt into each NCAA tournament, and how it ended. {plural(kept, 'holder')} took the belt into March and kept it all the way to the title; {plural(missed, 'time')} the holder wasn't in the NCAA field at all.</p>
  <div class="tablewrap"><table class="history march">
    <thead><tr><th class="mono">Season</th><th class="mono">Entered March with it</th><th class="mono">What happened</th><th class="mono">NCAA champion</th><th class="mono r">Changes</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
</section>"""
    write("march/index.html", page("The belt versus the bracket: every March since 1950", body, path="/march/", active="march",
                                   description="Who carried the College Basketball Belt into every NCAA tournament since 1950, and whether it survived March."))


def build_static(d):
    rules = f"""<section class="wrap prose">
<div class="kicker">The ruleset</div>
<h1 class="disp">How the belt works</h1>
<p>A lineal championship works like a boxing title: to become the champion, you have to beat the champion. The College Basketball Belt is one title, passed from team to team, game by game, for more than seventy-five years.</p>
<h2 class="disp">The rules</h2>
<ol>
<li><b>Where it starts.</b> Our game-by-game record begins with the 1949–50 season, so the belt starts with the reigning national champion: Kentucky, who beat Oklahoma A&amp;M 46–36 in the 1949 NCAA final.</li>
<li><b>Beat the holder, take the belt.</b> Every game counts: regular season, conference tournaments, the NCAA tournament, the NIT and the other postseason events. Home, away or neutral.</li>
<li><b>Division I only.</b> Both teams have to be in Division I that season (the major-college level before 1973). A holder that loses to a non-Division I team keeps the belt, and those games aren't title defenses.</li>
<li><b>No ties.</b> Basketball plays overtime until someone wins, so every belt game has a winner.</li>
<li><b>If a holder leaves Division I,</b> the belt goes back to the most recent earlier holder that is still playing, the same rule the College Football Belt uses. {"It hasn't happened yet." if not d["vacancies"] else f"It has happened {plural(len(d['vacancies']), 'time')}."}</li>
</ol>
<h2 class="disp">Sources</h2>
<p>Results come from CollegeBasketballData.com and are updated automatically every few hours during the season. Spot a missing or wrong game? Email <a href="mailto:hello@collegebasketballbelt.com">hello@collegebasketballbelt.com</a>.</p>
</section>"""
    write("rules/index.html", page("How the belt works", rules, path="/rules/", active="rules",
                                   description="The College Basketball Belt ruleset: where the lineal title starts, which games count, and what happens when a holder leaves Division I."))
    about = """<section class="wrap prose">
<div class="kicker">About</div>
<h1 class="disp">About the College Basketball Belt</h1>
<p>The College Basketball Belt tracks the lineal championship of men's college basketball: one title, passed from team to team only by beating whoever holds it. It's the sister site of the <a href="https://collegefootballbelt.com">College Football Belt</a>, which has tracked the same idea in college football since 1869, and part of the <a href="https://beltholders.com">Belt Holders</a> network, which does it for the NFL, NBA, NHL and MLB.</p>
<p>The site is independent and fan-run. It isn't affiliated with the NCAA, any conference or any school. School names are used only to identify the teams.</p>
<p>Find us at <a href="https://x.com/CollegeBBBelt">@CollegeBBBelt</a> or email <a href="mailto:hello@collegebasketballbelt.com">hello@collegebasketballbelt.com</a>.</p>
</section>"""
    write("about/index.html", page("About", about, path="/about/", description="About the College Basketball Belt, the lineal championship tracker for men's college basketball."))
    ads_text = ("<p>This site shows ads served by Google AdSense. Google and its partners use cookies to serve ads based on your visits to this and other sites. "
                "You can opt out of personalized advertising at <a href=\"https://adssettings.google.com\">Google's Ad Settings</a>. Visitors in the EEA and UK are asked for consent first.</p>"
                if ADSENSE_PUBLISHER_ID else "<p>This site doesn't show ads yet. If that changes, this section will describe what the ad provider collects and how to opt out.</p>")
    privacy = f"""<section class="wrap prose">
<div class="kicker">Privacy</div>
<h1 class="disp">Privacy policy</h1>
<p>Last updated {d_long(date.today().isoformat())}.</p>
<h2 class="disp">What we collect</h2>
<p>Nothing that identifies you. There are no accounts and no forms that send data to us. The email alert form sends your address to Blogtrottr, a third-party service, which emails you when our title-change feed updates; their privacy policy covers that address.</p>
<h2 class="disp">Analytics</h2>
<p>{"We use GoatCounter, a privacy-friendly analytics service that doesn't use cookies or collect personal data, to count page views." if GOATCOUNTER_CODE else "We don't run analytics yet."}</p>
<h2 class="disp">Advertising</h2>
{ads_text}
<h2 class="disp">Contact</h2>
<p><a href="mailto:hello@collegebasketballbelt.com">hello@collegebasketballbelt.com</a></p>
</section>"""
    write("privacy/index.html", page("Privacy", privacy, path="/privacy/", description="College Basketball Belt privacy policy."))
    write("404.html", page("Page not found", """<section class="wrap prose"><div class="kicker">404</div><h1 class="disp">That page lost the belt</h1><p>It's not here anymore. Try the <a href="/">current holder</a> or the <a href="/history/">full history</a>.</p></section>""",
                           path="/404.html", description="Page not found."))


def build_feed(d):
    items = []
    for r in d["reigns"][-40:]:
        if not r.get("won_from") or r.get("seed"):
            continue
        title = f"{r['name']} beat {r['won_from_name']} {score_text(r['won_score'])} and take the College Basketball Belt"
        dt = datetime.fromisoformat(r["start_date"] + "T23:30:00")
        items.append((dt, f"""<item><title>{e(title)}</title><link>{SITE_URL}/</link><guid isPermaLink="false">cbb-{r['index']}-{r['start_date']}</guid><pubDate>{dt.strftime('%a, %d %b %Y %H:%M:%S')} -0500</pubDate><description>{e(title)}. {ordinal(r['reign_no'])} reign for {e(r['name'])}.</description></item>"""))
    items.sort(key=lambda x: x[0], reverse=True)
    write("feed.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>The College Basketball Belt — title changes</title><link>{SITE_URL}/</link><description>Every time the College Basketball Belt changes hands.</description><language>en-us</language>
{"".join(x for _, x in items)}
</channel></rss>""")


def build_api(d):
    cur, ng = d["current"], d.get("next_game")
    out = {"holder": cur["name"], "since": cur["start_date"], "days_held": cur["days"],
           "defenses": cur.get("defenses", 0), "team_reign_number": cur["reign_no"],
           "next_game": ({"team": cur["name"], "opponent": ng["challenger_name"], "is_home": ng["holder_home"],
                          "neutral": ng["neutral"], "date": ng["date"], "venue_name": ng.get("venue")} if ng else None),
           "generated_at": d["generated"], "site": SITE_URL}
    write("api/current.json", json.dumps(out, indent=1))


def build_sitemap():
    urls = []
    for root, _, files in os.walk(OUT):
        if "index.html" in files:
            rel = os.path.relpath(root, OUT).replace(os.sep, "/")
            urls.append("/" if rel == "." else f"/{rel}/")
    urls.sort()
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{SITE_URL}{u}</loc></url>" for u in urls) + "</urlset>")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    write("CNAME", DOMAIN + "\n")
    if ADSENSE_PUBLISHER_ID:
        write("ads.txt", f"google.com, {ADSENSE_PUBLISHER_ID}, DIRECT, f08c47fec0942fa0\n")


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    with open(os.path.join("data", "lineage.json")) as f:
        D.update(json.load(f))
    build_home(D)
    build_history(D)
    build_records(D)
    build_teams(D)
    build_march(D)
    import site_extras
    site_extras.build_all({"cbb": D})
    build_static(D)
    build_feed(D)
    build_api(D)
    build_sitemap()
    for f in ("styles.css", "favicon.png", "apple-touch-icon.png", "icon-512.png", "og.png"):
        if os.path.exists(f):
            shutil.copy(f, os.path.join(OUT, f))
    print(f"Built {sum(len(fs) for _, fs, _ in [(0, f, 0) for _, _, f in os.walk(OUT)])} files into {OUT}/")


if __name__ == "__main__":
    main()
