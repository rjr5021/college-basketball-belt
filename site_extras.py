"""
The deeper belt pages, built from each belt's lineage.json. SHARED FILE: it must stay
byte-identical in rjr5021/belt-holders and rjr5021/college-basketball-belt (NET-1).
Site differences come from the league dicts and from optional attributes on the
build_site module (SITE_NAME, NETWORK, otd_description, search_description, P).
Paths below are relative to each belt's base: /<lg> on Belt Holders, / or /women
on the College Basketball Belt.

    /<lg>/seasons/ and /<lg>/seasons/<year>/   the belt's path through every season
    /<lg>/reigns/<n>/                          notable reigns (5+ defenses, or current)
    /<lg>/rivalries/ and /<lg>/rivalries/<a>-vs-<b>/   every pair with 5+ belt meetings
    /<lg>/compare/                             any two teams (client-side)
    /<lg>/next/                                preview of the next title defense
    /on-this-day/ and /on-this-day/<mm-dd>/    title changes on each calendar date
    /stories/ and /stories/<slug>/             data-driven long reads
    /search/                                   find a team or season

build_site.py calls build_all(datas) after its own pages.
"""

import json
from collections import Counter, defaultdict
from datetime import date

import build_site as S
import features as F

try:                                  # Belt Holders: every league in the registry
    from leagues import LIVE as _LIVE
except ImportError:                   # College Basketball Belt: build_site points this at the belt being built
    from cbb_league import LIVE as _LIVE
LIVE = list(_LIVE)

e = S.e
REIGN_MIN_DEFENSES = 5
RIVALRY_MIN = 5
MONTHS_LONG = S.MONTHS_LONG


def base(lg):
    """URL prefix of a belt's pages: "/nfl" on Belt Holders, "" or "/women" on the CBB site."""
    return lg["base"] if "base" in lg else "/" + lg["key"]


def out(lg, rel):
    pre = base(lg).strip("/")
    return f"{pre}/{rel}" if pre else rel


def unit1(lg):
    """One team, in the belt's own word: franchise, club, program."""
    return lg.get("unit_one", "franchise")


def _fit(long_title, short_title, limit=50):
    """The long title when it leaves room for the site suffix, else the short-name version (BH-10)."""
    return long_title if len(long_title) <= limit else short_title


def vb(lg, plural_form, singular_form):
    """Verb agreement: college names are singular ("Michigan holds"), team nicknames plural ("the Bengals hold")."""
    return singular_form if lg.get("singular") else plural_form


def post_word(lg):
    return lg.get("post_tag", "playoffs")


def site_name():
    return getattr(S, "SITE_NAME", "Belt Holders")


# --------------------------------------------------------------- helpers --

def sl(lg, season):
    fn = lg.get("season_label")
    return fn(season) if fn else str(season)


def season_url(lg, season, n=None):
    return f"{base(lg)}/seasons/{season}/" + (f"#g{n}" if n else "")


def notable(r, cur_index):
    return r.get("defenses", 0) >= REIGN_MIN_DEFENSES or r["index"] == cur_index


def reign_url(lg, d, r):
    return F.reign_link(lg, d, r)


def team_link(lg, code, season=None):
    name = lg["team_name"](code, season) if season is not None else lg["team_name"](code)
    if not F.has_team_page(lg, code):
        return e(name)
    return f'<a href="{base(lg)}/teams/{S.slug(lg["team_name"](code))}/">{e(name)}</a>'


def rivalry_slug(lg, a, b):
    x, y = sorted((S.slug(lg["team_name"](a)), S.slug(lg["team_name"](b))))
    return f"{x}-vs-{y}"


def score_for(bg, team):
    hp, ap = (int(x) for x in bg["score"].split("-"))
    mine, theirs = (hp, ap) if bg["home"] == team else (ap, hp)
    return mine, theirs


def game_line(lg, bg, link_teams=True):
    """'Pittsburgh Steelers beat Atlanta Falcons 20–13 (OT)' from the belt's point of view."""
    s = bg["season"]
    tl = (lambda c: team_link(lg, c, s)) if link_teams else (lambda c: e(lg["team_name"](c, s)))
    note = f" ({e(bg['note'])})" if bg.get("note") else ""
    if not bg.get("holder"):
        w = bg["new_holder"]
        m, t = score_for(bg, w)
        return f"{tl(w)} beat {tl(bg['opponent'])} {m}–{t}{note} in the first game"
    h, o = bg["holder"], bg["opponent"]
    m, t = score_for(bg, h)
    if bg["outcome"] == "changed":
        return f"{tl(o)} beat {tl(h)} {t}–{m}{note}"
    if bg["outcome"].endswith("(tie)"):
        return f"{tl(h)} and {tl(o)} tied {m}–{t}{note}"
    return f"{tl(h)} beat {tl(o)} {m}–{t}{note}"


def tag(bg):
    if bg["outcome"] == "changed":
        return '<span class="tag chg">Title change</span>'
    if bg["outcome"] == "established":
        return '<span class="tag chg">First holder</span>'
    if bg["outcome"].endswith("(tie)"):
        return '<span class="tag">Tie · defense</span>'
    return '<span class="tag">Defense</span>'


def games_table(lg, bgs, anchors=True):
    rows = []
    for bg in bgs:
        p, _ = lg["team_colors"](bg["new_holder"])
        post = f' <span class="tag post">{post_word(lg).capitalize()}</span>' if bg["season_type"] != "regular" else ""
        rows.append(f'<tr{(" id=g" + str(bg["n"])) if anchors else ""}><td class="mono n">{bg["n"]:,}</td>'
                    f'<td class="mono">{S.d_short(bg["date"], True)}</td>'
                    f'<td><i style="background:{p}"></i>{game_line(lg, bg)}{post}</td><td class="r">{tag(bg)}</td></tr>')
    return ('<div class="tablewrap"><table class="history games"><thead><tr><th class="mono">Belt game</th>'
            '<th class="mono">Date</th><th class="mono">Result</th><th class="mono r"></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def crumbs(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": S.SITE_URL + u}
                                for i, (n, u) in enumerate(items)]}


def strip(lg, codes, season):
    chips = "".join(f'<span class="chip" style="--c:{lg["team_colors"](c)[0]}">{e(lg["short_name"](c))}</span>' for c in codes)
    return f'<div class="strip">{chips}</div>'


# --------------------------------------------------------------- seasons --

