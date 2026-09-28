"""
The College Football Belt's extra features, for every belt on the network.
Shared file: Belt Holders (four leagues, pages under /<lg>/) and the College
Basketball Belt (one belt, pages at the root) both call it.

    /<lg>/outlook/        State of the Belt: chance to defend, belt tree,
                          season outlook (Monte Carlo), Elo power ranking
    /<lg>/champions/      did the belt finish each season with the champion?
    /<lg>/losers-belt/    the Losers Belt (lose to the holder, take it)
    /<lg>/timeline/       every reign on one canvas, year by year
    /<lg>/decades/...     one page per decade
    /<lg>/on-date/        who held it on any date (birthdays, etc.)
    /<lg>/degrees/        shortest chain of belt wins from team A to team B
    /<lg>/my-team/        your team's belt life, remembered on this device
    /<lg>/daily/          daily game: who took the belt?
    /<lg>/trivia/         twelve questions from the record book
    /<lg>/more/           hub for all of the above
    /<lg>/feed.xml, /<lg>/belt.ics, /<lg>/badge.svg, /embed/

init(site_module, base) once, then build(lg, d) per belt.  `site_module`
supplies page(), write(), subnav(), e(), slug(), d_short(), d_long(),
plural(), plate(), kickoff_12h() and SITE_URL.  `base(lg)` is the URL
prefix for a belt: "/nfl" on Belt Holders, "" on the College Basketball Belt.
"""

import hashlib
import json
import os
import random
import re
from urllib.parse import quote
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

S = None
BASE = None
SITE_NAME = "Belt Holders"
HOLDER_TAG = ' <span class="tag chg">Holder</span>'
SAME_TAG = '<span class="tag chg">Same team</span>'


def init(site_module, base, site_name="Belt Holders"):
    global S, BASE, SITE_NAME
    S, BASE, SITE_NAME = site_module, base, site_name


def e(x):
    return S.e(x)


def b(lg):
    return BASE(lg)


def out(lg, rel):
    pre = b(lg).lstrip("/")
    return f"{pre}/{rel}" if pre else rel


def verb(lg, plural_form, singular_form):
    return singular_form if lg.get("singular") else plural_form


def unit(lg):
    return lg.get("unit", "franchises")


def post_word(lg):
    return lg.get("post_word", "playoffs")


def team_url(lg, code):
    return f"{b(lg)}/teams/{S.slug(lg['team_name'](code))}/"


def tlink(lg, code, season=None):
    nm = lg["team_name"](code, season) if season is not None else lg["team_name"](code)
    return f'<a href="{team_url(lg, code)}">{e(nm)}</a>'


def pct(p, digits=0):
    if p is None:
        return "—"
    v = p * 100
    if 0 < v < 1 and digits == 0:
        return "<1%"
    if 99 < v < 100 and digits == 0:
        return ">99%"
    return f"{v:.{digits}f}%"


def sl(lg, s):
    fn = lg.get("season_label")
    return fn(s) if fn else str(s)


def page(lg, title, body, rel, description, jsonld=None):
    path = f"{b(lg)}/{rel}" if rel else f"{b(lg)}/"
    S.write(out(lg, rel + "index.html" if rel else "index.html"),
            S.page(title, body, path=path, description=description, active=lg.get("key"), jsonld=jsonld))


def numbers(items):
    cells = "".join(f'<div><b class="disp">{v}</b><span class="mono">{e(k)}</span></div>' for v, k in items)
    return f'<div class="numbers">{cells}</div>'


# ================================================================= outlook ==

def _where(g_home, holder):
    return "vs." if g_home == holder else "at"


def tree_columns(lg, tree):
    """Four columns: the next belt game, both possible second games, and so on."""
    if not tree:
        return ""
    cols = defaultdict(list)

    def walk(node, reach, depth):
        if not node:
            return
        cols[depth].append((node, reach))
        walk(node.get("win"), reach * node["p"], depth + 1)
        walk(node.get("lose"), reach * (1 - node["p"]), depth + 1)

    walk(tree, 1.0, 0)
    sn = lg["short_name"]
    html = []
    for depth in sorted(cols):
        cards = []
        for node, reach in sorted(cols[depth], key=lambda x: -x[1]):
            h, c = node["holder"], node["challenger"]
            hp = lg["team_colors"](h)[0]
            cp = lg["team_colors"](c)[0]
            cards.append(f"""<div class="tnode" style="--h:{hp};--c:{cp}">
  <div class="mono tdate">{S.d_short(node['date'])}{'' if depth == 0 else ' · ' + pct(reach) + ' to happen'}</div>
  <div class="tteams"><b class="disp">{e(sn(h))}</b> <span class="mono">{_where(node['home'], h)}</span> <b class="disp">{e(sn(c))}</b></div>
  <div class="tbar"><span style="width:{node['p'] * 100:.1f}%"></span></div>
  <div class="mono tp">{e(sn(h))} {pct(node['p'])} · {e(sn(c))} {pct(1 - node['p'])}</div>
</div>""")
        label = "Next belt game" if depth == 0 else f"Belt game {depth + 1}"
        html.append(f'<div class="tcol"><div class="kicker">{label}</div>{"".join(cards)}</div>')
    # who holds it after each game
    after = []
    for depth in sorted(cols):
        dist = Counter()
        for node, reach in cols[depth]:
            dist[node["holder"]] += reach * node["p"]
            dist[node["challenger"]] += reach * (1 - node["p"])
        after.append(dist)
    teams = sorted({t for d in after for t in d}, key=lambda t: -after[-1].get(t, 0))
    head = "".join(f'<th class="mono r">After game {i + 1}</th>' for i in range(len(after)))
    rows = "".join(
        f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td>'
        + "".join(f'<td class="mono r">{pct(d.get(t, 0)) if d.get(t) else "—"}</td>' for d in after) + "</tr>"
        for t in teams)
    return (f'<div class="tree">{"".join(html)}</div>'
            f'<h3 class="disp sub">Who holds it after each game</h3><div class="tablewrap"><table class="history treetab">'
            f'<thead><tr><th class="mono">Team</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>')


def next_extras(lg, d):
    """Chance to defend + belt tree, appended to the next-defense preview."""
    m = d.get("models") or {}
    pv = d.get("preview") or {}
    if not m.get("tree"):
        return ""
    h = d["current"]["team"]
    p = pv.get("holder_win_prob")
    return f"""<section class="wrap block">
  <div class="head"><h2 class="disp">The belt tree</h2><a class="mono more" href="{b(lg)}/outlook/">State of the belt →</a></div>
  <p class="intro">{e(lg['team_name'](h))} {verb(lg, 'have', 'has')} a {pct(p)} chance to defend, by our Elo ratings. Here's every way the next four belt games can go: win, and the holder plays its next game; lose, and the challenger carries the belt into theirs.</p>
  {tree_columns(lg, m['tree'])}
</section>"""


def build_outlook(lg, d):
    m = d.get("models") or {}
    cur = d["current"]
    h = cur["team"]
    n = lg["team_name"]
    look = m.get("outlook")
    pv = d.get("preview") or {}
    elo = dict(m.get("elo_rank") or [])
    rank = [t for t, _ in m.get("elo_rank") or []]
    h_rank = rank.index(h) + 1 if h in rank else None
    odds = dict(look["odds"]) if look else {}
    contenders = sum(1 for p in odds.values() if p >= 0.01)
    nums = numbers([
        (pct(pv.get("holder_win_prob")) if pv.get("holder_win_prob") is not None else "—", "Chance to win the next defense"),
        (pct(odds.get(h, 0)) if look else "—", "Chance to hold it at the end" if look else "No schedule on file"),
        (contenders if look else "—", "Teams with a 1%+ shot"),
        (f"#{h_rank}" if h_rank else "—", "Holder's Elo rank"),
    ])
    if look and look["odds"]:
        rows = "".join(
            f'<tr><td class="mono n">{i}</td><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td>'
            f'<td class="bar"><span style="width:{min(100, p / look["odds"][0][1] * 100):.1f}%;background:{lg["team_colors"](t)[0]}"></span></td>'
            f'<td class="mono r">{pct(p, 1)}</td><td class="mono r">{elo.get(t, "—")}</td></tr>'
            for i, (t, p) in enumerate(look["odds"][:25], 1))
        outlook_html = f"""<h2 class="disp sub">Who holds it when the regular season ends</h2>
  <p class="intro">We played out the rest of the schedule on file ({S.d_long(look['through'])} is the last game) {look['sims']:,} times, passing the belt game by game with Elo win chances. {e(n(h))} {verb(lg, 'keep', 'keeps')} it to the end in {pct(odds.get(h, 0), 1)} of runs. {contenders} teams finish with it at least 1% of the time.</p>
  <div class="tablewrap"><table class="history odds"><thead><tr><th class="mono">#</th><th class="mono">Team</th><th></th><th class="mono r">Chance</th><th class="mono r">Elo</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    else:
        outlook_html = f"""<h2 class="disp sub">Season outlook</h2><p class="intro">There's no regular-season schedule left on file for {e(n(h))} ({e(d.get('status', '').lower())}). The outlook comes back as soon as the next schedule is out.</p>"""
    tree = m.get("tree")
    tree_html = (f'<h2 class="disp sub">The belt tree</h2><p class="intro">Every way the next four belt games can go.</p>{tree_columns(lg, tree)}'
                 if tree else "")
    power = "".join(
        f'<tr><td class="mono n">{i}</td><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}{HOLDER_TAG if t == h else ""}</td><td class="mono r">{v}</td></tr>'
        for i, (t, v) in enumerate((m.get("elo_rank") or [])[:16], 1))
    body = f"""{S.subnav(lg, "outlook")}
<section class="wrap block">
  <div class="head"><h1 class="disp">State of the {e(lg['name'])} belt</h1><span class="mono note">Updated {S.d_long(d['generated'])}</span></div>
  {nums}
  {tree_html}
  {outlook_html}
  <div class="two">
    <div><h2 class="disp sub">Elo power ranking</h2><table class="history"><thead><tr><th class="mono">#</th><th class="mono">Team</th><th class="mono r">Elo</th></tr></thead><tbody>{power}</tbody></table></div>
    <div class="prose"><h2 class="disp sub">How the numbers work</h2>
      <p>Every team gets an Elo rating built from every game in the record, not just belt games. Wins against good teams count more; bigger margins count a little more in football and basketball. Home teams get a bump worth about {m.get('hfa', 0)} rating points, and between seasons each rating slides a third of the way back toward average.</p>
      <p>The chance to defend comes straight from the two ratings. The outlook plays the rest of the schedule thousands of times. They're honest rough odds, not betting lines.</p>
    </div>
  </div>
</section>"""
    page(lg, f"State of the {lg['name']} belt: odds, belt tree and outlook", body, "outlook/",
         f"Who's likely to hold the lineal {lg['name']} championship belt next: {n(h)}'s chance to defend, the belt tree for the next four games, and season-end odds for every team.")