def build_seasons(lg, d):
    key = lg["key"]
    seasons = d["seasons"]
    bgs_by_season = defaultdict(list)
    for bg in d["belt_games"]:
        bgs_by_season[bg["season"]].append(bg)
    rows, last_dec = [], None
    for s in reversed(seasons):
        dec = s["season"] // 10 * 10
        if dec != last_dec:
            rows.append(f'<tr class="dec"><th colspan="5" class="disp">{dec}s</th></tr>')
            last_dec = dec
        rows.append(f'<tr><td class="mono"><a href="{season_url(lg, s["season"])}">{e(s["label"])}</a></td>'
                    f'<td>{team_link(lg, s["entering"], s["season"])}</td><td>{team_link(lg, s["ending"], s["season"])}</td>'
                    f'<td class="mono r">{s["changes"]}</td><td class="mono r">{s["games"]}</td></tr>')
    body = f"""{S.subnav(lg, "seasons")}
<section class="wrap block">
  <div class="head"><h1 class="disp">{lg['name']} belt, season by season</h1><span class="mono note">{len(seasons)} seasons</span></div>
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Season</th><th class="mono">Entered with it</th><th class="mono">Finished with it</th><th class="mono r">Changes</th><th class="mono r">Belt games</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table></div>
</section>"""
    S.write(out(lg, "seasons/index.html"), S.page(f"{lg['long_name']}: every season", body, path=f"{base(lg)}/seasons/", active=key,
                                                 description=f"The lineal {lg['name']} championship belt season by season since {lg['first_season']}: who carried it in, who finished with it, and how often it moved."))
    for i, s in enumerate(seasons):
        bgs = bgs_by_season[s["season"]]
        prev_s = seasons[i - 1] if i else None
        next_s = seasons[i + 1] if i + 1 < len(seasons) else None
        n = lg["team_name"]
        summ = (f"{e(n(s['entering'], s['season']))} carried the belt into the {e(s['label'])} season. "
                f"It changed hands {S.plural(s['changes'], 'time')} among {S.plural(s['distinct_holders'], unit1(lg))}"
                + (f", {s['postseason_changes']} of those in the playoffs" if s["postseason_changes"] else "")
                + f", and {e(n(s['ending'], s['season']))} {'hold' if s['in_progress'] else 'finished the season with'} it.")
        if s["most_defenses"]["team"] and s["most_defenses"]["defenses"]:
            summ += f" Most defenses: {e(n(s['most_defenses']['team'], s['season']))}, {s['most_defenses']['defenses']}."
        prev_link = f'<a href="{season_url(lg, prev_s["season"])}">← {e(prev_s["label"])}</a>' if prev_s else "<span></span>"
        next_link = f'<a href="{season_url(lg, next_s["season"])}">{e(next_s["label"])} →</a>' if next_s else "<span></span>"
        nav = f'<nav class="pager mono">{prev_link}<a href="{base(lg)}/seasons/">All seasons</a>{next_link}</nav>'
        body = f"""{S.subnav(lg, "seasons")}
<section class="wrap block">
  <div class="kicker">{lg['long_name']} · season</div>
  <div class="head"><h1 class="disp">The {e(s['label'])} season</h1><span class="mono note">{S.plural(s['games'], 'belt game')} · {S.plural(s['changes'], 'title change')}</span></div>
  <p class="intro">{summ}</p>
  <h2 class="disp sub">Who held it, in order</h2>
  {strip(lg, s['holders'], s['season'])}
  <h2 class="disp sub">Every belt game</h2>
  {games_table(lg, bgs)}
  {nav}
</section>"""
        ld = crumbs([(lg["long_name"], f"{base(lg)}/"), ("Seasons", f"{base(lg)}/seasons/"), (s["label"], season_url(lg, s["season"]))])
        S.write(out(lg, f"seasons/{s['season']}/index.html"),
                S.page(f"{s['label']} {lg['name']} belt season", body, og_title=f"{s['label']} {lg['name']} season: the lineal championship belt", path=season_url(lg, s["season"]), active=key, jsonld=ld,
                       description=f"Every {lg['name']} belt game in {s['label']}: {n(s['entering'], s['season'])} carried it in, it changed hands {s['changes']} times, and {n(s['ending'], s['season'])} {'hold' if s['in_progress'] else 'finished with'} it."))


# ---------------------------------------------------------------- reigns --

def build_reigns(lg, d):
    key = lg["key"]
    reigns = d["reigns"]
    cur = reigns[-1]["index"]
    for i, r in enumerate(reigns):
        if not notable(r, cur):
            continue
        p, s = lg["team_colors"](r["team"])
        top, bottom, ink, accent = S.plate(p, s)
        bgs = [d["_bg"][n] for n in ([r["opened_by"]] if r.get("opened_by") else []) + r.get("belt_games", []) if n in d["_bg"]]
        start = (f"Took the belt from {team_link(lg, r['won_from'], r['season'])}, {S.won_score_text(r)}, on {S.d_long(r['start_date'])}."
                 if r.get("won_from") else (f"Reclaimed the belt on {S.d_long(r['start_date'])}." if r.get("reclaimed_after") else f"Won the first game on {S.d_long(r['start_date'])}."))
        if r.get("end_date") and r.get("lost_to"):
            last = bgs[-1] if bgs else None
            end = f"Lost it to {team_link(lg, r['lost_to'], r.get('end_season') or r['season'])}" + (f", {score_for(last, r['lost_to'])[0]}–{score_for(last, r['lost_to'])[1]}" if last and last['outcome'] == 'changed' else "") + f", on {S.d_long(r['end_date'])}."
        elif r.get("end_date"):
            end = f"The reign ended on {S.d_long(r['end_date'])} when {lg.get('leave_text', 'the franchise stopped playing')}."
        else:
            end = "Still holding."
        prev_r = reigns[i - 1] if i else None
        next_r = reigns[i + 1] if i + 1 < len(reigns) else None
        nav = '<nav class="pager mono">' + (f'<a href="{reign_url(lg, d, prev_r)}">← Previous reign: {e(prev_r["name"])}</a>' if prev_r else "<span></span>") + \
              (f'<a href="{reign_url(lg, d, next_r)}">Next reign: {e(next_r["name"])} →</a>' if next_r else "<span></span>") + "</nav>"
        body = f"""{S.subnav(lg, "history")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">{lg['long_name']} · reign {r['index']:,}</div>
    <h1 class="disp holder" style="{S.fit(r['name'])}">{e(r['name'])}</h1>
    <p class="lede">{start} {end}</p>
    <div class="stats"><div><b class="disp">{r.get('defenses', 0)}</b><span class="mono">Defenses</span></div><div><b class="disp">{r['days']:,}</b><span class="mono">Days</span></div><div><b class="disp">{S.ordinal(r['reign_no'])}</b><span class="mono">Reign for the {unit1(lg)}</span></div></div>
  </div>
</section>
<section class="wrap block"><div class="head"><h2 class="disp">Every game of the reign</h2></div>{games_table(lg, bgs, anchors=False)}{nav}</section>"""
        ld = crumbs([(lg["long_name"], f"{base(lg)}/"), ("History", f"{base(lg)}/history/"), (f"{r['name']} reign", f"{base(lg)}/reigns/{r['index']}/")])
        yr = r["start_date"][:4]
        S.write(out(lg, f"reigns/{r['index']}/index.html"),
                S.page(f"{F.poss(r['name'].split(' (')[0])} {r.get('defenses', 0)}-defense belt reign ({yr})", body, path=f"{base(lg)}/reigns/{r['index']}/", active=key, jsonld=ld,
                       description=f"{r['name']} held the lineal {lg['name']} championship belt for {S.plural(r['days'], 'day')} and {S.plural(r.get('defenses', 0), 'defense')} starting {S.d_long(r['start_date'])}. Every game of the reign."))


# ------------------------------------------------------------- rivalries --

def build_rivalries(lg, d):
    key = lg["key"]
    rivals = [p for p in d["rivalries"] if p["meetings"] >= RIVALRY_MIN]
    n = lg["team_name"]
    rows = []
    for p in rivals:
        url = f"{base(lg)}/rivalries/{rivalry_slug(lg, p['a'], p['b'])}/"
        rows.append(f'<tr><td><a href="{url}">{e(n(p["a"]))} vs. {e(n(p["b"]))}</a></td><td class="mono r">{p["meetings"]}</td>'
                    f'<td class="mono r">{p["a_wins"]}–{p["b_wins"]}{("–" + str(p["ties"])) if p["ties"] else ""}</td><td class="mono r">{p["changes"]}</td>'
                    f'<td class="mono r">{p["last"][:4]}</td></tr>')
        bgs = [d["_bg"][x] for x in p["games"] if x in d["_bg"]]
        ca, cb = lg["team_colors"](p["a"])[0], lg["team_colors"](p["b"])[0]
        lead = p["a"] if p["a_wins"] > p["b_wins"] else p["b"] if p["b_wins"] > p["a_wins"] else None
        intro = (f"{e(n(p['a']))} and {e(n(p['b']))} have met {S.plural(p['meetings'], 'time')} with the {lg['name']} belt on the line, "
                 f"from {S.d_long(p['first'])} to {S.d_long(p['last'])}. The belt changed hands in {S.plural(p['changes'], 'of those games', 'of those games')}. "
                 + (f"{e(n(lead))} {vb(lg, 'lead', 'leads')} the belt series {max(p['a_wins'], p['b_wins'])}–{min(p['a_wins'], p['b_wins'])}" if lead else f"The belt series is level at {p['a_wins']}–{p['b_wins']}")
                 + (f", with {S.plural(p['ties'], 'tie')}." if p["ties"] else "."))
        body = f"""{S.subnav(lg, "rivalries")}
<section class="wrap block">
  <div class="kicker">{lg['long_name']} · rivalry</div>
  <div class="head"><h1 class="disp"><span style="border-bottom:6px solid {ca}">{e(n(p['a']))}</span> vs. <span style="border-bottom:6px solid {cb}">{e(n(p['b']))}</span></h1></div>
  <div class="numbers">
    <div><b class="disp">{p['meetings']}</b><span class="mono">Belt meetings</span></div>
    <div><b class="disp">{p['a_wins']}</b><span class="mono">{e(lg['short_name'](p['a']))} wins</span></div>
    <div><b class="disp">{p['b_wins']}</b><span class="mono">{e(lg['short_name'](p['b']))} wins</span></div>
    <div><b class="disp">{p['changes']}</b><span class="mono">Title changes</span></div>
  </div>
  <p class="intro">{intro}</p>
  {games_table(lg, bgs, anchors=False)}
  <p class="mono more"><a href="{base(lg)}/compare/?a={p['a']}&amp;b={p['b']}">Compare these two →</a> · <a href="{base(lg)}/rivalries/">All rivalries →</a></p>
</section>"""
        ld = crumbs([(lg["long_name"], f"{base(lg)}/"), ("Rivalries", f"{base(lg)}/rivalries/"), (f"{n(p['a'])} vs. {n(p['b'])}", url)])
        S.write(out(lg, f"rivalries/{rivalry_slug(lg, p['a'], p['b'])}/index.html"),
                S.page(_fit(f"{n(p['a'])} vs. {n(p['b'])}: {F.belt_tag(lg)} rivalry", f"{lg['short_name'](p['a'])} vs. {lg['short_name'](p['b'])}: {F.belt_tag(lg)} rivalry"), body, og_title=f"{n(p['a'])} vs. {n(p['b'])}: {lg['name']} belt rivalry", path=url, active=key, jsonld=ld,
                       description=f"{n(p['a'])} vs. {n(p['b'])} with the lineal {lg['name']} championship on the line: {p['meetings']} meetings, {p['changes']} title changes, every game."))
    body = f"""{S.subnav(lg, "rivalries")}
<section class="wrap block">
  <div class="head"><h1 class="disp">{lg['name']} belt rivalries</h1><span class="mono note">{len(rivals)} pairs with {RIVALRY_MIN}+ belt meetings</span></div>
  <p class="intro">The matchups that have decided the {lg['name']} belt most often. Want a pair that isn't here? <a href="{base(lg)}/compare/">Compare any two teams</a>.</p>
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Matchup</th><th class="mono r">Meetings</th><th class="mono r">Wins (W–L{'–T' if any(p['ties'] for p in rivals) else ''})</th><th class="mono r">Title changes</th><th class="mono r">Last</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table></div>
</section>"""
    S.write(out(lg, "rivalries/index.html"), S.page(f"{lg['name']} belt rivalries", body, path=f"{base(lg)}/rivalries/", active=key,
                                                  description=f"The rivalries that decided the lineal {lg['name']} championship belt most often, with every belt meeting."))


# --------------------------------------------------------------- compare --

def build_compare(lg, d):
    key = lg["key"]
    teams = sorted({t for bg in d["belt_games"] for t in (bg.get("holder"), bg["opponent"]) if t},
                   key=lambda t: lg["team_name"](t))
    oc = {"changed": "c", "retained": "d", "retained (tie)": "t", "established": "c"}
    rows = [[bg["n"], bg["date"], bg.get("holder") or "", bg["opponent"], bg["score"], bg["home"], oc.get(bg["outcome"], "d"),
             bg["season"], bg.get("note") or ""] for bg in d["belt_games"] if bg.get("holder")]
    data = {"teams": {t: lg["team_name"](t) for t in teams}, "slugs": {t: S.slug(lg["team_name"](t)) for t in teams},
            "games": rows, "rivalries": [rivalry_slug(lg, p["a"], p["b"]) for p in d["rivalries"] if p["meetings"] >= RIVALRY_MIN]}
    S.write(out(lg, "compare/data.json"), json.dumps(data, separators=(",", ":")))
    opts = "".join(f'<option value="{t}">{e(lg["team_name"](t))}</option>' for t in teams)
    body = f"""{S.subnav(lg, "compare")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Compare any two teams</h1><span class="mono note">Every time they met with the {lg['name']} belt on the line</span></div>
  <form class="compare mono" onsubmit="return false">
    <label>Team A <select id="ca">{opts}</select></label>
    <label>Team B <select id="cb">{opts}</select></label>
  </form>
  <div id="cout" class="cout"><p class="intro">Pick two teams.</p></div>
</section>
<script>
(function(){{
var D=null, A=document.getElementById('ca'), B=document.getElementById('cb'), O=document.getElementById('cout');
var q=new URLSearchParams(location.search);
if(q.get('a'))A.value=q.get('a'); if(q.get('b'))B.value=q.get('b'); else if(B.options.length>1&&B.value===A.value)B.selectedIndex=1;
function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fd(d){{var p=d.split('-');return MO[+p[1]-1]+' '+(+p[2])+', '+p[0];}}
function render(){{
 if(!D)return; var a=A.value,b=B.value; if(a===b){{O.innerHTML='<p class="intro">Pick two different teams.</p>';return;}}
 var g=D.games.filter(function(r){{return (r[2]===a&&r[3]===b)||(r[2]===b&&r[3]===a);}});
 var wa=0,wb=0,t=0,ch=0,rows='';
 g.forEach(function(r){{var s=r[4].split('-').map(Number),hs=s[0],as=s[1],hw=r[5],aw=(hw===r[2]?r[3]:r[2]);
  var w=hs>as?hw:(as>hs?aw:null); if(w===a)wa++; else if(w===b)wb++; else t++; if(r[6]==='c')ch++;
  var m=w?(D.teams[w]+' won '+Math.max(hs,as)+'–'+Math.min(hs,as)):('Tied '+hs+'–'+as);
  rows='<tr><td class="mono n">'+r[0].toLocaleString()+'</td><td class="mono">'+fd(r[1])+'</td><td>'+esc(D.teams[r[2]])+' held it. '+esc(m)+(r[8]?' ('+esc(r[8])+')':'')+'</td><td class="r"><span class="tag'+(r[6]==='c'?' chg':'')+'">'+(r[6]==='c'?'Title change':'Defense')+'</span></td></tr>'+rows;}});
 var slug=[D.slugs[a],D.slugs[b]].sort().join('-vs-');
 var link=D.rivalries.indexOf(slug)>=0?'<p class="mono more"><a href="{base(lg)}/rivalries/'+slug+'/">Full rivalry page →</a></p>':'';
 O.innerHTML=g.length?('<div class="numbers"><div><b class="disp">'+g.length+'</b><span class="mono">Belt meetings</span></div><div><b class="disp">'+wa+'</b><span class="mono">'+esc(D.teams[a])+' wins</span></div><div><b class="disp">'+wb+'</b><span class="mono">'+esc(D.teams[b])+' wins</span></div><div><b class="disp">'+ch+'</b><span class="mono">Title changes</span></div></div>'+link+'<div class="tablewrap"><table class="history games"><thead><tr><th class="mono">Belt game</th><th class="mono">Date</th><th class="mono">What happened</th><th><span class="sr">Result</span></th></tr></thead><tbody>'+rows+'</tbody></table></div>'):'<p class="intro">'+esc(D.teams[a])+' and '+esc(D.teams[b])+' have never met with the belt on the line.</p>';
 history.replaceState(null,'','?a='+a+'&b='+b);
}}
A.onchange=B.onchange=render;
fetch('{base(lg)}/compare/data.json').then(function(r){{return r.json();}}).then(function(j){{D=j;render();}});
}})();
</script>"""
    S.write(out(lg, "compare/index.html"), S.page(f"Compare {lg['name']} teams: belt head-to-head", body, path=f"{base(lg)}/compare/", active=key,
                                                description=f"Pick any two {lg['name']} {unit1(lg)}s and see every time they met with the lineal championship belt on the line."))