# =============================================================== champions ==

def build_champions(lg, d):
    rows_data = (d.get("models") or {}).get("champions") or []
    if not rows_data:
        return
    n = lg["team_name"]
    matched = sum(1 for r in rows_data if r["match"])
    streak = 0
    for r in reversed(rows_data):
        if r["match"]:
            streak += 1
        else:
            break
    rows = []
    for r in reversed(rows_data):
        s = r["season"]
        c, h = r["champion"], r["holder"]
        rows.append(f'<tr><td class="mono">{e(sl(lg, s))}</td>'
                    f'<td>{("<i style=background:" + lg["team_colors"](c)[0] + "></i>" + tlink(lg, c, s)) if c else "—"}</td>'
                    f'<td>{("<i style=background:" + lg["team_colors"](h)[0] + "></i>" + tlink(lg, h, s)) if h else "—"}</td>'
                    f'<td class="mono r">{SAME_TAG if r["match"] else ""}</td></tr>')
    note = lg.get("champions_note", "")
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt vs. the champion</h1><span class="mono note">{len(rows_data)} seasons with a {post_word(lg)} final</span></div>
  <p class="intro">The belt doesn't care about brackets. But how often does it end the season in the same hands as the trophy? Here's the team that won each season's last {post_word(lg)} game next to the team holding the belt when the season's games ran out. {e(note)}</p>
  {numbers([(matched, "Seasons it matched"), (pct(matched / len(rows_data)), "Match rate"), (len(rows_data) - matched, "Seasons it didn't"), (streak, "Current matching streak")])}
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Season</th><th class="mono">Champion</th><th class="mono">Belt at season's end</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
</section>"""
    page(lg, f"{lg['name']} belt vs. the champion, every season", body, "champions/",
         f"Season by season: did the lineal {lg['name']} belt finish with the team that won the title? {matched} of {len(rows_data)} times it did.")


# ============================================================= losers belt ==

def build_losers(lg, d):
    L = (d.get("models") or {}).get("losers")
    if not L:
        return
    n = lg["team_name"]
    cur = L["current"]
    t = cur["team"]
    p, s = lg["team_colors"](t)
    top, bottom, ink, accent = S.plate(p, s)
    how = ""
    if L["recent"]:
        r = L["recent"][0]
        a, bb = (int(x) for x in r["score"].split("-"))
        how = f"{e(n(t))} picked it up on {S.d_long(r['date'])}, losing to {e(n(r['from']))} {max(a, bb)}–{min(a, bb)}."
    first = L.get("first")
    rec_days = "".join(f'<tr><td>{tlink(lg, x)}</td><td class="mono r">{v:,}</td></tr>' for x, v in L["most_days"])
    rec_n = "".join(f'<tr><td>{tlink(lg, x)}</td><td class="mono r">{v:,}</td></tr>' for x, v in L["most_reigns"])
    longest = "".join(f'<tr><td>{tlink(lg, r["team"])}</td><td class="mono">{S.d_short(r["start"], True)} – {S.d_short(r["end"], True) if r.get("end") else "now"}</td><td class="mono r">{r["defenses"]}</td></tr>' for r in L["longest"])
    recent = "".join(
        f'<tr><td class="mono">{S.d_short(r["date"], True)}</td><td><i style="background:{lg["team_colors"](r["new"])[0]}"></i>{tlink(lg, r["new"])} lost to {e(n(r["from"]))} '
        f'{max(int(x) for x in r["score"].split("-"))}–{min(int(x) for x in r["score"].split("-"))}</td></tr>' for r in L["recent"])
    body = f"""{S.subnav(lg, "more")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">The {e(lg['name'])} Losers Belt · current holder</div>
    <h1 class="disp holder" style="--fit:{max(len(w) for w in n(t).split())}">{e(n(t))}</h1>
    <p class="lede">{how} To get rid of it, they have to win a game.</p>
  </div>
</section>
<section class="wrap block">
  <p class="intro">Same schedule, same rules, flipped: the Losers Belt passes to whoever <em>loses</em> to its holder. It's the crown nobody wants, and some {unit(lg)} have worn it for years. {f"It started on {S.d_long(first['date'])}, when {e(n(first['team']))} lost to {e(n(first['opp']))}." if first else ""}</p>
  {numbers([(f"{L['reigns']:,}", "Losers Belt reigns"), (f"{L['games']:,}", "Losers Belt games"), (cur.get('defenses', 0), "Losses in a row with it"), (f"{cur['days']:,}", "Days held")])}
  <div class="two">
    <div><h2 class="disp sub">Most days with it</h2><table class="history"><tbody>{rec_days}</tbody></table></div>
    <div><h2 class="disp sub">Most times stuck with it</h2><table class="history"><tbody>{rec_n}</tbody></table></div>
  </div>
  <h2 class="disp sub">Longest Losers Belt reigns (losses in a row as holder)</h2>
  <div class="tablewrap"><table class="history"><tbody>{longest}</tbody></table></div>
  <h2 class="disp sub">Latest handoffs</h2>
  <div class="tablewrap"><table class="history"><tbody>{recent}</tbody></table></div>
</section>"""
    page(lg, f"The {lg['name']} Losers Belt: {n(t)} {verb(lg, 'have', 'has')} it", body, "losers-belt/",
         f"The {lg['name']} Losers Belt passes to whoever loses to its holder. {n(t)} {verb(lg, 'have', 'has')} it now. Records, longest reigns and latest handoffs.")


# ======================================================== timeline / dates ==

def _timeline_data(lg, d):
    first = date.fromisoformat(d["reigns"][0]["start_date"])
    today = date.fromisoformat(d["generated"])
    teams, idx = [], {}
    rs = []
    for r in d["reigns"]:
        t = r["team"]
        if t not in idx:
            idx[t] = len(teams)
            teams.append(t)
        st = (date.fromisoformat(r["start_date"]) - first).days
        en = (date.fromisoformat(r.get("end_date") or d["generated"]) - first).days
        rs.append([st, en, idx[t], r.get("defenses", 0), r["index"], r["reign_no"]])
    return {"first": first.isoformat(), "today": today.isoformat(),
            "names": [lg["team_name"](t) for t in teams], "colors": [lg["team_colors"](t)[0] for t in teams],
            "urls": [team_url(lg, t) for t in teams], "r": rs}


def build_timeline(lg, d):
    data = _timeline_data(lg, d)
    S.write(out(lg, "timeline/data.json"), json.dumps(data, separators=(",", ":")))
    days = Counter()
    for r in d["reigns"]:
        days[r["team"]] += r["days"]
    legend = "".join(f'<span class="chip" style="--c:{lg["team_colors"](t)[0]}">{e(lg["short_name"](t))}</span>' for t, _ in days.most_common(16))
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The {e(lg['name'])} belt timeline</h1><span class="mono note">{len(d['reigns']):,} reigns · one row per year · tap or hover a stripe</span></div>
  <p class="intro">Every day since {S.d_long(data['first'])}, colored by whoever held the belt. Long solid bands are dynasties; the confetti is a belt that wouldn't sit still.</p>
  <div class="strip">{legend}</div>
  <div id="tip" class="tltip mono">Hover a stripe to see who held it.</div>
  <div class="tlwrap"><canvas id="tl"></canvas></div>
</section>
<script>
(function(){{
var C=document.getElementById('tl'),T=document.getElementById('tip'),D=null,ROW=9,LEFT=46;
var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function dt(o){{var d=new Date(Date.parse(D.first+'T12:00:00Z')+o*864e5);return d;}}
function fd(o){{var d=dt(o);return MO[d.getUTCMonth()]+' '+d.getUTCDate()+', '+d.getUTCFullYear();}}
function draw(){{
 var y0=+D.first.slice(0,4),y1=+D.today.slice(0,4),w=C.parentNode.clientWidth,rows=y1-y0+1,dpr=window.devicePixelRatio||1;
 C.width=w*dpr;C.height=rows*ROW*dpr;C.style.width=w+'px';C.style.height=rows*ROW+'px';
 var x=C.getContext('2d');x.scale(dpr,dpr);var W=w-LEFT;
 var cs=getComputedStyle(document.body);x.fillStyle=cs.color;x.font='10px IBM Plex Mono, monospace';
 var base=Date.parse(D.first+'T12:00:00Z');
 D.r.forEach(function(r){{
  var s=base+r[0]*864e5,e=base+(r[1]+1)*864e5;
  for(var t=s;t<e;){{var d=new Date(t),y=d.getUTCFullYear(),ys=Date.UTC(y,0,1),ye=Date.UTC(y+1,0,1),seg=Math.min(e,ye);
   x.fillStyle=D.colors[r[2]];x.fillRect(LEFT+(t-ys)/(ye-ys)*W,(y-y0)*ROW,Math.max(.6,(seg-t)/(ye-ys)*W),ROW-2);t=seg;}}
 }});
 x.fillStyle=cs.color;for(var y=y0;y<=y1;y++)if(y%10===0||y===y0)x.fillText(y,0,(y-y0)*ROW+8);
 C.onmousemove=C.onclick=function(ev){{var b=C.getBoundingClientRect(),px=ev.clientX-b.left-LEFT,py=ev.clientY-b.top;if(px<0)return;
  var y=y0+Math.floor(py/ROW),ys=Date.UTC(y,0,1),ye=Date.UTC(y+1,0,1),t=ys+px/W*(ye-ys),o=Math.floor((t-base)/864e5);
  var lo=0,hi=D.r.length-1;while(lo<hi){{var m=(lo+hi+1)>>1;if(D.r[m][0]<=o)lo=m;else hi=m-1;}}
  var r=D.r[lo];if(!r||o<0)return;
  T.innerHTML='<b>'+D.names[r[2]]+'</b> · reign '+r[4].toLocaleString()+' · '+fd(r[0])+' – '+(r[1]>=(Date.parse(D.today+'T12:00:00Z')-base)/864e5-1?'now':fd(r[1]))+' · '+r[3]+' defenses · <a href="'+D.urls[r[2]]+'">team page →</a>';}};
}}
fetch('{b(lg)}/timeline/data.json').then(function(r){{return r.json();}}).then(function(j){{D=j;draw();window.addEventListener('resize',draw);}});
}})();
</script>"""
    page(lg, f"{lg['name']} belt timeline: every reign since {lg['first_season']}", body, "timeline/",
         f"Every day of the lineal {lg['name']} championship belt since {lg['first_season']}, one colored stripe per reign.")


def build_on_date(lg, d):
    first = d["reigns"][0]["start_date"]
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Who held the {e(lg['name'])} belt on…</h1><span class="mono note">Any date since {S.d_long(first)}</span></div>
  <p class="intro">Your birthday, your wedding day, the day your team moved to town. Pick a date and see who had the belt.</p>
  <form class="compare mono" onsubmit="return false"><label>Date <input type="date" id="od" min="{first}" max="{d['generated']}"></label></form>
  <div id="oout" class="cout"></div>
</section>
<script>
(function(){{
var D=null,I=document.getElementById('od'),O=document.getElementById('oout');
var MO=['January','February','March','April','May','June','July','August','September','October','November','December'];
function fd(o){{var d=new Date(Date.parse(D.first+'T12:00:00Z')+o*864e5);return MO[d.getUTCMonth()]+' '+d.getUTCDate()+', '+d.getUTCFullYear();}}
function go(){{
 if(!D||!I.value)return;var o=Math.round((Date.parse(I.value+'T12:00:00Z')-Date.parse(D.first+'T12:00:00Z'))/864e5);
 if(o<0){{O.innerHTML='<p class="intro">The belt didn\\'t exist yet.</p>';return;}}
 var lo=0,hi=D.r.length-1;while(lo<hi){{var m=(lo+hi+1)>>1;if(D.r[m][0]<=o)lo=m;else hi=m-1;}}
 var r=D.r[lo],nm=D.names[r[2]],now=(r[1]>=Math.round((Date.parse(D.today+'T12:00:00Z')-Date.parse(D.first+'T12:00:00Z'))/864e5));
 O.innerHTML='<div class="ondate" style="--c:'+D.colors[r[2]]+'"><div class="kicker">'+fd(o)+'</div><b class="disp">'+nm+'</b><p>Reign '+r[4].toLocaleString()+' of the belt, and the '+ord(r[5])+' for the '+'{'team' if lg.get('singular') else 'franchise'}'+'. Held from '+fd(r[0])+(now?' and still going':' to '+fd(r[1]))+', with '+r[3]+' successful defense'+(r[3]===1?'':'s')+'.</p><p class="mono"><a href="'+D.urls[r[2]]+'">'+nm+' belt history →</a></p></div>';
 history.replaceState(null,'','?d='+I.value);
}}
function ord(n){{var s=['th','st','nd','rd'],v=n%100;return n+(s[(v-20)%10]||s[v]||s[0]);}}
I.onchange=go;
var q=new URLSearchParams(location.search);I.value=q.get('d')||'{d['generated']}';
fetch('{b(lg)}/timeline/data.json').then(function(r){{return r.json();}}).then(function(j){{D=j;go();}});
}})();
</script>"""
    page(lg, f"Who held the {lg['name']} belt on any date", body, "on-date/",
         f"Pick any date since {lg['first_season']} and see who held the lineal {lg['name']} championship belt that day.")


# ================================================================= decades ==

def build_decades(lg, d):
    first_y = int(d["reigns"][0]["start_date"][:4])
    last_y = int(d["generated"][:4])
    decs = list(range(first_y // 10 * 10, last_y // 10 * 10 + 1, 10))
    n = lg["team_name"]
    cards = []
    for dec in decs:
        a, z = date(dec, 1, 1), min(date(dec + 10, 1, 1), date.fromisoformat(d["generated"]) + timedelta(days=1))
        if z <= a:
            continue
        days = Counter()
        started = []
        for r in d["reigns"]:
            rs = date.fromisoformat(r["start_date"])
            re_ = date.fromisoformat(r.get("end_date") or d["generated"])
            lo, hi = max(rs, a), min(re_, z)
            if hi > lo:
                days[r["team"]] += (hi - lo).days
            if a <= rs < z:
                started.append(r)
        bgs = [bg for bg in d["belt_games"] if a.isoformat() <= bg["date"] < z.isoformat()]
        changes = [bg for bg in bgs if bg["outcome"] == "changed"]
        if not bgs and not days:
            continue
        top = days.most_common(10)
        best = max(started, key=lambda r: (r.get("defenses", 0), r["days"]), default=None)
        seasons = sorted({bg["season"] for bg in bgs})
        tot = sum(days.values()) or 1
        bar = "".join(f'<span style="flex:{v};background:{lg["team_colors"](t)[0]}" title="{e(n(t))}"></span>' for t, v in top)
        rows = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v:,}</td><td class="mono r">{pct(v / tot)}</td></tr>' for t, v in top)
        schips = "".join(f'<a class="chip" href="{b(lg)}/seasons/{s}/">{e(sl(lg, s))}</a>' for s in seasons)
        chain = "".join(f'<tr><td class="mono">{S.d_short(r["start_date"], True)}</td><td><i style="background:{lg["team_colors"](r["team"])[0]}"></i>{tlink(lg, r["team"])}</td><td class="mono r">{r.get("defenses", 0)} def.</td></tr>'
                        for r in sorted(started, key=lambda r: -r.get("defenses", 0))[:10])
        body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The {e(lg['name'])} belt in the {dec}s</h1><a class="mono more" href="{b(lg)}/decades/">All decades →</a></div>
  {numbers([(f"{len(bgs):,}", "Belt games"), (f"{len(changes):,}", "Title changes"), (len(days), f"{unit(lg).capitalize()} that held it"), (e(lg['short_name'](top[0][0])) if top else "—", "Held it longest")])}
  <div class="decbar">{bar}</div>
  {f'<p class="intro">The reign of the decade: {tlink(lg, best["team"])}, from {S.d_long(best["start_date"])}, with {S.plural(best.get("defenses", 0), "defense")}.</p>' if best else ''}
  <div class="two">
    <div><h2 class="disp sub">Days with the belt, {dec}s</h2><table class="history"><tbody>{rows}</tbody></table></div>
    <div><h2 class="disp sub">Best reigns that began this decade</h2><table class="history"><tbody>{chain}</tbody></table></div>
  </div>
  <h2 class="disp sub">Seasons</h2><div class="strip">{schips}</div>
</section>"""
        page(lg, f"The {lg['name']} belt in the {dec}s", body, f"decades/{dec}s/",
             f"The lineal {lg['name']} championship belt in the {dec}s: {len(changes)} title changes, {len(days)} holders, and who held it longest.")
        cards.append(f'<a class="deccard" href="{b(lg)}/decades/{dec}s/"><b class="disp">{dec}s</b><div class="decbar sm">{bar}</div>'
                     f'<span class="mono">{S.plural(len(changes), "change")} · {e(lg["short_name"](top[0][0])) if top else ""} held it most</span></a>')
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The {e(lg['name'])} belt, decade by decade</h1></div>
  <div class="decgrid">{"".join(reversed(cards))}</div>
</section>"""
    page(lg, f"The {lg['name']} belt by decade", body, "decades/",
         f"The lineal {lg['name']} championship belt decade by decade: who held it most and how often it moved.")


# ================================================================= degrees ==

def build_degrees(lg, d):
    teams = sorted({t for bg in d["belt_games"] for t in (bg.get("holder"), bg["opponent"]) if t}, key=lambda t: lg["team_name"](t))
    opts = "".join(f'<option value="{t}">{e(lg["team_name"](t))}</option>' for t in teams)
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Degrees of the belt</h1><span class="mono note">The shortest chain of belt-game wins from one team to another</span></div>
  <p class="intro">Your team beat a team that beat a team that beat… your rival? Pick two {unit(lg)}. We find the fewest belt games that link a win by the first to a loss by the second, using only games with the {e(lg['name'])} belt on the line.</p>
  <form class="compare mono" onsubmit="return false">
    <label>From <select id="da">{opts}</select></label>
    <label>To <select id="db">{opts}</select></label>
  </form>
  <div id="dout" class="cout"></div>
</section>
<script>
(function(){{
var D=null,A=document.getElementById('da'),B=document.getElementById('db'),O=document.getElementById('dout'),G=null;
var q=new URLSearchParams(location.search);if(q.get('a'))A.value=q.get('a');if(q.get('b'))B.value=q.get('b');else if(B.options.length>1&&A.value===B.value)B.selectedIndex=1;
var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fd(d){{var p=d.split('-');return MO[+p[1]-1]+' '+(+p[2])+', '+p[0];}}
function graph(){{G={{}};D.games.forEach(function(r,i){{var s=r[4].split('-').map(Number);if(s[0]===s[1])return;var h=r[5],a=(h===r[2]?r[3]:r[2]);var w=s[0]>s[1]?h:a,l=w===h?a:h;(G[w]=G[w]||[]).push([l,i]);}});}}
function go(){{
 if(!D)return;var a=A.value,z=B.value;if(a===z){{O.innerHTML='<p class="intro">Pick two different teams.</p>';return;}}
 var prev={{}};prev[a]=null;var Q=[a],found=false;
 while(Q.length&&!found){{var t=Q.shift();(G[t]||[]).forEach(function(e){{if(!(e[0] in prev)){{prev[e[0]]=[t,e[1]];if(e[0]===z)found=true;Q.push(e[0]);}}}});}}
 if(!(z in prev)){{O.innerHTML='<p class="intro">No chain of belt wins links '+D.teams[a]+' to '+D.teams[z]+'.</p>';return;}}
 var path=[],c=z;while(prev[c]){{path.unshift(prev[c][1]);c=prev[c][0];}}
 var rows=path.map(function(i,k){{var r=D.games[i],s=r[4].split('-').map(Number),h=r[5],aw=(h===r[2]?r[3]:r[2]),w=s[0]>s[1]?h:aw,l=w===h?aw:h;
  return '<li><span class="mono">'+(k+1)+' · '+fd(r[1])+'</span><b>'+D.teams[w]+'</b> beat '+D.teams[l]+' '+Math.max(s[0],s[1])+'–'+Math.min(s[0],s[1])+(r[6]==='c'?' <span class="tag chg">Title change</span>':'')+'</li>';}}).join('');
 O.innerHTML='<div class="numbers"><div><b class="disp">'+path.length+'</b><span class="mono">Degree'+(path.length===1?'':'s')+' of separation</span></div></div><ol class="degrees">'+rows+'</ol>';
 history.replaceState(null,'','?a='+a+'&b='+z);
}}
A.onchange=B.onchange=go;
fetch('{b(lg)}/compare/data.json').then(function(r){{return r.json();}}).then(function(j){{D=j;graph();go();}});
}})();
</script>"""
    page(lg, f"Degrees of the {lg['name']} belt", body, "degrees/",
         f"Find the shortest chain of lineal {lg['name']} belt wins linking any two teams.")


# ================================================================= my team ==

def build_my_team(lg, d):
    m = d.get("models") or {}
    rec = d["records"]
    recent = set(m.get("elo") or {})
    cur = d["current"]
    odds = dict((m.get("outlook") or {}).get("odds") or [])
    rank = {t: i for i, (t, _) in enumerate(m.get("elo_rank") or [], 1)}
    reigns = defaultdict(list)
    for r in d["reigns"]:
        reigns[r["team"]].append(r)
    losers_cur = (m.get("losers") or {}).get("current", {}).get("team")
    tree_reach = Counter()

    def walk(node, reach):
        if not node:
            return
        tree_reach[node["challenger"]] += reach
        walk(node.get("win"), reach * node["p"])
        walk(node.get("lose"), reach * (1 - node["p"]))

    walk(m.get("tree"), 1.0)
    data = {}
    for t in sorted(recent, key=lambda t: lg["team_name"](t)):
        rs = reigns.get(t, [])
        last = rs[-1] if rs else None
        meet = (m.get("meet") or {}).get(t)
        data[t] = {
            "name": lg["team_name"](t), "short": lg["short_name"](t), "color": lg["team_colors"](t)[0], "url": team_url(lg, t),
            "reigns": len(rs), "days": sum(r["days"] for r in rs), "defenses": sum(r.get("defenses", 0) for r in rs),
            "best": max((r.get("defenses", 0) for r in rs), default=0),
            "last": [last["start_date"], last.get("end_date")] if last else None,
            "holder": t == cur["team"], "elo": (m.get("elo") or {}).get(t), "rank": rank.get(t),
            "odds": odds.get(t), "meet": meet, "shot": round(tree_reach.get(t, 0), 3), "losers": t == losers_cur,
        }
    S.write(out(lg, "my-team/data.json"), json.dumps(data, separators=(",", ":")))
    opts = "".join(f'<option value="{t}">{e(v["name"])}</option>' for t, v in data.items())
    key = lg.get("key", "cbb")
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">My team</h1><span class="mono note">Pick once; this device remembers</span></div>
  <form class="compare mono" onsubmit="return false"><label>Team <select id="mt"><option value="">Choose…</option>{opts}</select></label></form>
  <div id="mout" class="cout"></div>
</section>
<script>
(function(){{
var D=null,S=document.getElementById('mt'),O=document.getElementById('mout'),K='belt-myteam-{key}';
var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fd(d){{var p=d.split('-');return MO[+p[1]-1]+' '+(+p[2])+', '+p[0];}}
function pc(p){{return p==null?'—':(p>0&&p<.01?'<1%':Math.round(p*100)+'%');}}
function go(){{
 var t=S.value;if(!t||!D){{O.innerHTML='';return;}}try{{localStorage.setItem(K,t);}}catch(e){{}}
 var x=D[t],s=[];
 if(x.holder)s.push('<b>{e(lg["team_name"](cur["team"]))} '+'{verb(lg, "hold", "holds")}'+' the belt right now.</b>');
 else if(x.meet)s.push('Next shot at the belt: '+fd(x.meet[0])+' '+(x.meet[1]===t?'at home':'on the road')+', if nobody takes it first.');
 else s.push('No game against the current holder on the schedule yet.');
 if(x.shot>0&&!x.holder)s.push('Chance they get a belt game in the next four: '+pc(x.shot)+'.');
 if(x.odds!=null)s.push('Chance to hold it when the regular season ends: '+pc(x.odds)+'.');
 if(x.losers)s.push('They also hold the <a href="{b(lg)}/losers-belt/">Losers Belt</a>. Ouch.');
 O.innerHTML='<div class="ondate" style="--c:'+x.color+'"><div class="kicker">'+(x.rank?'Elo #'+x.rank+' · '+x.elo:'')+'</div><b class="disp">'+x.name+'</b><p>'+s.join(' ')+'</p>'+
 '<div class="numbers"><div><b class="disp">'+x.reigns+'</b><span class="mono">Reigns</span></div><div><b class="disp">'+x.days.toLocaleString()+'</b><span class="mono">Days held</span></div><div><b class="disp">'+x.defenses+'</b><span class="mono">Defenses</span></div><div><b class="disp">'+x.best+'</b><span class="mono">Best reign (defenses)</span></div></div>'+
 '<p>'+(x.last?(x.last[1]?'Last held it '+fd(x.last[0])+' – '+fd(x.last[1])+'.':'Holding it since '+fd(x.last[0])+'.'):'Never held the belt.')+'</p><p class="mono"><a href="'+x.url+'">Full team belt history →</a> · <a href="{b(lg)}/compare/?a='+t+'&b={cur["team"]}">vs. the holder →</a></p></div>';
}}
S.onchange=go;
try{{var v=localStorage.getItem(K);if(v)S.value=v;}}catch(e){{}}
fetch('{b(lg)}/my-team/data.json').then(function(r){{return r.json();}}).then(function(j){{D=j;go();}});
}})();
</script>"""
    page(lg, f"My team: your {lg['name']} belt dashboard", body, "my-team/",
         f"Pick your team and see its {lg['name']} belt history, next shot at the belt and odds to hold it.")


# =================================================== daily game + trivia ==

def _decoys(lg, pool, correct, season, k=3, seed=""):
    rng = random.Random(seed)
    cands = [t for t in pool if t != correct]
    rng.shuffle(cands)
    return cands[:k]


def build_daily(lg, d):
    changes = [bg for bg in d["belt_games"] if bg["outcome"] == "changed" and bg.get("holder")]
    by_season = defaultdict(set)
    for bg in d["belt_games"]:
        for t in (bg.get("holder"), bg["opponent"]):
            if t:
                by_season[bg["season"]].add(t)
    rng = random.Random(lg.get("key", "cbb") + "daily")
    # a year's worth of puzzles, weighted toward the modern game but reaching back to the start
    if len(changes) > 400:
        modern = changes[len(changes) // 2:]
        old = changes[:len(changes) // 2]
        pick = rng.sample(modern, 250) + rng.sample(old, 150)
    else:
        pick = list(changes)
    rng.shuffle(pick)
    items = []
    for bg in pick:
        s = bg["season"]
        pool = sorted(by_season[s] | by_season.get(s - 1, set()) | by_season.get(s + 1, set()))
        dec = _decoys(lg, [t for t in pool if t != bg["holder"]], bg["opponent"], s, 3, seed=str(bg["n"]))
        if len(dec) < 3:
            continue
        hp, ap = (int(x) for x in bg["score"].split("-"))
        items.append([bg["date"], lg["team_name"](bg["holder"], s), "home" if bg["home"] == bg["holder"] else "road",
                      f"{max(hp, ap)}–{min(hp, ap)}", lg["team_name"](bg["opponent"], s),
                      [lg["team_name"](t, s) for t in dec], bg["n"], sl(lg, s)])
    key = lg.get("key", "cbb")
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Daily belt game</h1><span class="mono note" id="dd"></span></div>
  <p class="intro">One title change from {e(lg['name'])} history every day. Who took the belt?</p>
  <div id="dq" class="quiz"></div>
  <p class="mono note" id="ds"></p>
  <p class="mono more"><a href="{b(lg)}/trivia/">Play {e(lg['name'])} belt trivia →</a></p>
</section>
<script>
(function(){{
var P={json.dumps(items, separators=(",", ":"))},K='belt-daily-{key}';
var MO=['January','February','March','April','May','June','July','August','September','October','November','December'];
function fd(d){{var p=d.split('-');return MO[+p[1]-1]+' '+(+p[2])+', '+p[0];}}
var now=new Date(),td=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');
var day=Math.floor(Date.parse(td+'T12:00:00Z')/864e5),q=P[day%P.length];
document.getElementById('dd').textContent=fd(td);
var st={{}};try{{st=JSON.parse(localStorage.getItem(K)||'{{}}');}}catch(e){{}}
var opts=[q[4]].concat(q[5]),r=day;opts.sort(function(a,b){{r=(r*9301+49297)%233280;return (a+r).length%3-1;}});
opts=opts.map(function(o,i){{return [o,i];}}).sort(function(a,b){{return ((a[1]*7+day)%4)-((b[1]*7+day)%4);}}).map(function(x){{return x[0];}});
var Q=document.getElementById('dq');
Q.innerHTML='<p class="big">'+fd(q[0])+' · '+q[7]+'. '+q[1]+' put the belt on the line '+(q[2]==='home'?'at home':'on the road')+' and lost '+q[3]+'. Who took it?</p><div class="opts">'+opts.map(function(o){{return '<button class="mono">'+o+'</button>';}}).join('')+'</div><p class="reveal"></p>';
function finish(pick){{
 var ok=pick===q[4];Q.querySelectorAll('button').forEach(function(b){{b.disabled=true;if(b.textContent===q[4])b.className+=' right';else if(b.textContent===pick)b.className+=' wrong';}});
 Q.querySelector('.reveal').innerHTML=(ok?'Right. ':'Not quite. ')+q[4]+' took it: belt game '+q[6].toLocaleString()+'. <a href="{b(lg)}/seasons/'+q[0].slice(0,4)+'/">See the season →</a>';
}}
function stats(){{var s=st.streak||0,p=st.played||0,w=st.won||0;document.getElementById('ds').textContent=p?('Played '+p+' · won '+w+' · streak '+s):'';}}
if(st.last===td){{finish(st.pick);}}
Q.querySelectorAll('button').forEach(function(b){{b.onclick=function(){{if(st.last===td)return;var ok=b.textContent===q[4];
 var y=new Date(Date.parse(td+'T12:00:00Z')-864e5).toISOString().slice(0,10);
 st.streak=ok?((st.last===y&&st.lastok)?(st.streak||0)+1:1):0;st.played=(st.played||0)+1;st.won=(st.won||0)+(ok?1:0);st.last=td;st.pick=b.textContent;st.lastok=ok;
 try{{localStorage.setItem(K,JSON.stringify(st));}}catch(e){{}}finish(b.textContent);stats();}};}});
stats();
}})();
</script>"""
    page(lg, f"Daily {lg['name']} belt game", body, "daily/",
         f"A new {lg['name']} belt puzzle every day: one title change from history. Who took the belt?")


def _num_opts(v, rng):
    step = max(1, round(v * 0.15))
    s = {v}
    while len(s) < 4:
        s.add(max(0, v + rng.choice([-3, -2, -1, 1, 2, 3]) * step))
    return [str(x) for x in s]


def build_trivia(lg, d):
    m = d.get("models") or {}
    rec = d["records"]
    n = lg["team_name"]
    rng = random.Random(lg.get("key", "cbb") + "trivia")
    recent = list(m.get("elo") or {})
    all_holders = [t for t, _ in rec["most_days"]]
    qs = []

    def q(text, right, wrong):
        wrong = [w for w in wrong if w != right][:3]
        if len(wrong) < 3:
            return
        qs.append({"q": text, "a": right, "o": sorted([right] + wrong, key=lambda x: rng.random())})

    others = lambda exclude, pool: [n(t) for t in pool if t not in exclude]
    q(f"Which {unit(lg)[:-1]} has held the {lg['name']} belt for the most total days?", n(rec["most_days"][0][0]), others({rec["most_days"][0][0]}, all_holders[1:6]))
    q(f"Which {unit(lg)[:-1]} has the most separate reigns?", n(rec["most_reigns"][0][0]), others({rec["most_reigns"][0][0]}, [t for t, _ in rec["most_reigns"][1:6]]))
    lr = rec["longest_reigns"][0]
    q(f"The longest reign ever ran {lr['defenses']} straight defenses. Whose was it?", n(lr["team"]), others({lr["team"]}, [r["team"] for r in rec["longest_reigns"][1:8]]))
    fg = d.get("first_game")
    if fg:
        early = sorted({t for bg in d["belt_games"][:60] for t in (bg.get("holder"), bg["opponent"]) if t})
        q(f"Who won the very first {lg['name']} belt game, on {S.d_long(fg['date'])}?", n(fg["new_holder"], fg["season"]),
          [n(t, fg["season"]) for t in early if t != fg["new_holder"]][:3])
    q(f"How many {unit(lg)} have held the {lg['name']} belt?", str(rec["programs"]), [x for x in _num_opts(rec["programs"], rng) if x != str(rec["programs"])])
    if rec.get("busiest_seasons"):
        s, c = rec["busiest_seasons"][0]
        q(f"In which season did the belt change hands the most ({c} times)?", sl(lg, s), [sl(lg, x) for x, _ in rec["busiest_seasons"][1:4]])
    L = m.get("losers")
    if L:
        t = L["current"]["team"]
        q(f"Who's stuck with the {lg['name']} Losers Belt right now?", n(t), [n(x) for x in rng.sample([r for r in recent if r != t], 3)])
    riv = d.get("rivalries") or []
    if len(riv) >= 4:
        top = riv[0]
        q("Which pair has met the most times with the belt on the line?", f"{n(top['a'])} & {n(top['b'])}",
          [f"{n(p['a'])} & {n(p['b'])}" for p in riv[1:4]])
    dr = rec.get("droughts") or []
    if len(dr) >= 4:
        q("Which current team has gone longest since it last held the belt?", n(dr[0]["team"]), [n(x["team"]) for x in dr[4:10:2]])
    ch = m.get("champions") or []
    if ch:
        k = sum(1 for c in ch if c["match"])
        q(f"Out of {len(ch)} seasons, how many times has the belt ended the season with the champion?", str(k), [x for x in _num_opts(k, rng) if x != str(k)])
    cur = d["current"]
    if cur.get("won_from"):
        q(f"Who did {n(cur['team'])} take the belt from on {S.d_long(cur['start_date'])}?", n(cur["won_from"]),
          [n(x) for x in rng.sample([r for r in recent if r not in (cur["won_from"], cur["team"])], 3)])
    tk = rec.get("top_takeovers") or []
    if tk:
        w0 = tk[0]
        q(f"Which team has taken the belt from {n(w0['loser'])} the most times ({w0['times']})?", n(w0["winner"]),
          [n(x) for x in rng.sample([r for r in all_holders if r not in (w0["winner"], w0["loser"])], 3)])
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">{e(lg['name'])} belt trivia</h1><span class="mono note">{len(qs)} questions from the record book</span></div>
  <div id="tq" class="quiz"></div>
  <p class="big" id="ts"></p>
  <p class="mono more"><a href="{b(lg)}/daily/">Today's daily belt game →</a> · <a href="{b(lg)}/records/">The records →</a></p>
</section>
<script>
(function(){{
var Q={json.dumps(qs, separators=(",", ":"))},T=document.getElementById('tq'),score=0,done=0;
T.innerHTML=Q.map(function(q,i){{return '<div class="tqi"><p class="big"><span class="mono">'+(i+1)+'.</span> '+q.q+'</p><div class="opts">'+q.o.map(function(o){{return '<button class="mono" data-i="'+i+'">'+o+'</button>';}}).join('')+'</div></div>';}}).join('');
T.querySelectorAll('button').forEach(function(b){{b.onclick=function(){{var q=Q[+b.dataset.i],box=b.parentNode;if(box.dataset.done)return;box.dataset.done=1;done++;
 if(b.textContent===q.a)score++;box.querySelectorAll('button').forEach(function(x){{x.disabled=true;if(x.textContent===q.a)x.className+=' right';else if(x===b)x.className+=' wrong';}});
 if(done===Q.length)document.getElementById('ts').textContent='You got '+score+' of '+Q.length+'.';}};}});
}})();
</script>"""
    page(lg, f"{lg['name']} belt trivia", body, "trivia/",
         f"How well do you know the lineal {lg['name']} championship belt? {len(qs)} questions from the record book.")


# ======================================================= feeds, ics, badge ==

def build_feed(lg, d):
    n = lg["team_name"]
    items = []
    for r in d["reigns"][-40:][::-1]:
        if not r.get("won_from"):
            continue
        title = f"{r['name']} beat {n(r['won_from'])} {S.won_score_text(r)} and take the {lg['name']} belt"
        dt = datetime.fromisoformat(r["start_date"] + "T23:00:00")
        items.append(f"<item><title>{e(title)}</title><link>{S.SITE_URL}{b(lg)}/</link><guid isPermaLink=\"false\">{lg.get('key', 'cbb')}-{r['index']}-{r['start_date']}</guid>"
                     f"<pubDate>{dt.strftime('%a, %d %b %Y %H:%M:%S')} -0400</pubDate><description>{e(title)}.</description></item>")
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{e(lg["long_name"])} — title changes</title>'
           f'<link>{S.SITE_URL}{b(lg)}/</link><description>Every time the lineal {e(lg["name"])} belt changes hands.</description><language>en-us</language>'
           + "".join(items) + "</channel></rss>")
    S.write(out(lg, "feed.xml"), xml)


def _ics_escape(s):
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def build_ics(lg, d):
    n = lg["team_name"]
    ng = d.get("next_game")
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ev = []
    if ng:
        h, c = ng["holder"], ng["challenger"]
        where = "vs." if ng["holder_home"] else "at"
        summary = _ics_escape(f"{lg['name']} belt: {lg['short_name'](h)} {where} {lg['short_name'](c)}")
        ko = ng.get("kickoff")
        if ko:
            st = f"DTSTART;TZID=America/New_York:{ng['date'].replace('-', '')}T{ko.replace(':', '')}00"
            hrs = 3 if lg.get("key") in ("nfl", "mlb") else 2.5
            en_dt = datetime.fromisoformat(f"{ng['date']}T{ko}") + timedelta(hours=hrs)
            en = f"DTEND;TZID=America/New_York:{en_dt.strftime('%Y%m%dT%H%M%S')}"
        else:
            st = f"DTSTART;VALUE=DATE:{ng['date'].replace('-', '')}"
            en = f"DTEND;VALUE=DATE:{(date.fromisoformat(ng['date']) + timedelta(days=1)).strftime('%Y%m%d')}"
        desc = _ics_escape(f"{n(h)} defend the lineal {lg['name']} belt against {n(c)}. Preview: {S.SITE_URL}{b(lg)}/next/")
        loc = _ics_escape(ng.get("stadium") or "")
        ev.append("\r\n".join(["BEGIN:VEVENT", f"UID:{lg.get('key', 'cbb')}-{ng['date']}-{h}-{c}@{S.SITE_URL.split('//')[1]}",
                               f"DTSTAMP:{stamp}", st, en, f"SUMMARY:{summary}", f"DESCRIPTION:{desc}",
                               f"LOCATION:{loc}", f"URL:{S.SITE_URL}{b(lg)}/next/", "END:VEVENT"]))
    cal = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{SITE_NAME}//{lg['name']} belt//EN", "CALSCALE:GREGORIAN",
                       f"X-WR-CALNAME:{_ics_escape(lg['name'])} belt defenses", "X-WR-TIMEZONE:America/New_York",
                       "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H", *ev, "END:VCALENDAR"]) + "\r\n"
    S.write(out(lg, "belt.ics"), cal)


def badge_svg(lg, d):
    cur = d["current"]
    p, s = lg["team_colors"](cur["team"])
    top, bottom, ink, accent = S.plate(p, s)
    name = lg["team_name"](cur["team"])
    size = 26 if len(name) <= 20 else 22 if len(name) <= 26 else 18
    sub = f"since {S.d_short(cur['start_date'], True)} · {S.plural(cur.get('defenses', 0), 'defense')}"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="360" height="72" viewBox="0 0 360 72" role="img" aria-label="{e(lg['name'])} belt: {e(name)}">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient></defs>
<rect width="360" height="72" rx="6" fill="url(#g)"/><rect x="0" y="0" width="8" height="72" rx="3" fill="{accent}"/>
<text x="22" y="20" font-family="Menlo,Consolas,monospace" font-size="10" letter-spacing="2" fill="{ink}" opacity=".8">{e(lg['name'].upper())} BELT HOLDER</text>
<text x="22" y="46" font-family="'Arial Narrow',Arial,sans-serif" font-weight="700" font-size="{size}" fill="{ink}">{e(name.upper())}</text>
<text x="22" y="63" font-family="Menlo,Consolas,monospace" font-size="10" fill="{ink}" opacity=".8">{e(sub)}</text>
</svg>"""


def build_badge(lg, d):
    S.write(out(lg, "badge.svg"), badge_svg(lg, d))


def embed_snippet(lg):
    url = f"{S.SITE_URL}{b(lg)}/"
    return (f'<a href="{url}"><img src="{S.SITE_URL}{b(lg)}/badge.svg" width="360" height="72" '
            f'alt="Current {lg["name"]} belt holder"></a>')


def build_embed(leagues_datas):
    """One /embed/ page listing a badge per belt (call once per site)."""
    blocks = []
    for lg, d in leagues_datas:
        snip = embed_snippet(lg)
        blocks.append(f"""<div class="embed"><h2 class="disp sub">{e(lg['name'])}</h2><img src="{b(lg)}/badge.svg" width="360" height="72" alt="">
<textarea readonly class="mono" rows="3" onclick="this.select()">{e(snip)}</textarea>
<p class="mono note">Also: <a href="{b(lg)}/feed.xml">RSS</a> · <a href="{b(lg)}/belt.ics">calendar (next defense)</a> · <a href="/api/current.json">JSON</a></p></div>""")
    body = f"""<section class="wrap block">
  <div class="head"><h1 class="disp">Put the belt on your site</h1><span class="mono note">Badges update on their own</span></div>
  <p class="intro">Paste a snippet into your blog, forum signature or team site. The badge always shows the current holder.</p>
  <div class="embeds">{"".join(blocks)}</div>
</section>"""
    S.write("embed/index.html", S.page("Embed the belt: badges, feeds and calendars", body, path="/embed/",
                                       description="Free badges that always show the current belt holder, plus RSS feeds, calendars and a JSON API."))


# ================================================================ live box ==

ESPN = {"nfl": "football/nfl", "nba": "basketball/nba", "nhl": "hockey/nhl", "mlb": "baseball/mlb",
        "cbb": "basketball/mens-college-basketball"}


def live_box(lg, d):
    """A box that fills in with the live score when the holder is playing."""
    ng = d.get("next_game")
    path = ESPN.get(lg.get("key", "cbb"))
    if not ng or not path:
        return ""
    names = [lg["short_name"](ng["holder"]), lg["short_name"](ng["challenger"]),
             lg["team_name"](ng["holder"]), lg["team_name"](ng["challenger"])]
    return f"""<div id="livebox" class="livebox wrap" hidden></div>
<script>
(function(){{
var G={json.dumps({"date": ng["date"], "names": names, "holder": lg["short_name"](ng["holder"])})};
var t=new Date(),et=new Date(t.toLocaleString('en-US',{{timeZone:'America/New_York'}}));
var today=et.getFullYear()+'-'+String(et.getMonth()+1).padStart(2,'0')+'-'+String(et.getDate()).padStart(2,'0');
if(today!==G.date)return;
var box=document.getElementById('livebox');
function low(s){{return (s||'').toLowerCase();}}
function hit(c){{var t=c.team||{{}};return [t.name,t.shortDisplayName,t.displayName,t.location].some(function(x){{return G.names.some(function(n){{return low(n)===low(x);}});}});}}
function load(){{
 fetch('https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates='+G.date.replace(/-/g,'')+'&limit=400').then(function(r){{return r.json();}}).then(function(j){{
  var ev=(j.events||[]).find(function(e){{var c=e.competitions[0].competitors;return c.length===2&&hit(c[0])&&hit(c[1]);}});
  if(!ev)return;var c=ev.competitions[0],st=c.status.type,cs=c.competitors;
  var away=cs.find(function(x){{return x.homeAway==='away';}}),home=cs.find(function(x){{return x.homeAway==='home';}});
  function row(x){{return '<div class="lrow"><b class="disp">'+x.team.shortDisplayName+'</b><b class="disp sc">'+(st.state==='pre'?'':x.score)+'</b></div>';}}
  box.innerHTML='<div class="kicker dot">'+(st.state==='in'?'Live · belt on the line':st.state==='post'?'Final · belt game':'Today · belt game')+'</div>'+row(away)+row(home)+'<div class="mono note">'+st.shortDetail+'</div>';
  box.hidden=false;if(st.state!=='post')setTimeout(load,60000);
 }}).catch(function(){{}});
}}
load();
}})();
</script>"""


# ==================================================================== hub ==

def build_more(lg, d):
    cards = [
        ("outlook/", "State of the belt", "Chance to defend, the belt tree, season odds and Elo ratings."),
        ("champions/", "Belt vs. champion", f"Did the belt finish each season with the team that won the {post_word(lg)}?"),
        ("losers-belt/", "The Losers Belt", "Lose to the holder and it's yours. The crown nobody wants."),
        ("timeline/", "Timeline", "Every reign since the start, one colored stripe at a time."),
        ("decades/", "Decades", "Who ruled each decade, and how often the belt moved."),
        ("on-date/", "Belt on any date", "Your birthday, your wedding day: who held it?"),
        ("degrees/", "Degrees of the belt", "The shortest chain of belt wins from one team to another."),
        ("my-team/", "My team", "Your team's belt life and next shot, remembered on this device."),
        ("daily/", "Daily belt game", "One title change a day. Guess who took it."),
        ("trivia/", "Trivia", "Questions from the record book."),
        ("/embed/", "Badge for your site", "A badge that always shows the current holder."),
        ("feed.xml", "RSS feed", f"Every {lg['name']} title change, as it happens."),
        ("belt.ics", "Calendar", "Subscribe and the next title defense lands on your calendar."),
    ]
    grid = "".join(f'<a class="morecard" href="{h if h.startswith("/") else b(lg) + "/" + h}"><b class="disp">{e(t)}</b><span>{e(x)}</span></a>' for h, t, x in cards)
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">More {e(lg['name'])} belt</h1></div>
  <div class="moregrid">{grid}</div>
</section>"""
    page(lg, f"More from the {lg['name']} belt", body, "more/",
         f"Odds, the belt tree, the Losers Belt, a timeline, trivia, a daily game and more for the lineal {lg['name']} championship belt.")


def build(lg, d):
    build_outlook(lg, d)
    build_champions(lg, d)
    build_losers(lg, d)
    build_timeline(lg, d)
    build_on_date(lg, d)
    build_decades(lg, d)
    build_degrees(lg, d)
    build_my_team(lg, d)
    build_daily(lg, d)
    build_trivia(lg, d)
    if lg.get("feed", True):
        build_feed(lg, d)
    build_ics(lg, d)
    build_badge(lg, d)
    build_more(lg, d)


# ========================================================= next-game preview ==
# The College Football Belt's preview layout: split matchup hero, what's at
# stake, odds line, "beat the lean" pick, AI preview, form, head to head and
# a sidebar.  Reads preview_extra.json from enrich_preview.py when present;
# every piece degrades gracefully without it.

def _extra(lg):
    for p in (os.path.join("data", lg.get("key", ""), "preview_extra.json"), os.path.join("data", "preview_extra.json")):
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f) or {}, os.path.dirname(p)
    return {}, None


def _ledger(folder):
    p = os.path.join(folder or "", "lean_ledger.json")
    if folder and os.path.exists(p):
        with open(p) as f:
            return json.load(f) or []
    return []


def _monogram(name):
    parts = [w for w in re.split(r"[\s\-&]+", name) if w and w[0].isalnum()]
    return "".join(w[0] for w in parts[:2]).upper() or name[:2].upper()


def _location(lg, code):
    full, short = lg["team_name"](code), lg["short_name"](code)
    return full[: -len(short)].strip() if full.endswith(short) and full != short else ""


def _gcal(title, start_iso, hours, details, loc):
    try:
        st = datetime.strptime(start_iso[:16].replace("Z", ""), "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None
    en = st + timedelta(hours=hours)
    q = {"action": "TEMPLATE", "text": title, "dates": f"{st:%Y%m%dT%H%M00Z}/{en:%Y%m%dT%H%M00Z}",
         "details": details, "location": loc or ""}
    return "https://calendar.google.com/calendar/render?" + "&".join(f"{k}={quote(str(v))}" for k, v in q.items())


def _grade_ledger(ledger, d):
    by = {}
    for bg in d["belt_games"]:
        if bg.get("holder"):
            by[f"{bg['holder']}|{bg['opponent']}|{bg['date']}"] = bg["new_holder"] if not bg["outcome"].endswith("(tie)") else "tie"
    w = l = 0
    for x in ledger:
        res = by.get(x["key"])
        if res and x.get("pick"):
            if res == x["pick"] or (res == "tie" and x["pick"] == x["holder"]):
                w += 1
            else:
                l += 1
    return w, l


def build_preview(lg, d):
    rel = "next/"
    pv, ng, cur = d.get("preview"), d.get("next_game"), d["current"]
    n, sn = lg["team_name"], lg["short_name"]
    if not (pv and ng):
        body = f"""{S.subnav(lg, "next")}
<section class="wrap prose block"><div class="kicker">Next title defense</div><h1 class="disp">No defense scheduled yet</h1>
<p>{e(cur['name'])} {verb(lg, 'hold', 'holds')} the {e(lg['name'])} belt. {verb(lg, 'Their', 'Its')} next game isn't on the schedule yet ({e((d.get('status') or '').lower())}); this page fills in as soon as it is.</p>
<p><a href="{b(lg)}/">Back to the {e(lg['name'])} belt →</a></p></section>"""
        page(lg, f"Next {lg['name']} belt defense", body, rel, f"Preview of the next lineal {lg['name']} championship title defense.")
        return
    x, folder = _extra(lg)
    key = f"{ng['holder']}|{ng['challenger']}|{ng['date']}"
    if x.get("key") != key:
        x = {}
    espn = x.get("espn") or {}
    wx = x.get("weather")
    ai = x.get("ai")
    start = x.get("start_utc")
    h, c = pv["holder"], pv["challenger"]
    where = "vs." if ng["holder_home"] or ng.get("neutral") else "at"
    home_word = "vs" if ng["holder_home"] else "at"
    teams = espn.get("teams") or {}

    def side(code, role):
        p, s2 = lg["team_colors"](code)
        top, bottom, ink, accent = S.plate(p, s2)
        info = teams.get(str(code)) or {}
        logo = (f'<img class="mlogo" src="{e(info["logo"])}" alt="" loading="lazy" onerror="this.outerHTML=\'<span class=mlogo>{_monogram(n(code))}</span>\'">'
                if info.get("logo") else f'<span class="mlogo">{e(_monogram(n(code)))}</span>')
        form = pv["holder_form"] if code == h else pv["challenger_form"]
        wins = sum(1 for r in form if r["result"] == "W")
        losses = sum(1 for r in form if r["result"] == "L")
        last = form[0] if form else None
        last_txt = ""
        if last:
            verb_ = {"W": "def.", "L": "lost to", "T": "tied"}[last["result"]]
            last_txt = f" · Last: {verb_} {e(last['opp_name'])} {e(last['score'])}"
        rank = f'<span class="mrank mono">No. {info["rank"]}</span>' if info.get("rank") else ""
        rec = f'<span class="mrank mono">{e(info["record"])}</span>' if info.get("record") and not info.get("rank") else ""
        if role == "holder":
            kick = f"Holder · {S.ordinal(cur['reign_no'])} reign · {S.plural(cur.get('defenses', 0), 'defense')}"
        else:
            clr = pv.get("challenger_last_reign")
            kick = "Challenger · " + (f"last held {(clr.get('end') or clr['start'])[:4]}" if clr else "never held it")
        loc = _location(lg, code)
        big = sn(code)
        return f"""<div class="mside" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="kicker">{e(kick)}</div>
  <div class="mname">{logo}<div>{f'<span class="mono mloc">{e(loc)}</span>' if loc else ''}<b class="disp" style="--fit:{max(len(w) for w in big.split())}">{e(big)}</b>{rank}{rec}</div></div>
  <p class="mono mform">{wins}–{losses} in the last {len(form)}{last_txt}</p>
</div>"""

    venue = (espn.get("venue") or {})
    vname = venue.get("name") or ng.get("stadium") or ng.get("venue")
    vcity = ", ".join(v for v in (venue.get("city"), venue.get("state")) if v) or ng.get("city")
    tv = " · ".join(espn.get("tv") or [])
    time_el = (f'<span class="localtime" data-utc="{e(start)}">{S.kickoff_12h(ng.get("kickoff"))} ET</span>' if start
               else e(S.kickoff_12h(ng.get("kickoff"))))
    mid = f"""<div class="mmid">
  <div class="kicker">Belt on the line</div>
  <b class="disp mday">{S.weekday(ng['date']).upper()}</b>
  <span>{S.d_long(ng['date'])}</span>
  {f'<span>{e(vname)}{", " + e(vcity) if vcity and vcity not in (vname or "") else ""}</span>' if vname else ''}
  {f'<span class="mono mtv">{e(tv)}</span>' if tv else ''}
  <span class="mono mtime">{time_el}</span>
</div>"""
    hero = f'<section class="mhero wrap">{side(h, "holder")}{mid}{side(c, "challenger")}</section>'

    # what's at stake
    reign_days = (date.fromisoformat(ng["date"]) - date.fromisoformat(pv.get("holder_reign_start") or cur["start_date"])).days
    next_def = pv["holder_streak"] + 1
    bm = [bg for bg in d["belt_games"] if bg.get("holder") and {bg["holder"], bg["opponent"]} == {h, c}]
    bm_h = sum(1 for bg in bm if bg["new_holder"] == h and not bg["outcome"].endswith("(tie)"))
    bm_c = sum(1 for bg in bm if bg["new_holder"] == c and not bg["outcome"].endswith("(tie)"))
    c_reign_no = pv["challenger_reigns"] + 1
    cells = [
        (f"If {sn(h)} {verb(lg, 'win', 'wins')}", f"{S.ordinal(next_def)} defense · reign reaches {reign_days:,} days"),
        (f"If {sn(c)} {verb(lg, 'win', 'wins')}", "Belt changes hands · " + (f"{sn(c)}’s {S.ordinal(c_reign_no)} reign" if pv["challenger_reigns"] else f"first reign in {'program' if lg.get('singular') else 'franchise'} history")),
        ("Head to head, belt games", (f"Met {S.plural(len(bm), 'time')} · {sn(h)} {bm_h}, {sn(c)} {bm_c}" if bm else "First belt game between these two")),
    ]
    if wx and wx.get("temp_f") is not None:
        cells.append(("Kickoff weather" if lg.get("key") == "nfl" else "First-pitch weather",
                       f"{wx['temp_f']}°F · {(wx.get('condition') or '').lower()} · wind {wx.get('wind_mph')} mph · {wx.get('precip_chance')}% rain<small class='mono'>forecast as of {wx.get('as_of')}</small>"))
    else:
        rec = lambda r: f"{r['W']}–{r['L']}" + (f"–{r['T']}" if r.get("T") else "")
        cells.append((f"{sl(lg, pv['record_season'])} records", f"{sn(h)} {rec(pv['holder_record'])} · {sn(c)} {rec(pv['challenger_record'])}"))
    stakes = "".join(f'<div><span class="kicker">{e(k)}</span><p>{v if "<small" in v else e(v)}</p></div>' for k, v in cells)

    # odds line
    m = d.get("models") or {}
    odds_bits = []
    if pv.get("holder_win_prob") is not None:
        odds_bits.append(f'<b>{pct(pv["holder_win_prob"])}</b> to defend, per our Elo estimate')
    look = m.get("outlook")
    if look:
        oh = dict(look["odds"]).get(h, 0)
        odds_bits.append(f'<b>{pct(oh)}</b> to hold the belt through the regular season (<a href="{b(lg)}/outlook/">outlook</a>)')
    o = espn.get("odds") or {}
    if o.get("details"):
        odds_bits.append(f'line <b>{e(o["details"])}</b>' + (f', O/U {e(str(o["over_under"]))}' if o.get("over_under") else "")
                         + (f' ({e(o["provider"])})' if o.get("provider") else ""))
    elif ng.get("spread") is not None:
        fav = ng["home"] if ng["spread"] > 0 else ng["away"]
        odds_bits.append(f'line <b>{e(sn(fav))} −{abs(ng["spread"]):g}</b>' if ng["spread"] else "line <b>pick ’em</b>")
    oddsline = f'<p class="oddsline mono">{" · ".join(odds_bits)}</p>' if odds_bits else ""

    # beat the lean
    results = {}
    for bg in d["belt_games"][-120:]:
        if bg.get("holder"):
            results[f"{bg['holder']}|{bg['opponent']}|{bg['date']}"] = bg["new_holder"]
    ledger = _ledger(folder)
    lw, ll = _grade_ledger(ledger, d)
    lean_rec = f" The lean is {lw}–{ll} on {e(lg['name'])} belt games so far." if lw + ll else ""
    lean_pick = ""
    if ai and ai.get("predicted_winner"):
        lean_pick = f' The lean says <b>{e(ai["predicted_winner"])}</b>.'
    lk = lg.get("key", "cbb")
    beat = f"""<section class="wrap"><div class="lean">
  <div class="kicker">Beat the lean</div>
  <div class="leanbtns"><button class="mono" data-p="{h}">{e(sn(h))} {verb(lg, 'keep', 'keeps')} it</button><button class="mono" data-p="{c}">{e(sn(c))} {verb(lg, 'take', 'takes')} it</button></div>
  <p class="note" id="leannote">Pick before {'kickoff' if lk == 'nfl' else 'first pitch' if lk == 'mlb' else 'puck drop' if lk == 'nhl' else 'tipoff'}. We grade it after the game.{lean_pick}{lean_rec}</p>
</div></section>
<script>
(function(){{
var K='belt-picks-{lk}',G={json.dumps(key)},R={json.dumps(results, separators=(",", ":"))},N={json.dumps({h: sn(h), c: sn(c)})};
var P={{}};try{{P=JSON.parse(localStorage.getItem(K)||'{{}}');}}catch(e){{}}
var btns=document.querySelectorAll('.leanbtns button'),note=document.getElementById('leannote'),base=note.innerHTML;
function show(){{
 btns.forEach(function(b){{b.classList.toggle('on',P[G]===b.dataset.p);}});
 var w=0,l=0;Object.keys(P).forEach(function(k){{if(R[k]){{if(R[k]===P[k])w++;else l++;}}}});
 note.innerHTML=(P[G]?'Your pick: <b>'+N[P[G]]+'</b>. You can change it until the game starts. ':'')+base+(w+l?' Your record: <b>'+w+'–'+l+'</b>.':'');
}}
btns.forEach(function(b){{b.onclick=function(){{P[G]=b.dataset.p;try{{localStorage.setItem(K,JSON.stringify(P));}}catch(e){{}}show();}};}});
show();
}})();
</script>"""

    # the article (AI) or a stats summary
    verbw = "travel to" if not lg.get("singular") else "travels to"
    head = (f"{n(h)} {'host' if not lg.get('singular') else 'hosts'} {n(c)} with the belt on the line" if ng["holder_home"] and not ng.get("neutral")
            else f"{n(h)} {verbw if not ng.get('neutral') else ('meet' if not lg.get('singular') else 'meets')} {n(c)} with the belt on the line")
    if ai and ai.get("overview"):
        km = "".join(f"<li>{e(k)}</li>" for k in ai.get("key_matchups") or [])
        article = f"""<article class="pv-article">
  <div class="kicker">The preview · AI-written</div>
  <h2 class="disp">{e(head)}</h2>
  <p>{e(ai['overview'])}</p>
  {f'<h3 class="kicker">Worth watching</h3><ul>{km}</ul>' if km else ''}
  {f'<h3 class="kicker">The numbers</h3><p>{e(ai["betting_angles"])}</p>' if ai.get('betting_angles') else ''}
  {f'''<div class="leanbox"><div class="kicker">The lean</div><b class="disp">{e(ai["predicted_score"])}</b><p>{e(ai.get("prediction_writeup") or "")}</p>
  <p class="note">Written by Claude from the stats on this page: a for-fun editorial call, not betting advice or a guarantee. If it stops being fun, the National Problem Gambling Helpline is 1-800-522-4700.</p></div>''' if ai.get('predicted_score') else ''}
</article>"""
    else:
        h2h = pv["h2h"]
        lead = (f"{n(h)} {verb(lg, 'lead', 'leads')} the all-time series {h2h['holder_wins']}–{h2h['challenger_wins']}" if h2h["holder_wins"] > h2h["challenger_wins"]
                else f"{n(c)} {verb(lg, 'lead', 'leads')} the all-time series {h2h['challenger_wins']}–{h2h['holder_wins']}" if h2h["challenger_wins"] > h2h["holder_wins"]
                else f"the all-time series is even at {h2h['holder_wins']}" if h2h["games"] else "they've never met")
        article = f"""<article class="pv-article">
  <div class="kicker">The preview</div>
  <h2 class="disp">{e(head)}</h2>
  <p>{e(n(h))} {verb(lg, 'put', 'puts')} the {e(lg['name'])} belt on the line for the {S.ordinal(next_def)} time this reign. {e(lead[0].upper() + lead[1:])}{', and ' + e(sn(c)) + (' have' if not lg.get('singular') else ' has') + (' never held the belt' if not pv['challenger_reigns'] else ' held it ' + S.plural(pv['challenger_reigns'], 'time') + ' before') }.</p>
</article>"""

    def form_col(code, rows):
        info = teams.get(str(code)) or {}
        logo = f'<img src="{e(info["logo"])}" alt="" loading="lazy">' if info.get("logo") else ""
        lis = "".join(f'<li><span class="wl {r["result"]}">{r["result"]}</span><b class="mono">{e(r["score"])}</b>'
                      f'<span>{"vs" if r["home"] else "at"} {e(r["opp_name"])}{" · playoffs" if r.get("postseason") else ""}</span>'
                      f'<span class="mono d">{S.d_short(r["date"], True)}</span></li>' for r in rows)
        return f'<div><h3 class="fhead">{logo}{e(n(code))}</h3><ul class="frows">{lis}</ul></div>'

    form = f"""<section class="pv-sec"><div class="kicker">Recent form</div><h2 class="disp">Last {max(len(pv['holder_form']), len(pv['challenger_form']))} games</h2>
  <div class="formcols">{form_col(h, pv['holder_form'])}{form_col(c, pv['challenger_form'])}</div></section>"""
    h2h = pv["h2h"]
    mt = pv.get("meetings") or []
    mrows = "".join(f'<tr><td class="mono">{S.d_short(x["date"], True)}</td><td>{e(n(x["away"], x["season"]))} {"vs." if x.get("neutral") else "at"} {e(n(x["home"], x["season"]))}{" · playoffs" if x.get("postseason") else ""}</td>'
                    f'<td class="mono r">{x["ap"]}–{x["hp"]}{(" " + e(x["note"])) if x.get("note") else ""}</td></tr>' for x in mt)
    series = (f"{e(n(h))} {verb(lg, 'lead', 'leads')} the series {h2h['holder_wins']}–{h2h['challenger_wins']}" if h2h["holder_wins"] > h2h["challenger_wins"]
              else f"{e(n(c))} {verb(lg, 'lead', 'leads')} the series {h2h['challenger_wins']}–{h2h['holder_wins']}" if h2h["challenger_wins"] > h2h["holder_wins"]
              else f"The series is tied {h2h['holder_wins']}–{h2h['challenger_wins']}")
    h2h_html = (f"""<section class="pv-sec"><div class="kicker">Head to head</div><h2 class="disp">All-time series</h2>
  <p class="intro">{series}{f", {h2h['ties']} ties" if h2h.get('ties') else ""}, going back to {S.d_long(h2h['first'])}.</p>
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Date</th><th class="mono">Matchup</th><th class="mono r">Score (away–home)</th></tr></thead><tbody>{mrows}</tbody></table></div></section>"""
                if h2h["games"] else f'<section class="pv-sec"><div class="kicker">Head to head</div><h2 class="disp">First meeting</h2><p class="intro">{e(n(h))} and {e(n(c))} have never played.</p></section>')

    # sidebar
    title = f"{lg['name']} belt: {sn(h)} {where} {sn(c)}"
    gcal = _gcal(title, start, 3, f"{n(h)} defend the lineal {lg['name']} belt. {S.SITE_URL}{b(lg)}/next/", ", ".join(v for v in (vname, vcity) if v)) if start else None
    webcal = f"webcal://{S.SITE_URL.split('//')[1]}{b(lg)}/belt.ics"
    clr = pv.get("challenger_last_reign")
    last_held = (clr.get("end") or clr["start"])[:4] if clr else "Never"
    c_days = pv.get("challenger_days", 0)
    c_def = pv.get("challenger_defenses", 0)
    c_sent = (f"{e(n(c))} {verb(lg, 'have', 'has')} held the belt {S.plural(pv['challenger_reigns'], 'time')} for {c_days:,} days in total, most recently in {last_held}. "
              f"With it in hand: {S.plural(c_def, 'successful defense')}." if pv["challenger_reigns"]
              else f"{e(n(c))} {verb(lg, 'have', 'has')} never held the {e(lg['name'])} belt. A win would be the first reign ever.")
    bm_line = (f"Met {S.plural(len(bm), 'time')} with the belt on the line: {e(sn(h))} {bm_h}, {e(sn(c))} {bm_c}. Last: {S.d_long(bm[-1]['date'])}."
               if bm else "These two have never met with the belt on the line.")
    aside = f"""<aside class="pv-aside">
  <div class="acard"><div class="kicker">Don’t miss it</div>
    {f'<a class="abtn mono" href="{e(gcal)}" target="_blank" rel="noopener">+ Google Calendar</a>' if gcal else ''}
    <a class="abtn mono" href="{b(lg)}/belt.ics">↓ Download .ics (Apple / Outlook)</a>
    <p class="note"><a href="{webcal}">Subscribe to the belt calendar</a>: it updates itself and follows the belt when it changes hands.</p>
    <a class="abtn mono" href="#alerts">Email me if it changes hands</a>
  </div>
  <div class="acard"><div class="kicker">Belt history between these two</div><p>{bm_line}</p><a class="mono more" href="{b(lg)}/compare/?a={h}&amp;b={c}">Full comparison →</a></div>
  <div class="acard"><div class="kicker">{e(n(c))} &amp; the belt</div>
    <div class="anums"><div><b class="disp">{pv['challenger_reigns']}</b><span class="mono">Reigns</span></div><div><b class="disp">{c_days:,}</b><span class="mono">Days held</span></div><div><b class="disp">{last_held}</b><span class="mono">Last held</span></div></div>
    <p>{c_sent}</p><a class="mono more" href="{team_url(lg, c)}">Team page →</a></div>
</aside>"""
    crumbs_html = f'<nav class="crumbs mono wrap"><a href="{b(lg)}/">{e(lg["name"])} belt</a> / <a href="{b(lg)}/seasons/">{e(sl(lg, ng.get("season") or pv.get("record_season")))}</a> / Up next</nav>'
    body = f"""{S.subnav(lg, "next")}
{live_box(lg, d)}
{crumbs_html}
<h1 class="sr">Up next: {e(n(h))} {where} {e(n(c))}, {S.d_long(ng['date'])}. The {e(lg['name'])} belt is on the line</h1>
{hero}
<section class="wrap"><div class="stakes">{stakes}</div>{oddsline}</section>
{beat}
<section class="wrap pv-grid"><div>{article}{form}{h2h_html}</div>{aside}</section>
{next_extras(lg, d)}
<script>
document.querySelectorAll('.localtime').forEach(function(el){{try{{var d=new Date(el.dataset.utc.length===17?el.dataset.utc.replace('Z',':00Z'):el.dataset.utc);if(isNaN(d))return;
el.textContent=d.toLocaleTimeString([],{{hour:'numeric',minute:'2-digit',timeZoneName:'short'}})+' your time';}}catch(e){{}}}});
</script>"""
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{n(h)} {where} {n(c)}",
          "startDate": start or ng["date"], "sport": lg.get("sport", ""),
          "location": {"@type": "Place", "name": vname or "", "address": vcity or ""},
          "competitor": [{"@type": "SportsTeam", "name": n(h)}, {"@type": "SportsTeam", "name": n(c)}]}
    page(lg, f"{sn(h)} {where} {sn(c)} preview: {lg['name']} belt on the line {S.d_short(ng['date'])}", body, rel,
         f"{n(h)} defend the lineal {lg['name']} championship belt {where} {n(c)} on {S.d_long(ng['date'])}: odds, the lean, recent form, head to head and what's at stake.",
         jsonld=ld)