# ------------------------------------------------------------------ next --

def form_table(lg, rows):
    lis = "".join(f'<tr><td class="mono">{S.d_short(r["date"], True)}</td><td>{"vs." if r["home"] else "at"} {e(r["opp_name"])}{" · " + post_word(lg) if r["postseason"] else ""}</td>'
                  f'<td class="mono r"><b class="res {r["result"]}">{r["result"]}</b> {e(r["score"])}{(" " + e(r["note"])) if r["note"] else ""}</td></tr>' for r in rows)
    return f'<table class="history form"><tbody>{lis}</tbody></table>'


def build_next(lg, d):
    key = lg["key"]
    pv, ng, cur = d.get("preview"), d.get("next_game"), d["current"]
    n = lg["team_name"]
    if not (pv and ng):
        body = f"""{S.subnav(lg, "next")}
<section class="wrap prose"><div class="kicker">Next title defense</div><h1 class="disp">{"The belt is frozen" if F.belt_state(lg, d)["state"] == "postseason_holder_out" else "No defense scheduled yet"}</h1>
<p>{e(F.belt_state(lg, d)["line"])} This page fills in as soon as the next game is on the schedule.</p>
<p><a href="{base(lg)}/">Back to the {lg['name']} belt →</a></p></section>"""
        S.write(out(lg, "next/index.html"), S.page(f"Next {lg['name']} belt defense", body, path=f"{base(lg)}/next/", active=key,
                                                 description=f"Preview of the next lineal {lg['name']} championship title defense.",
                                                 robots="noindex,follow"))      # BH-13: a stub until the next game is on file
        return
    h, c = pv["holder"], pv["challenger"]
    hp, hs = lg["team_colors"](h)
    top, bottom, ink, accent = S.plate(hp, hs)
    where = "vs." if ng["holder_home"] else "at"
    rec = lambda r: f"{r['W']}–{r['L']}" + (f"–{r['T']}" if r["T"] else "")
    h2h = pv["h2h"]
    lead = ("even" if h2h["holder_wins"] == h2h["challenger_wins"] else
            f"{e(lg['short_name'](h))} {vb(lg, 'lead', 'leads')}" if h2h["holder_wins"] > h2h["challenger_wins"] else f"{e(lg['short_name'](c))} {vb(lg, 'lead', 'leads')}")
    bm = [d["_bg"][x] for x in [b["n"] for b in d["belt_games"] if b.get("holder") and {b["holder"], b["opponent"]} == {h, c}]]
    bm_h = sum(1 for b in bm if b["new_holder"] == h and not b["outcome"].endswith("(tie)"))
    bm_c = sum(1 for b in bm if b["new_holder"] == c and not b["outcome"].endswith("(tie)"))
    clr = pv.get("challenger_last_reign")
    ch_hist = (f"{e(n(c))} {vb(lg, 'have', 'has')} held the belt {S.plural(pv['challenger_reigns'], 'time')}; the last reign began {S.d_long(clr['start'])}"
               + (f" and ended {S.d_long(clr['end'])}." if clr.get("end") else ".") if clr else f"{e(n(c))} {vb(lg, 'have', 'has')} never held the {lg['name']} belt. A win would be the first reign in {unit1(lg)} history.")
    stakes = (f"If {e(n(c))} {vb(lg, 'win, they take', 'wins, it takes')} the belt and start reign {cur['index'] + 1:,}. If {e(n(h))} {vb(lg, 'win', 'wins')}, it's defense number {pv['holder_streak'] + 1} of this reign"
              + (" (a tie also counts as a defense)." if lg.get("tie_rule") == "holder" and key in ("nfl", "mlb") else "."))
    spread = ""
    if ng.get("spread") is not None:
        fav = ng["home"] if ng["spread"] > 0 else ng["away"]
        spread = f"{e(lg['short_name'](fav))} favored by {abs(ng['spread']):g}" if ng["spread"] else "Pick ’em"
    body = f"""{S.subnav(lg, "next")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">Next title defense · {S.weekday(ng['date'])}, {S.d_long(ng['date'])} · {S.kickoff_12h(ng.get('kickoff'))}</div>
    <h1 class="disp holder" style="--fit:{max(len(w) for w in (lg['short_name'](h) + ' ' + where + ' ' + lg['short_name'](c)).split())}">{e(lg['short_name'](h))} {where} {e(lg['short_name'](c))}</h1>
    <p class="lede">{stakes}{(' ' + e(ng['stadium']) + '.') if ng.get('stadium') else ''}{(' ' + spread + '.') if spread else ''}</p>
  </div>
</section>
<section class="wrap block">
  <div class="numbers">
    <div><b class="disp">{pv['holder_streak']}</b><span class="mono">Defenses this reign</span></div>
    <div><b class="disp">{h2h['games']}</b><span class="mono">All-time meetings ({lead})</span></div>
    <div><b class="disp">{len(bm)}</b><span class="mono">Belt meetings</span></div>
    <div><b class="disp">{pv['challenger_reigns']}</b><span class="mono">{e(lg['short_name'](c))} reigns all-time</span></div>
  </div>
  <div class="two">
    <div><h2 class="disp sub">{e(n(h))} · recent games</h2><p class="mono note">{sl(lg, pv['record_season'])} record, {post_word(lg)} included: {rec(pv['holder_record'])}</p>{form_table(lg, pv['holder_form'])}</div>
    <div><h2 class="disp sub">{e(n(c))} · recent games</h2><p class="mono note">{sl(lg, pv['record_season'])} record, {post_word(lg)} included: {rec(pv['challenger_record'])}</p>{form_table(lg, pv['challenger_form'])}</div>
  </div>
  <h2 class="disp sub">Head to head</h2>
  <p class="intro">All-time: {e(lg['short_name'](h))} {h2h['holder_wins']}, {e(lg['short_name'](c))} {h2h['challenger_wins']}{f", {h2h['ties']} ties" if h2h['ties'] else ""}{f" since {S.d_long(h2h['first'])}" if h2h['first'] else ""}.
  {f"With the belt on the line they've met {S.plural(len(bm), 'time')}: {e(lg['short_name'](h))} won {bm_h}, {e(lg['short_name'](c))} won {bm_c}." if bm else "They have never met with the belt on the line."} {ch_hist}</p>
  {games_table(lg, bm[-10:][::-1], anchors=False) if bm else ""}
  <p class="mono more"><a href="{base(lg)}/compare/?a={h}&amp;b={c}">Full belt head-to-head →</a></p>
</section>"""
    import features as F
    body = body.replace(S.subnav(lg, "next"), S.subnav(lg, "next") + F.live_box(lg, d), 1) + F.next_extras(lg, d)
    if pv.get("holder_win_prob") is not None:
        body = body.replace(f'<div><b class="disp">{pv["holder_streak"]}</b><span class="mono">Defenses this reign</span></div>',
                            f'<div><b class="disp">{round(pv["holder_win_prob"] * 100)}%</b><span class="mono">Chance to defend (Elo)</span></div>', 1)
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f"{n(h)} {where} {n(c)}",
          "startDate": ng["date"], "sport": lg.get("sport", ""),
          "competitor": [{"@type": "SportsTeam", "name": n(h)}, {"@type": "SportsTeam", "name": n(c)}]}
    S.write(out(lg, "next/index.html"), S.page(f"{lg['short_name'](h)} {where} {lg['short_name'](c)}: {lg['name']} belt title defense preview", body,
                                             path=f"{base(lg)}/next/", active=key, jsonld=ld,
                                             description=f"{n(h)} {vb(lg, 'defend', 'defends')} the lineal {lg['name']} championship belt {where} {n(c)} on {S.d_long(ng['date'])}: recent form, head-to-head and what's at stake."))


# ----------------------------------------------------------- on this day --

def otd_items(datas):
    by = defaultdict(list)
    for lg in LIVE:
        d = datas[lg["key"]]
        for bg in d["belt_games"]:
            if bg["outcome"] == "changed":
                by[bg["date"][5:10]].append((bg["date"], lg, bg))
    for k in by:
        by[k].sort(key=lambda x: x[0], reverse=True)
    return by


def otd_list(items, limit=None):
    lis = []
    for dt, lg, bg in items[:limit] if limit else items:
        p, _ = lg["team_colors"](bg["new_holder"])
        lis.append(f'<li><span class="mono lg">{lg["name"]}</span><i style="background:{p}"></i><div>{game_line(lg, bg)} and took the belt</div>'
                   f'<a class="mono when" href="{season_url(lg, bg["season"], bg["n"])}">{dt[:4]}</a></li>')
    return f'<ol class="feed">{"".join(lis)}</ol>'


OTD_HOME_LIMIT = 6
OTD_INDEX_MIN = 2         # dated on-this-day pages with fewer title changes are noindex


def otd_home(by, today=None):
    """Homepage "Today in belt history" (BH-11/CFB-3): rendered for the build day, then swapped in the
    browser for today's date in US Eastern time from /on-this-day/<mm-dd>/top.json, so a build that ran
    yesterday never shows yesterday. Hidden when the date has no title changes."""
    today = today or date.today()
    k = f"{today:%m-%d}"
    items = by.get(k, [])
    label = f"{MONTHS_LONG[today.month - 1]} {today.day}"
    js = ('<script>(function(){var s=document.getElementById("otd-home");if(!s||!window.fetch)return;try{'
          'var p=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",month:"2-digit",day:"2-digit"}).formatToParts(new Date()),o={};'
          'p.forEach(function(x){o[x.type]=x.value;});var k=o.month+"-"+o.day;if(k===s.dataset.k)return;'
          "fetch('/on-this-day/'+k+'/top.json').then(function(r){return r.json();}).then(function(j){"
          's.querySelector(".otd-list").innerHTML=j.html;var a=s.querySelector("a.more");a.textContent="All of "+j.label+" \u2192";'
          'a.setAttribute("href",a.getAttribute("href").replace(s.dataset.k,k));s.dataset.k=k;s.hidden=!j.n;}).catch(function(){});}catch(e){}})();</script>')
    return (f'<section class="wrap block" id="otd-home" data-k="{k}"{"" if items else " hidden"}><div class="head"><h2 class="disp">Today in belt history</h2>'
            f'<a class="mono more" href="/on-this-day/{k}/">All of {label} →</a></div>'
            f'<div class="otd-list">{otd_list(items, OTD_HOME_LIMIT) if items else ""}</div></section>{js}')


def build_otd(datas):
    by = otd_items(datas)
    today = date.today()
    for m in range(1, 13):
        for dd in range(1, 32):
            try:
                dt = date(2024, m, dd)
            except ValueError:
                continue
            k = f"{m:02d}-{dd:02d}"
            items = by.get(k, [])
            extra = S.otd_extra(k) if hasattr(S, "otd_extra") else []      # the college belts, on beltholders.com
            prev_d = date.fromordinal(dt.toordinal() - 1)
            next_d = date.fromordinal(dt.toordinal() + 1)
            nav = (f'<nav class="pager mono"><a href="/on-this-day/{prev_d:%m-%d}/">← {MONTHS_LONG[prev_d.month - 1]} {prev_d.day}</a>'
                   f'<a href="/on-this-day/">Today</a><a href="/on-this-day/{next_d:%m-%d}/">{MONTHS_LONG[next_d.month - 1]} {next_d.day} →</a></nav>')
            label = f"{MONTHS_LONG[m - 1]} {dd}"
            counts = Counter(lg["name"] for _, lg, _ in items)
            body = f"""<section class="wrap block">
  <div class="kicker">On this day</div>
  <div class="head"><h1 class="disp">{label} in belt history</h1><span class="mono note">{S.plural(len(items), 'title change')}{(' · ' + ', '.join(f'{v} {k}' for k, v in counts.most_common())) if items else ''}</span></div>
  {otd_list(items) if items else '<p class="intro">No belt has ever changed hands on this date.</p>'}
  {('<h2 class="disp sub">The college belts on ' + label + '</h2><ol class="feed">' + "".join(x["html"] for x in extra) + '</ol>') if extra else ''}
  {nav}
</section>"""
            html = S.page(f"On this day, {label}: belt title changes", body, path=f"/on-this-day/{k}/",
                          description=(S.otd_description(label) if hasattr(S, "otd_description")
                                       else f"Every lineal championship belt title change on {label}, in every league we track."),
                          robots=None if len(items) + len(extra) >= OTD_INDEX_MIN else "noindex,follow")   # BH-9: a date with 0-1 changes is thin
            S.write(f"on-this-day/{k}/index.html", html)
            S.write(f"on-this-day/{k}/top.json", json.dumps({"label": label, "n": len(items),
                                                             "html": otd_list(items, OTD_HOME_LIMIT) if items else ""}, separators=(",", ":")))
            if (m, dd) == (today.month, today.day):
                # BH-11/CBB-6: /on-this-day/ is not a page of its own. It sends the reader to today's dated
                # page (today in US Eastern time, worked out in the browser, so it's right whatever day the
                # build ran), is noindex, and canonicalizes to the dated page. Without JS it shows the build day.
                pre = getattr(S, "P", "")
                go = ('<script>(function(){try{var p=new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",month:"2-digit",day:"2-digit"}).formatToParts(new Date()),'
                      'o={};p.forEach(function(x){o[x.type]=x.value;});location.replace("' + pre + '/on-this-day/"+o.month+"-"+o.day+"/");}catch(e){}})();</script>')
                idx = S.page(f"On this day, {label}: belt title changes", body.replace("<section", go + "<section", 1), path=f"/on-this-day/{k}/",
                             description=(S.otd_description(label) if hasattr(S, "otd_description")
                                          else f"Every lineal championship belt title change on {label}, in every league we track."),
                             robots="noindex,follow")
                getattr(S, "NOINDEX", set()).discard(f"/on-this-day/{k}/")     # the dated page itself stays indexable
                S.write("on-this-day/index.html", idx)


# --------------------------------------------------------------- stories --

def stories_for(lg, d):
    n, key = lg["team_name"], lg["key"]
    rec = d["records"]
    out = []
    # 1. longest reigns
    parts = []
    for i, r in enumerate(rec["longest_reigns"][:5], 1):
        full = next((x for x in d["reigns"] if x["start_date"] == r["start_date"] and x["team"] == r["team"]), None)
        if not full:
            continue
        how = f"took it from {e(n(full['won_from'], full['season']))} {S.won_score_text(full)} on {S.d_long(full['start_date'])}" if full.get("won_from") else f"picked it up on {S.d_long(full['start_date'])}"
        end = (f"The run ended on {S.d_long(full['end_date'])} against {e(n(full['lost_to'], full.get('end_season') or full['season']))}." if full.get("lost_to")
               else "The reign is still going.")
        parts.append(f"<h2 class=\"disp\">{i}. {e(full['name'])}, {sl(lg, full['season'])}</h2><p>{e(full['name'])} {how} and defended it {S.plural(full.get('defenses', 0), 'time')} over {S.plural(full['days'], 'day')}. {end} <a href=\"{reign_url(lg, d, full)}\">Every game of the reign →</a></p>")
    out.append(("longest-reigns", f"The longest reigns in {lg['name']} belt history",
                f"The five runs that held off every challenger longest, from {lg['first_season']} to today.", "".join(parts)))
    # 2. droughts
    dr = rec.get("droughts", [])
    never = rec.get("never_held", [])
    parts = [f"<p>Every active {lg.get('active_label', lg['name'] + ' ' + unit1(lg))} and how long it's been since it last held the belt. The belt moves constantly, so a long wait usually means a {unit1(lg)} keeps losing the one game that matters.</p>"]
    if never and len(never) <= 40:
        parts.append(f"<h2 class=\"disp\">Never held it</h2><p>{', '.join(team_link(lg, t) for t in never)}.</p>")
    elif never:
        parts.append(f"<h2 class=\"disp\">Never held it</h2><p>{len(never)} current programs have never held the belt.</p>")
    parts.append("<h2 class=\"disp\">The longest waits</h2><ol>" + "".join(
        f"<li>{team_link(lg, x['team'])}: last held it {S.d_long(x['last'])}, {S.plural(x['days'], 'day')} ago.</li>" for x in dr) + "</ol>")
    out.append(("droughts", f"Waiting for the {lg['name']} belt: the longest droughts",
                f"The active {unit1(lg)}s that have gone longest without the belt, and the ones still waiting for their first reign.", "".join(parts)))
    # 3. busiest seasons
    ss = {s["season"]: s for s in d["seasons"]}
    parts = ["<p>Some seasons the belt barely moves. Others it gets passed around like a hot potato. Here are the seasons it changed hands most, and the ones where it hardly moved.</p><h2 class=\"disp\">Busiest seasons</h2><ol>"]
    for s, c in rec["busiest_seasons"][:5]:
        x = ss.get(s)
        if x:
            parts.append(f"<li><a href=\"{season_url(lg, s)}\">{e(x['label'])}</a>: {S.plural(c, 'title change')} among {S.plural(x['distinct_holders'], unit1(lg))}; {e(n(x['ending'], s))} finished with it.</li>")
    parts.append("</ol><h2 class=\"disp\">Quietest seasons</h2><ol>")
    for s, c in rec["quietest_seasons"][:5]:
        x = ss.get(s)
        if x:
            parts.append(f"<li><a href=\"{season_url(lg, s)}\">{e(x['label'])}</a>: {S.plural(c, 'title change')}. {e(n(x['entering'], s))} carried it in and {e(n(x['ending'], s))} carried it out.</li>")
    parts.append("</ol>")
    out.append(("wildest-seasons", f"The {lg['name']} belt's wildest and quietest seasons",
                "The seasons the belt changed hands most, and the ones it hardly moved.", "".join(parts)))
    # 4. how it got here
    ch = [bg for bg in d["belt_games"] if bg["outcome"] == "changed"][-12:]
    cur = d["current"]
    parts = [f"<p>{e(cur['name'])} {vb(lg, 'hold', 'holds')} the {lg['name']} belt today. Here's how it got to them: the last {len(ch)} times it changed hands.</p><ol>"]
    for bg in ch:
        parts.append(f"<li>{S.d_long(bg['date'])}: {game_line(lg, bg)}. <a href=\"{season_url(lg, bg['season'], bg['n'])}\">Season page →</a></li>")
    parts.append("</ol>")
    out.append(("how-it-got-here", f"How the {lg['name']} belt got to {cur['name']}",
                f"The last {len(ch)} title changes, in order, ending with the current holder.", "".join(parts)))
    # 5. rivalries
    rv = d["rivalries"][:5]
    parts = [f"<p>No two {unit1(lg)}s have fought over the {lg['name']} belt more often than these.</p>"]
    for i, p in enumerate(rv, 1):
        ties_txt = f", {p['ties']} ties" if p["ties"] else ""
        parts.append(f"<h2 class=\"disp\">{i}. {e(n(p['a']))} vs. {e(n(p['b']))}</h2><p>{p['meetings']} belt meetings between {p['first'][:4]} and {p['last'][:4]}, {S.plural(p['changes'], 'title change')}. Belt series: {e(lg['short_name'](p['a']))} {p['a_wins']}, {e(lg['short_name'](p['b']))} {p['b_wins']}{ties_txt}. <a href=\"{base(lg)}/rivalries/{rivalry_slug(lg, p['a'], p['b'])}/\">Every meeting →</a></p>")
    out.append(("rivalries", f"The rivalries that decided the {lg['name']} belt",
                f"The five pairs of {unit1(lg)}s that have met most often with the belt on the line.", "".join(parts)))
    # 6. frozen (audit 7.18): seasons the holder missed the postseason and carried the belt over
    fz = frozen_seasons(lg, d)
    if fz:
        st = F.belt_state(lg, d)
        pw = post_word(lg)
        now = (f"<p><b>Right now:</b> {e(st['line'])}</p>" if st["state"] == "postseason_holder_out" else "")
        items = "".join(f"<li><a href=\"{season_url(lg, x['season'])}\">{e(x['label'])}</a>: {e(n(x['holder'], x['season']))} sat out the {e(pw)} with the belt"
                        + (f" while {e(n(x['champion'], x['season']))} won the title" if x.get("champion") else "") + ".</li>" for x in fz[:30])
        parts = [f"<p>The belt only moves when its holder plays. When the holder's season ends early, the belt freezes: the champions get crowned in the {e(pw)}, "
                 f"and the belt waits for next season. It has happened {S.plural(len(fz), 'time')} in {lg['name']} belt history.</p>{now}<h2 class=\"disp\">Every frozen season, newest first</h2><ol>{items}</ol>"]
        out.append(("frozen", f"Frozen: when the {lg['name']} belt sat out the {pw}",
                    f"{S.plural(len(fz), 'season')} the belt holder missed the {pw} and carried the belt into the next season.", "".join(parts)))
    return out


def frozen_seasons(lg, d):
    """Seasons whose postseason was played without the belt: a champion was crowned, and no
    postseason game that season was a belt game (the holder wasn't there)."""
    if not F.caps(lg, d)["has_postseason"]:
        return []
    post = {bg["season"] for bg in d["belt_games"] if bg.get("season_type") != "regular"}
    live = {x["season"] for x in d.get("seasons", []) if x.get("in_progress")}
    ss = {x["season"]: x for x in d.get("seasons", [])}
    out = []
    for c in (d.get("models") or {}).get("champions") or []:
        s = c.get("season")
        if s in post or s in live or s not in ss or not c.get("champion"):
            continue
        out.append({"season": s, "label": ss[s]["label"], "holder": c.get("holder") or ss[s]["ending"], "champion": c.get("champion")})
    return sorted(out, key=lambda x: -x["season"])


def build_stories(datas):
    """Belt Holders (NETWORK): a stories index per league plus an all-league one at /stories/.
    The CBB site: one index per belt at <base>/stories/."""
    network = getattr(S, "NETWORK", True)
    cards = []
    for lg in LIVE:
        d = datas[lg["key"]]
        key = lg["key"]
        mine = []
        for sslug, title, dek, html in stories_for(lg, d):
            url = f"{base(lg)}/stories/{sslug}/"
            more = f"More {lg['name']} stories →" if network else "More stories →"
            body = f"""{S.subnav(lg, "stories")}
<section class="wrap prose story"><div class="kicker">{lg['long_name']} · story</div><h1 class="disp">{e(title)}</h1><p class="dek">{e(dek)}</p>{html}
<p class="mono more"><a href="{base(lg)}/stories/">{more}</a></p></section>"""
            ld = {"@context": "https://schema.org", "@type": "Article", "headline": title, "description": dek,
                  "dateModified": d["generated"], "publisher": {"@type": "Organization", "name": F.OWNER}}
            S.write(url.strip("/") + "/index.html", S.page(title, body, path=url, active=key, jsonld=ld, description=dek))
            mine.append((lg, title, dek, url))
        if network:
            lis = "".join(f'<a class="storycard" href="{u}"><b class="disp">{e(t)}</b><span>{e(dk)}</span></a>' for _, t, dk, u in mine)
            body = f"""{S.subnav(lg, "stories")}
<section class="wrap block"><div class="head"><h1 class="disp">{lg['name']} belt stories</h1><span class="mono note">Written from the data, updated with every game</span></div><div class="storygrid">{lis}</div></section>"""
            S.write(out(lg, "stories/index.html"), S.page(f"{lg['name']} belt stories", body, path=f"{base(lg)}/stories/", active=key,
                                                        description=f"Long reads on the lineal {lg['name']} championship belt: the longest reigns, the longest droughts, the wildest seasons and the rivalries that decided it."))
        cards += mine
        if not network:      # machine-readable list for the network pages on beltholders.com
            S.write(out(lg, "stories/index.json"), json.dumps([{"title": t, "dek": dk, "url": S.SITE_URL + u} for _, t, dk, u in mine], indent=0))
    lis = "".join(f'<a class="storycard" href="{u}"><span class="mono lg">{lg["name"]}</span><b class="disp">{e(t)}</b><span>{e(dk)}</span></a>' for lg, t, dk, u in cards)
    if network:
        S.write("stories/index.json", json.dumps([{"title": t, "dek": dk, "belt": lg["name"], "url": S.SITE_URL + u} for lg, t, dk, u in cards], indent=0))
        others = S.network_stories() if hasattr(S, "network_stories") else []
        net = "".join(f'<a class="storycard" href="{x["url"]}"><span class="mono lg">{e(x["belt"])}</span><b class="disp">{e(x["title"])}</b><span>{e(x.get("dek") or "")}</span></a>' for x in others)
        body = f"""<section class="wrap block"><div class="head"><h1 class="disp">Stories</h1><span class="mono note">Every league</span></div><div class="storygrid">{lis}</div></section>""" + (
            f"""<section class="wrap block"><div class="head"><h2 class="disp">From the college belts</h2><span class="mono note">collegefootballbelt.com · collegebasketballbelt.com</span></div><div class="storygrid">{net}</div></section>""" if net else "")
        S.write("stories/index.html", S.page("Stories", body, path="/stories/",
                                             description="Long reads on the lineal championship belts: the longest reigns, the longest droughts, the wildest seasons and the rivalries that decided them."))
    else:
        body = f"""{S.subnav(lg, "stories")}
<section class="wrap block"><div class="head"><h1 class="disp">Stories</h1><span class="mono note">Written from the data, updated with every game</span></div><div class="storygrid">{lis}</div></section>"""
        S.write(out(lg, "stories/index.html"), S.page("Stories", body, path=f"{base(lg)}/stories/",
                                                    description=f"Long reads on the {getattr(S, 'SEC', {}).get('short', site_name())}: the longest reigns, the longest droughts, the wildest seasons and the rivalries that decided it."))
    return cards


# ---------------------------------------------------------------- search --

def build_search(datas, cards=()):
    """NET-6: search/index.json holds teams, seasons, notable reigns and stories; search/players.json the
    players with F.SEARCH_MIN_GAMES+ belt games (fetched alongside it). Rows are [name, label, url, weight]."""
    idx = []
    for lg in LIVE:
        d = datas[lg["key"]]
        teams = {r["team"] for r in d["reigns"]}
        for t in teams:
            idx.append([lg["team_name"](t), f"{lg['name']} team", f"{base(lg)}/teams/{S.slug(lg['team_name'](t))}/", 9999])
        for s in d["seasons"]:
            idx.append([f"{lg['name']} {s['label']}", "Season", season_url(lg, s["season"]), 500])
        cur = d["reigns"][-1]["index"] if d["reigns"] else None
        for r in d["reigns"]:
            if notable(r, cur) and r.get("defenses", 0) >= REIGN_MIN_DEFENSES:
                yr = r["start_date"][:4]
                idx.append([f"{lg['team_name'](r['team'], r.get('season'))} {yr}", f"{lg['name']} reign · {S.plural(r['defenses'], 'defense')}",
                            f"{base(lg)}/reigns/{r['index']}/", r["defenses"]])
    for c in cards:
        lg, t, _dk, u = c
        idx.append([t, f"{lg['name']} story", u, 1])
    S.write("search/index.json", json.dumps(idx, separators=(",", ":"), ensure_ascii=False))
    S.write("search/players.json", json.dumps(sorted(F.SEARCH_PLAYERS, key=lambda x: -x[3]), separators=(",", ":"), ensure_ascii=False))
    body = """<section class="wrap block"><div class="head"><h1 class="disp">Search</h1></div>
<input id="q" class="searchbox mono" type="search" placeholder="A team, a player, a city, or a season like 1985" autofocus>
<ol id="res" class="results"></ol></section>
<script>
(function(){var I=[],q=document.getElementById('q'),o=document.getElementById('res');
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function fold(s){return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');}
function run(){var v=fold(q.value.trim());if(!v){o.innerHTML='';return;}
var r=[];I.forEach(function(x){var n=x.f||(x.f=fold(x[0])),i=n.indexOf(v);if(i<0)return;
r.push([i===0||n.charAt(i-1)===' '?0:1,-(x[3]||0),x]);});
r.sort(function(a,b){return a[0]-b[0]||a[1]-b[1];});r=r.slice(0,40);
o.innerHTML=r.length?r.map(function(y){var x=y[2];return '<li><a href="'+x[2]+'">'+esc(x[0])+'</a><span class="mono">'+esc(x[1])+'</span></li>';}).join(''):'<li>No matches.</li>';}
q.addEventListener('input',run);
var p=new URLSearchParams(location.search).get('q');if(p){q.value=p;}
function add(j){I=I.concat(j);run();}
fetch('/search/index.json').then(function(r){return r.json();}).then(add);
fetch('/search/players.json').then(function(r){return r.ok?r.json():[];}).then(add).catch(Boolean);})();
</script>"""
    S.write("search/index.html", S.page("Search", body, path="/search/", description=(S.search_description() if hasattr(S, "search_description")
                                                                                   else "Find any team, player, reign or season on Belt Holders.")))


# ----------------------------------------------------------------- teams --

def team_extras(lg, d, team):
    """Extra sections for a team page: belt record by opponent + seasons with the belt."""
    n = lg["team_name"]
    rec = defaultdict(lambda: [0, 0, 0])
    seasons = set()
    for bg in d["belt_games"]:
        if not bg.get("holder") or team not in (bg["holder"], bg["opponent"]):
            continue
        opp = bg["opponent"] if bg["holder"] == team else bg["holder"]
        mine, theirs = score_for(bg, team)
        rec[opp][0 if mine > theirs else 1 if mine < theirs else 2] += 1
        if bg["new_holder"] == team or bg["holder"] == team:
            seasons.add(bg["season"])
    rows = "".join(f'<tr><td>{team_link(lg, o)}</td><td class="mono r">{w}–{l}{f"–{t}" if t else ""}</td><td class="mono r"><a href="{base(lg)}/compare/?a={team}&amp;b={o}">Games →</a></td></tr>'
                   for o, (w, l, t) in sorted(rec.items(), key=lambda kv: -sum(kv[1]))[:15])
    chips = "".join(f'<a class="chip" style="--c:{lg["team_colors"](team)[0]}" href="{season_url(lg, s)}">{e(sl(lg, s))}</a>' for s in sorted(seasons, reverse=True))
    return f"""<section class="wrap block"><div class="two">
  <div><h2 class="disp sub">Belt record by opponent</h2><table class="history"><thead><tr><th class="mono">Opponent</th><th class="mono r">W–L</th><th><span class="sr">Share</span></th></tr></thead><tbody>{rows}</tbody></table></div>
  <div><h2 class="disp sub">Seasons with the belt</h2><div class="strip">{chips}</div></div>
</div></section>"""


# ------------------------------------------------------------ challengers --

CHALLENGER_INDEX_MIN = 3      # challenger pages with fewer belt games are noindex (thin)


def challengers(lg, d):
    """Teams that played belt games but never held the belt: {code: belt games}."""
    held = {r["team"] for r in d["reigns"]}
    c = Counter()
    for bg in d["belt_games"]:
        for t in (bg.get("holder"), bg["opponent"]):
            if t and t not in held:
                c[t] += 1
    return c


def build_challenger(lg, d, team):
    """"<Team> vs. the belt": a page for every team that has challenged for the belt and
    never won it (BH-4/CBB-2), so every team link resolves. Returns (url, games)."""
    n, sn = lg["team_name"], lg["short_name"]
    name = n(team)
    games = [bg for bg in d["belt_games"] if team in (bg.get("holder"), bg["opponent"])]
    if not games:
        return None
    losses, ties, closest, holders = 0, 0, [], Counter()
    for bg in games:
        mine, theirs = score_for(bg, team)
        holders[bg.get("holder") or bg["new_holder"]] += 1
        if mine == theirs:
            ties += 1
        else:
            losses += 1
            closest.append((theirs - mine, bg))
    closest.sort(key=lambda x: (x[0], x[1]["date"]))
    first, last = games[0], games[-1]
    nxt = d.get("next_game") or {}
    next_line = ""
    if nxt and team in (nxt.get("challenger"), nxt.get("away"), nxt.get("home")) and nxt.get("date"):
        next_line = (f" Next shot: {S.d_long(nxt['date'])} against {e(n(d['current']['team']))}, the current holder.")
    p, s2 = lg["team_colors"](team)
    top, bottom, ink, accent = S.plate(p, s2)
    rec = f"0–{losses}" + (f"–{ties}" if ties else "")
    lede = (f"{e(name)} {vb(lg, 'have', 'has')} played {S.plural(len(games), 'belt game')} and never taken the {e(lg['name'])} belt: "
            f"the first chance came on {S.d_long(first['date'])}, the latest on {S.d_long(last['date'])}.{next_line}")
    if ties:
        lede += f" {S.plural(ties, 'game')} ended level, which leaves the belt with the holder."
    faced = ", ".join(f"{team_link(lg, h)} ({x})" for h, x in holders.most_common(6))
    close = "".join(f'<tr><td class="mono">{S.d_short(bg["date"], True)}</td><td>{game_line(lg, bg)}</td><td class="mono r">{m_}</td></tr>'
                    for m_, bg in closest[:8])
    rows = "".join(f'<tr id="g{bg["n"]}"><td class="mono"><a href="{season_url(lg, bg["season"], bg["n"])}">{bg["n"]:,}</a></td>'
                   f'<td class="mono">{S.d_short(bg["date"], True)}</td><td>{game_line(lg, bg)}</td></tr>' for bg in reversed(games))
    body = f"""{S.subnav(lg, "teams")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">{e(lg['long_name'])} · still waiting</div>
    <h1 class="disp holder" style="--fit:{max(len(x) for x in name.split())}">{e(name)} vs. the belt</h1>
    <div class="stats"><div><b class="disp">{len(games)}</b><span class="mono">Belt games</span></div><div><b class="disp">{rec}</b><span class="mono">Record vs. holders</span></div><div><b class="disp">{first['date'][:4]}</b><span class="mono">First shot</span></div><div><b class="disp">{last['date'][:4]}</b><span class="mono">Latest shot</span></div></div>
  </div>
</section>
<section class="wrap block prose"><p>{lede}</p><p>Holders faced most often: {faced}.</p></section>
<section class="wrap block"><div class="two">
  <div><h2 class="disp sub">The closest calls</h2><table class="history"><thead><tr><th class="mono">Date</th><th class="mono">Game</th><th class="mono r">Margin</th></tr></thead><tbody>{close}</tbody></table></div>
  <div><h2 class="disp sub">Every belt game</h2><div class="tablewrap"><table class="history"><thead><tr><th class="mono">Belt game</th><th class="mono">Date</th><th class="mono">Result</th></tr></thead><tbody>{rows}</tbody></table></div></div>
</div></section>{S.school_box(name) if hasattr(S, "school_box") else ""}"""
    url = f"{base(lg)}/teams/{S.slug(name)}/"
    thin = len(games) < CHALLENGER_INDEX_MIN
    kw = {"robots": "noindex,follow"} if thin else {}
    S.write(out(lg, f"teams/{S.slug(name)}/index.html"),
            S.page(f"{name} vs. the {lg['name']} belt", body, path=url, active=lg["key"],
                   description=f"{name} {vb(lg, 'have', 'has')} played {S.plural(len(games), 'lineal ' + lg['name'] + ' belt game')} "
                               f"({rec} against the holder) and {vb(lg, 'are', 'is')} still waiting for a first reign.", **kw))
    return url, len(games)


def challengers_section(lg, d):
    """Cards for the teams index: every challenger, most belt games first. Builds their pages."""
    cards = []
    for t, k in sorted(challengers(lg, d).items(), key=lambda kv: (-kv[1], lg["team_name"](kv[0]))):
        built = build_challenger(lg, d, t)
        if not built:
            continue
        p, _ = lg["team_colors"](t)
        cards.append(f'<a class="teamcard" href="{built[0]}"><i style="background:{p}"></i><b class="disp">{e(lg["team_name"](t))}</b>'
                     f'<span class="mono">{S.plural(k, "belt game")} · never held it</span></a>')
    if not cards:
        return ""
    return (f'<section class="wrap block"><div class="head"><h2 class="disp">Still waiting</h2><span class="mono note">{len(cards)} '
            f'{unit1(lg)}s have played for the belt and never taken it</span></div><div class="teamgrid">{"".join(cards)}</div></section>')


# ------------------------------------------------------------------ main --

def build_all(datas):
    import features as F
    F.init(S, base, site_name())
    for lg in LIVE:
        d = datas[lg["key"]]
        d["_bg"] = {bg["n"]: bg for bg in d["belt_games"]}
        build_seasons(lg, d)
        build_reigns(lg, d)
        build_rivalries(lg, d)
        build_compare(lg, d)
        F.build(lg, d)
        F.build_preview(lg, d)
        F.build_batch2(lg, d)
        F.build_tables(lg, d)
        F.build_api_dumps(lg, d)
    F.build_embed([(lg, datas[lg["key"]]) for lg in LIVE])
    build_otd(datas)
    cards = build_stories(datas)
    build_search(datas, cards)
    return cards
