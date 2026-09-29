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
from html import unescape as _unescape
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
CHG_TAG = '<span class="tag chg">Title change</span>'
DEF_TAG = '<span class="tag">Defense</span>'
SAME_SHORT = ' <span class="tag chg">Same</span>'


def init(site_module, base, site_name="Belt Holders"):
    global S, BASE, SITE_NAME
    S, BASE, SITE_NAME = site_module, base, site_name
    SEARCH_PLAYERS.clear()


SEARCH_PLAYERS = []      # [name, label, url, belt games] for players with SEARCH_MIN_GAMES+; site_extras.build_search reads it
SEARCH_MIN_GAMES = 5


def e(x):
    return S.e(x)


def b(lg):
    return BASE(lg)


def out(lg, rel):
    pre = b(lg).lstrip("/")
    return f"{pre}/{rel}" if pre else rel


def verb(lg, plural_form, singular_form):
    return singular_form if lg.get("singular") else plural_form


def poss(name):
    """Possessive of a team name, as CFB's possessive(): Michigan’s, the Bengals’, Chicago White Sox’s."""
    return name + ("’" if name.endswith(("s", "S")) else "’s")


def belt_state(lg, d):
    """BH-12: one state per belt, used by the tiles, the plate, /next/, /outlook/ and api/current.json.

      in_season_next_game     the holder's next game is on the schedule
      offseason_next_known    offseason, but the holder's first game of next season is already out
      postseason_holder_out   the league is still playing (postseason) but the holder is done:
                              the belt is frozen and carries over to next season
      offseason_schedule_pending  offseason, no game for the holder on file yet
    Returns {state, pill, foot, sub, line}; foot/sub fill the tile foot when there's no next game."""
    st = _belt_state(lg, d)
    h = d.get("_health")                     # NET-2: data/health.json from check_freshness.py
    if h and not h.get("ok", True):
        st.update(delayed=True, pill="Data delayed", reason=h.get("reason", ""))
    return st


def _belt_state(lg, d):
    ng, status, cur = d.get("next_game"), d.get("status") or "", d["current"]
    name = lg["team_name"](cur["team"])
    last = (d.get("seasons") or [None])[-1]
    nxt = None
    if last and lg.get("unit") != "nations":
        lab = str(last.get("label") or last["season"])
        y = int(lab[:4]) + 1
        nxt = f"{y}–{str(y + 1)[2:]}" if "–" in lab else str(y)
    they = verb(lg, "their", "its")
    again = lg["short_name"](cur["team"])
    again = again if lg.get("singular") else f"the {again}"
    if ng:
        if status == "In season":
            return {"state": "in_season_next_game", "pill": status, "foot": "", "sub": "", "line": ""}
        return {"state": "offseason_next_known", "pill": status or "Offseason", "foot": "", "sub": "",
                "line": f"{name} {verb(lg, 'hold', 'holds')} the belt through the offseason; the next defense is {S.d_long(ng['date'])}."}
    if status == "In season":
        into = f"into the {nxt} season" if nxt else "into next season"
        return {"state": "postseason_holder_out", "pill": "Belt frozen", "foot": "Frozen", "sub": f"Until {nxt}" if nxt else "Until next season",
                "line": (f"{name} {verb(lg, 'are', 'is')} done for the season while the rest of the league plays on, so the belt is frozen: "
                         f"{verb(lg, 'they carry', 'it carries')} it {into}, and nobody can take it until {again} {verb(lg, 'play', 'plays')} again.")}
    first = f"the first game on {poss(name)} {nxt} schedule" if nxt else f"{poss(name)} next game"
    return {"state": "offseason_schedule_pending", "pill": status or "Offseason", "foot": "Offseason", "sub": "Schedule pending",
            "line": f"{name} {verb(lg, 'hold', 'holds')} the belt through the offseason. The next defense is {first}, once {they} schedule is out."}


def next_payload(lg, d, site_url):
    """The next belt game in the network's shape (api/current.json "next", api/network.json)."""
    ng = d.get("next_game")
    if not ng:
        return None
    ex, _ = _extra(lg)
    espn = (ex or {}).get("espn") or {}
    return {"date": ng["date"], "time_et": ng.get("kickoff") or ng.get("start_et"),
            "opponent": lg["team_name"](ng["challenger"]), "opponent_short": lg["short_name"](ng["challenger"]),
            "home": bool(ng["holder_home"]), "neutral": bool(ng.get("neutral")), "venue": ng.get("stadium") or ng.get("venue"),
            "tv": espn.get("tv") if isinstance(espn.get("tv"), str) else None,
            "win_prob": (d.get("preview") or {}).get("holder_win_prob"), "url": f"{site_url}{b(lg)}/next/"}


def build_api_dumps(lg, d):
    """CBB-7: api/reigns.json and api/games.json, the same two files the College Football Belt
    publishes: every reign and every belt game, with team names, straight from the lineage."""
    n = lg["team_name"]
    gen = d.get("generated")
    reigns = [{"index": r["index"], "team": r["team"], "name": r["name"], "reign_no": r.get("reign_no"),
               "start_date": r["start_date"], "end_date": r.get("end_date"), "days": r.get("days"),
               "defenses": r.get("defenses", 0), "won_from": r.get("won_from"),
               "won_from_name": n(r["won_from"]) if r.get("won_from") else None, "opened_by": r.get("opened_by")}
              for r in d["reigns"]]
    games = [{"n": g["n"], "date": g["date"], "season": g["season"], "season_type": g.get("season_type"),
              "holder": g.get("holder"), "holder_name": n(g["holder"], g["season"]) if g.get("holder") else None,
              "opponent": g["opponent"], "opponent_name": n(g["opponent"], g["season"]), "home": g.get("home"),
              "neutral": bool(g.get("neutral")), "score": g.get("score"), "outcome": g["outcome"],
              "new_holder": g.get("new_holder"), "new_holder_name": n(g["new_holder"], g["season"]) if g.get("new_holder") else None,
              "ot": bool(g.get("ot"))} for g in d["belt_games"]]
    S.write(out(lg, "api/reigns.json"), json.dumps({"belt": lg["name"], "reigns": reigns, "generated_at": gen}, separators=(",", ":")))
    S.write(out(lg, "api/games.json"), json.dumps({"belt": lg["name"], "belt_games": games, "generated_at": gen}, separators=(",", ":")))


def belt_tag(lg):
    """How a short <title> names the belt: "Bundesliga belt"; single-sport sites set their own ("belt game")."""
    return lg.get("title_belt", f"{lg['name']} belt")


def unit_one(lg):
    """One team, in the belt's own word: franchise, club, nation, program."""
    return lg.get("unit_one", "franchise")


def unit(lg):
    return lg.get("unit", "franchises")


def post_word(lg):
    return lg.get("post_word", "playoffs")


TEAM_PAGES = {}      # league key -> team codes with a page: holders and every challenger (BH-4)


def has_team_page(lg, code):
    pages = TEAM_PAGES.get(lg["key"])
    return True if pages is None else code in pages


def team_url(lg, code):
    return f"{b(lg)}/teams/{S.slug(lg['team_name'](code))}/"


def team_href(lg, code):
    """The team's page, or None when it has none (it never played a belt game)."""
    return team_url(lg, code) if has_team_page(lg, code) else None


def tlink(lg, code, season=None):
    nm = lg["team_name"](code, season) if season is not None else lg["team_name"](code)
    return f'<a href="{team_url(lg, code)}">{e(nm)}</a>' if has_team_page(lg, code) else e(nm)


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


def page(lg, title, body, rel, description, jsonld=None, robots=None, og_title=None):
    path = f"{b(lg)}/{rel}" if rel else f"{b(lg)}/"
    kw = {"robots": robots} if robots else {}
    if og_title:
        kw["og_title"] = og_title
    S.write(out(lg, rel + "index.html" if rel else "index.html"),
            S.page(title, body, path=path, description=description, active=lg.get("key"), jsonld=jsonld, **kw))


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
  <div class="tablewrap"><table class="history odds"><thead><tr><th class="mono">#</th><th class="mono">Team</th><th><span class="sr">Share</span></th><th class="mono r">Chance</th><th class="mono r">Elo</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    else:
        outlook_html = f"""<h2 class="disp sub">Season outlook</h2><p class="intro">{e(belt_state(lg, d)['line'] or "There's no regular-season schedule left on file for " + n(h) + ".")} The outlook comes back as soon as the next schedule is out.</p>"""
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
         f"Who's likely to hold the lineal {lg['name']} championship belt next: {poss(n(h))} chance to defend, the belt tree for the next four games, and season-end odds for every team.")


# =============================================================== champions ==

def build_champions(lg, d):
    if not caps(lg, d)["has_champions"]:
        return
    rows_data = (d.get("models") or {}).get("champions") or []
    live = {s["season"] for s in d.get("seasons", []) if s.get("in_progress")}
    rows_data = [r for r in rows_data if r["season"] not in live]      # no champion until the season is over (BH-6)
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
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Season</th><th class="mono">Champion</th><th class="mono">Belt at season's end</th><th><span class="sr">Match</span></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
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
  <p class="mono more"><a href="{b(lg)}/losers-belt/reigns/">All {L['reigns']:,} Losers Belt reigns, searchable →</a></p>
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
 O.innerHTML='<div class="ondate" style="--c:'+D.colors[r[2]]+'"><div class="kicker">'+fd(o)+'</div><b class="disp">'+nm+'</b><p>Reign '+r[4].toLocaleString()+' of the belt, and the '+ord(r[5])+' for the '+'{unit_one(lg)}'+'. Held from '+fd(r[0])+(now?' and still going':' to '+fd(r[1]))+', with '+r[3]+' successful defense'+(r[3]===1?'':'s')+'.</p><p class="mono"><a href="'+D.urls[r[2]]+'">'+nm+' belt history →</a></p></div>';
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
            "name": lg["team_name"](t), "short": lg["short_name"](t), "color": lg["team_colors"](t)[0], "url": team_href(lg, t),
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
 '<p>'+(x.last?(x.last[1]?'Last held it '+fd(x.last[0])+' – '+fd(x.last[1])+'.':'Holding it since '+fd(x.last[0])+'.'):'Never held the belt.')+'</p><p class="mono">'+(x.url?'<a href="'+x.url+'">Full team belt history →</a> · ':'')+'<a href="{b(lg)}/compare/?a='+t+'&b={cur["team"]}">vs. the holder →</a></p></div>';
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
        pick = rng.sample(modern, min(250, len(modern))) + rng.sample(old, min(150, len(old)))
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
        desc = _ics_escape(f"{n(h)} {verb(lg, 'defend', 'defends')} the lineal {lg['name']} belt against {n(c)}. Preview: {S.SITE_URL}{b(lg)}/next/")
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
        "cbb": "basketball/mens-college-basketball", "women": "basketball/womens-college-basketball",
        # the leagues added in October 2026 (live score box on game day)
        "wnba": "basketball/wnba", "mls": "soccer/usa.1", "nwsl": "soccer/usa.nwsl", "epl": "soccer/eng.1",
        "laliga": "soccer/esp.1", "seriea": "soccer/ita.1", "bundesliga": "soccer/ger.1", "ligue1": "soccer/fra.1",
        "eredivisie": "soccer/ned.1"}


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
        ("schedule/", "Belt schedule", "Every game left on the holder's schedule, with win chances."),
        ("lean/", "The lean’s ledger", "Every AI pick on a belt game, graded."),
        ("defend-or-dethrone/", "Defend or dethrone", "Real belt games. Does the holder keep it? Build a streak."),
        ("heartbreak/", "Heartbreak list", "The closest calls, escapes and heartbreaks."),
        ("playoffs/", "The belt in the playoffs", "Every postseason belt game, season by season."),
        ("splits/", "Home, road & overtime" if any(bg.get("ot") for bg in d["belt_games"]) else "Home and road",
         "Road warriors, home fortresses and extra-time title changes." if any(bg.get("ot") for bg in d["belt_games"])
         else "Road warriors and home fortresses."),
        ("standings/", "Belt vs. the standings", "Did the holder have the best record?"),
        ("ap-poll/", "Belt vs. the AP poll", "Was the holder ranked? How often the belt and No. 1 lined up."),
        ("what-if/", "What if?", "Famous title changes flipped and replayed."),
        ("__groups__", "", ""),
        ("map/", "The belt map", "Every city that has held it, and the belt's journey."),
        ("states/", "By state", "Which states have held the belt longest."),
        ("relocations/", "The belt on the move", "Franchises that held it in more than one city."),
        ("web/", "Web of the belt", "Who took it from whom, as a network."),
        ("games/", "Every belt game", "Searchable by team, decade and result."),
        ("players/", "Players", "Everyone who has played in a belt game, with stats."),
        ("leaders/", "Belt-game leaders", "Career and single-game leaders when the belt is on the line."),
        ("data/", "Data & press", "Every reign and belt game as CSV, plus the API."),
        ("/embed/", "Badge for your site", "A badge that always shows the current holder."),
        ("feed.xml", "RSS feed", f"Every {lg['name']} title change, as it happens."),
        ("belt.ics", "Calendar", "Subscribe and the next title defense lands on your calendar."),
    ]
    if lg.get("key") in (None, "cbb", "women"):
        cards = [c for c in cards if c[0] != "playoffs/"]
    root = getattr(S, "OUT", "site")

    def built(h):
        if h.startswith("/") or h == "__groups__":
            return True
        path = os.path.join(root, out(lg, h))
        return os.path.exists(os.path.join(path, "index.html") if h.endswith("/") else path)
    cards = [c for c in cards if built(c[0])]
    gh = GROUP_HUB.get(lg.get("key", "cbb")) if (d.get("models") or {}).get("groups") else None
    cards = [(gh[0], gh[1], f"Belts that count only games inside each {gh[2]}.") if c[0] == "__groups__" else c for c in cards if c[0] != "__groups__" or gh]
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


# ========================================================= next-game preview ==
# The College Football Belt's preview layout: split matchup hero, what's at
# stake, odds line, "beat the lean" pick, AI preview, form, head to head and
# a sidebar.  Reads preview_extra.json from enrich_preview.py when present;
# every piece degrades gracefully without it.

def _extra(lg):
    for p in (os.path.join("data", lg.get("key", ""), "preview_extra.json"), os.path.join("data", "preview_extra.json")):
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return json.load(f) or {}, os.path.dirname(p)
            except ValueError:
                return {}, os.path.dirname(p)
    return {}, None


def _ledger(folder):
    p = os.path.join(folder or "", "lean_ledger.json")
    if folder and os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f) or []
        except ValueError:
            return []
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
        (f"If {sn(c)} {verb(lg, 'win', 'wins')}", "Belt changes hands · " + (f"{poss(sn(c))} {S.ordinal(c_reign_no)} reign" if pv["challenger_reigns"] else f"first reign in {unit_one(lg)} history")),
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
    gcal = _gcal(title, start, 3, f"{n(h)} {verb(lg, 'defend', 'defends')} the lineal {lg['name']} belt. {S.SITE_URL}{b(lg)}/next/", ", ".join(v for v in (vname, vcity) if v)) if start else None
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
    <p>{c_sent}</p>{f'<a class="mono more" href="{team_url(lg, c)}">Team page →</a>' if has_team_page(lg, c) else ''}</div>
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
         f"{n(h)} {verb(lg, 'defend', 'defends')} the lineal {lg['name']} championship belt {where} {n(c)} on {S.d_long(ng['date'])}: odds, the lean, recent form, head to head and what's at stake.",
         jsonld=ld)


# ============================================================ batch: more ==

MARGIN = {"nfl": 3, "nba": 3, "cbb": 3, "women": 3, "nhl": 1, "mlb": 1}


def _score(bg):
    hp, ap = (int(x) for x in bg["score"].split("-"))
    return hp, ap


def _winner_score(bg):
    hp, ap = _score(bg)
    return f"{max(hp, ap)}–{min(hp, ap)}"


def game_event_ld(lg, bg):
    """NET-6: schema.org SportsEvent for a played belt game page."""
    n = lg["team_name"]
    s = bg["season"]
    home = bg["home"]
    away = bg["opponent"] if home == bg.get("holder") else (bg.get("holder") or bg["opponent"])
    return {"@type": "SportsEvent", "name": f"{n(away, s)} at {n(home, s)}", "startDate": bg["date"],
            "sport": lg.get("sport", ""), "eventStatus": "https://schema.org/EventCompleted",
            "homeTeam": {"@type": "SportsTeam", "name": n(home, s)}, "awayTeam": {"@type": "SportsTeam", "name": n(away, s)},
            "description": _unescape(re.sub(r"<[^>]+>", "", _gline(lg, bg))) + f". Lineal {lg['name']} championship belt game {bg['n']:,}."}


def _gline(lg, bg):
    """'Cincinnati Bengals beat Jacksonville Jaguars 34–31' for a belt game."""
    n = lg["team_name"]
    s = bg["season"]
    hp, ap = _score(bg)
    if not bg.get("holder"):
        w, l = bg["new_holder"], bg["opponent"]
        return f"{tlink(lg, w, s)} beat {tlink(lg, l, s)} {_winner_score(bg)} in the first game"
    if hp == ap:
        return f"{e(n(bg['holder'], s))} and {e(n(bg['opponent'], s))} tied {hp}–{ap}"
    w = bg["home"] if hp > ap else (bg["opponent"] if bg["home"] == bg["holder"] else bg["holder"])
    l = bg["opponent"] if w == bg["holder"] else bg["holder"]
    note = f" ({e(bg['note'])})" if bg.get("note") else ""
    return f"{tlink(lg, w, s)} beat {tlink(lg, l, s)} {_winner_score(bg)}{note}"


GAME_PAGES = {}      # league key -> belt game numbers that get a page of their own (BH-2)
REIGN_PAGE_DEFENSES = 5


def plan_game_pages(lg, d):
    """Decide which belt games get their own page: a title change that opened a reign of
    5+ defenses, the current reign or the first game on record; any game with a recap;
    any game with a box score. Every other game lives only as its anchor on the season
    page (seasons/<year>/#g<n>). Call once per belt before building pages."""
    keep = set()
    by_open = {r.get("opened_by"): r for r in d["reigns"] if r.get("opened_by")}
    cur = d["reigns"][-1] if d["reigns"] else None
    boxed = {int(k) for k in _box_for(lg, d)} if lg.get("key") in BOX_SCHEMA else set()
    for n_, r in by_open.items():       # title changes (build_game_pages)
        if r.get("defenses", 0) >= REIGN_PAGE_DEFENSES or r is cur or r["index"] == 1 or n_ in boxed:
            keep.add(n_)
    rcs = _recaps(lg)                   # any game with a recap (title change or defense)
    for bg in d["belt_games"]:
        if rcs.get(f"{bg.get('holder')}|{bg['opponent']}|{bg['date']}"):
            keep.add(bg["n"])
    GAME_PAGES[lg["key"]] = keep
    TEAM_PAGES[lg["key"]] = {r["team"] for r in d["reigns"]} | {t for bg in d["belt_games"] for t in (bg.get("holder"), bg["opponent"]) if t}
    return keep


def reign_link(lg, d, r):
    """Where a reign links: its own page when notable (5+ defenses or current), else the
    game that opened it, else its first belt game on the season page."""
    if r.get("defenses", 0) >= 5 or r["index"] == d["reigns"][-1]["index"]:
        return f"{b(lg)}/reigns/{r['index']}/"
    by_n = d.get("_bg") or {bg["n"]: bg for bg in d["belt_games"]}
    first = r.get("opened_by") or (r["belt_games"][0] if r.get("belt_games") else None)
    bg = by_n.get(first) if first else None
    if not bg:
        return f"{b(lg)}/history/"
    return game_url(lg, bg) if r.get("opened_by") else f"{b(lg)}/seasons/{bg['season']}/#g{bg['n']}"


def game_has_page(lg, n_):
    pages = GAME_PAGES.get(lg["key"])
    return True if pages is None else n_ in pages


def game_url(lg, bg):
    if game_has_page(lg, bg["n"]):
        return f"{b(lg)}/games/{bg['n']}/"
    return f"{b(lg)}/seasons/{bg['season']}/#g{bg['n']}"


def build_schedule(lg, d):
    m = d.get("models") or {}
    sched = m.get("schedule") or []
    h = d["current"]["team"]
    n, sn = lg["team_name"], lg["short_name"]
    rows, still = [], 1.0
    for dt, home, away, ko, st, p in sched:
        opp = away if home == h else home
        rows.append(f'<tr><td class="mono">{S.weekday(dt)} {S.d_short(dt, True)}</td>'
                    f'<td><i style="background:{lg["team_colors"](opp)[0]}"></i>{"vs." if home == h else "at"} {tlink(lg, opp)}{" · " + post_word(lg) if st != "regular" else ""}</td>'
                    f'<td class="mono r">{pct(p)}</td><td class="mono r">{pct(still)}</td></tr>')
        still *= p
    table = (f'<div class="tablewrap"><table class="history"><thead><tr><th class="mono">Date</th><th class="mono">Game</th>'
             f'<th class="mono r">{e(sn(h))} win chance</th><th class="mono r">Chance it’s still a belt game</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
             if rows else f'<p class="intro">{e(n(h))} {verb(lg, "have", "has")} no games on the schedule yet ({e((d.get("status") or "").lower())}).</p>')
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt schedule</h1><span class="mono note">{e(poss(n(h)))} next {len(sched)} games</span></div>
  <p class="intro">Every game left on {e(poss(n(h)))} schedule is a belt game for as long as {verb(lg, "they keep", "it keeps")} winning. The last column is the chance {e(sn(h))} still {verb(lg, 'hold', 'holds')} the belt going into that game, so it's still for the title. Lose once and the schedule switches to the new holder’s.</p>
  {table}
  <p class="mono more"><a href="{b(lg)}/outlook/">Every way it can go: the belt tree →</a></p>
</section>"""
    page(lg, f"{lg['name']} belt schedule: every possible title defense", body, "schedule/",
         f"{poss(n(h))} upcoming {lg['name']} schedule: every game that could put the lineal belt on the line, with win chances.")


def build_lean(lg, d):
    _, folder = _extra(lg)
    ledger = _ledger(folder)
    by = {f"{bg['holder']}|{bg['opponent']}|{bg['date']}": bg for bg in d["belt_games"] if bg.get("holder")}
    n = lg["team_name"]
    rows, w, l = [], 0, 0
    for x in reversed(ledger):
        bg = by.get(x["key"])
        res = ""
        if bg and x.get("pick"):
            won = bg["new_holder"] if not bg["outcome"].endswith("(tie)") else x["holder"]
            ok = won == x["pick"]
            w += ok
            l += not ok
            res = f'<span class="tag{" chg" if ok else ""}">{"Right" if ok else "Wrong"}</span> {_winner_score(bg)}'
        else:
            res = '<span class="mono note">Pending</span>'
        rows.append(f'<tr><td class="mono">{S.d_short(x["date"], True)}</td><td>{e(n(x["holder"]))} vs. {e(n(x["challenger"]))}</td>'
                    f'<td>{e(n(x["pick"])) if x.get("pick") else "—"}<small>{e(x.get("score") or "")}</small></td><td class="r">{res}</td></tr>')
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The lean’s ledger</h1><span class="mono note">Every AI pick on a {e(lg['name'])} belt game</span></div>
  <p class="intro">Before every belt game, Claude reads the numbers on the preview page and makes a pick: the lean. Picks are logged the moment they're made and never revised, so here's the honest record.</p>
  {numbers([(f"{w}–{l}", "The lean’s record"), (pct(w / (w + l)) if w + l else "—", "Right"), (len(ledger), "Picks made"), (len(ledger) - w - l, "Pending")])}
  {f'<div class="tablewrap"><table class="history"><thead><tr><th class="mono">Date</th><th class="mono">Game</th><th class="mono">The pick</th><th class="mono r">Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>' if rows else '<p class="intro">The first pick lands with the next preview.</p>'}
  <p class="mono more"><a href="{b(lg)}/next/">This week’s lean →</a></p>
</section>"""
    page(lg, f"The lean’s ledger: AI picks on {lg['name']} belt games", body, "lean/",
         f"Every AI-written pick on a lineal {lg['name']} belt game, graded against the result.",
         robots=None if w + l else "noindex,follow")     # BH-13: no graded pick yet, nothing to index


def build_dod(lg, d):
    rng = random.Random(lg.get("key", "cbb") + "dod")
    pool = [bg for bg in d["belt_games"] if bg.get("holder") and not bg["outcome"].endswith("(tie)")]
    if len(pool) > 600:
        pool = rng.sample(pool, 600)
    n = lg["team_name"]
    items = [[bg["date"], n(bg["holder"], bg["season"]), n(bg["opponent"], bg["season"]), 1 if bg["home"] == bg["holder"] else 0,
              1 if bg["outcome"] == "changed" else 0, _winner_score(bg), bg["n"], sl(lg, bg["season"])] for bg in pool]
    changes = sum(1 for bg in d["belt_games"] if bg["outcome"] == "changed")
    total = sum(1 for bg in d["belt_games"] if bg.get("holder"))
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Defend or dethrone</h1><span class="mono note" id="dscore"></span></div>
  <p class="intro">A real {e(lg['name'])} belt game. Does the holder defend it, or does the challenger take the belt? Holders have defended {pct(1 - changes / total)} of the time. Keep your streak alive.</p>
  <div id="dg" class="quiz"></div>
</section>
<script>
(function(){{
var P={json.dumps(items, separators=(",", ":"))},K='belt-dod-{lg.get("key", "cbb")}',S={{best:0,cur:0,n:0,w:0}};
try{{S=Object.assign(S,JSON.parse(localStorage.getItem(K)||'{{}}'));}}catch(e){{}}
var MO=['January','February','March','April','May','June','July','August','September','October','November','December'];
function fd(d){{var p=d.split('-');return MO[+p[1]-1]+' '+(+p[2])+', '+p[0];}}
var G=document.getElementById('dg'),sc=document.getElementById('dscore');
function stat(){{sc.textContent='Streak '+S.cur+' · best '+S.best+' · '+S.w+'/'+S.n+' right';}}
function next(){{
 var q=P[Math.floor(Math.random()*P.length)];
 G.innerHTML='<p class="big">'+fd(q[0])+' · '+q[7]+'. <b>'+q[1]+'</b> put the belt on the line '+(q[3]?'at home against ':'on the road at ')+'<b>'+q[2]+'</b>.</p><div class="opts"><button class="mono" data-v="0">'+q[1]+' defend it</button><button class="mono" data-v="1">'+q[2]+' take it</button></div><p class="reveal"></p>';
 G.querySelectorAll('button').forEach(function(b){{b.onclick=function(){{
  var ok=(+b.dataset.v)===q[4];S.n++;if(ok){{S.w++;S.cur++;S.best=Math.max(S.best,S.cur);}}else S.cur=0;
  try{{localStorage.setItem(K,JSON.stringify(S));}}catch(e){{}}
  G.querySelectorAll('button').forEach(function(x){{x.disabled=true;if((+x.dataset.v)===q[4])x.className+=' right';else x.className+=' wrong';}});
  G.querySelector('.reveal').innerHTML=(ok?'Right. ':'Nope. ')+(q[4]?q[2]+' won '+q[5]+' and took the belt.':q[1]+' won '+q[5]+' and kept it.')+' <a href="{b(lg)}/seasons/'+q[0].slice(0,4)+'/">Season →</a> <button class="mono nextq">Next game →</button>';
  G.querySelector('.nextq').onclick=next;stat();
 }};}});
}}
stat();next();
}})();
</script>"""
    page(lg, f"Defend or dethrone: the {lg['name']} belt guessing game", body, "defend-or-dethrone/",
         f"Real {lg['name']} belt games from history. Does the holder defend it or lose it? Build a streak.")


def build_heartbreak(lg, d):
    thr = MARGIN.get(lg.get("key", "cbb"), 3)
    n = lg["team_name"]
    unit_word = {"nhl": "goal", "mlb": "run"}.get(lg.get("key"), "point")
    close_losses, whisker, lost_close = Counter(), Counter(), Counter()
    recent = []
    for bg in d["belt_games"]:
        if not bg.get("holder") or bg["outcome"].endswith("(tie)"):
            continue
        hp, ap = _score(bg)
        if abs(hp - ap) > thr:
            continue
        if bg["outcome"] == "changed":
            lost_close[bg["holder"]] += 1
            recent.append(bg)
        else:
            close_losses[bg["opponent"]] += 1
            whisker[bg["holder"]] += 1
            recent.append(bg)
    t1 = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v}</td></tr>' for t, v in close_losses.most_common(12))
    t2 = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v}</td></tr>' for t, v in lost_close.most_common(12))
    t3 = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v}</td></tr>' for t, v in whisker.most_common(12))
    rec = "".join(f'<tr><td class="mono">{S.d_short(bg["date"], True)}</td><td>{_gline(lg, bg)}</td><td class="r">{CHG_TAG if bg["outcome"] == "changed" else DEF_TAG}</td></tr>'
                  for bg in recent[-25:][::-1])
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The heartbreak list</h1><span class="mono note">Belt games decided by {S.plural(thr, unit_word)} or less</span></div>
  <p class="intro">{len(recent):,} belt games have come down to {S.plural(thr, unit_word)} or less. These are the {unit(lg)} who got closest without taking it, and the holders who survived by a whisker.</p>
  <div class="two">
    <div><h2 class="disp sub">So close: challengers</h2><p class="mono note">Lost a belt game by {thr} or less</p><table class="history"><tbody>{t1}</tbody></table></div>
    <div><h2 class="disp sub">Lost it by a whisker</h2><p class="mono note">Holders beaten by {thr} or less</p><table class="history"><tbody>{t2}</tbody></table></div>
  </div>
  <h2 class="disp sub">Escape artists</h2><p class="mono note">Holders who defended by {thr} or less</p>
  <div class="tablewrap"><table class="history"><tbody>{t3}</tbody></table></div>
  <h2 class="disp sub">Latest nail-biters</h2>
  <div class="tablewrap"><table class="history"><tbody>{rec}</tbody></table></div>
</section>"""
    page(lg, f"The {lg['name']} belt heartbreak list", body, "heartbreak/",
         f"Every lineal {lg['name']} belt game decided by {thr} {unit_word}{'s' if thr > 1 else ''} or less: the closest calls, the escapes and the heartbreaks.")


def caps(lg, d):
    """BH-13: what a league has, so pages that don't apply aren't built. A league dict can set any of
    these explicitly; otherwise they come from the data. The More hub hides cards for pages not built."""
    nations = lg.get("unit") == "nations"
    post = any(bg["season_type"] != "regular" for bg in d["belt_games"])
    return {
        "has_postseason": lg.get("has_postseason", post and lg.get("key") not in (None, "cbb", "women")),
        "has_standings": lg.get("has_standings", not nations),     # national teams have no table or regular season
        "has_champions": lg.get("has_champions", not nations),
        "has_ot": lg.get("has_ot", any(bg.get("ot") for bg in d["belt_games"])),
    }


def build_playoffs(lg, d):
    if not caps(lg, d)["has_postseason"]:
        return
    post = [bg for bg in d["belt_games"] if bg["season_type"] != "regular"]
    by = defaultdict(list)
    for bg in post:
        by[bg["season"]].append(bg)
    ch = [bg for bg in post if bg["outcome"] == "changed"]
    most = Counter(bg["new_holder"] for bg in ch)
    rows = []
    for s in sorted(by, reverse=True):
        gs = by[s]
        first = gs[0]["holder"] or gs[0]["new_holder"]
        last = gs[-1]["new_holder"]
        c = sum(1 for bg in gs if bg["outcome"] == "changed")
        rows.append(f'<tr><td class="mono"><a href="{b(lg)}/seasons/{s}/">{e(sl(lg, s))}</a></td><td>{tlink(lg, first, s)}</td><td>{tlink(lg, last, s)}</td>'
                    f'<td class="mono r">{len(gs)}</td><td class="mono r">{c}</td></tr>')
    top = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v}</td></tr>' for t, v in most.most_common(10))
    latest = "".join(f'<tr><td class="mono">{S.d_short(bg["date"], True)}</td><td>{_gline(lg, bg)}</td></tr>' for bg in ch[-15:][::-1])
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt in the {post_word(lg)}</h1><span class="mono note">{len(post):,} {post_word(lg)} belt games · {len(ch):,} title changes</span></div>
  <p class="intro">When the holder makes the {post_word(lg)}, every game is for two titles at once. The belt only moves in the {post_word(lg)} if the holder is there, so a lot of years it sits out. These are the years it didn't.</p>
  <div class="two">
    <div><h2 class="disp sub">Most {post_word(lg)} title changes won</h2><table class="history"><tbody>{top}</tbody></table></div>
    <div><h2 class="disp sub">Latest {post_word(lg)} title changes</h2><table class="history"><tbody>{latest}</tbody></table></div>
  </div>
  <h2 class="disp sub">Season by season</h2>
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Season</th><th class="mono">Carried it in</th><th class="mono">Came out with it</th><th class="mono r">Games</th><th class="mono r">Changes</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
</section>"""
    page(lg, f"The {lg['name']} belt in the {post_word(lg)}", body, "playoffs/",
         f"Every {post_word(lg)} game with the lineal {lg['name']} belt on the line: who carried it in, who came out with it.")


def build_splits(lg, d):
    n = lg["team_name"]
    road_take, home_take, home_def, road_def = Counter(), Counter(), Counter(), Counter()
    ot = []
    for bg in d["belt_games"]:
        if not bg.get("holder") or bg.get("neutral"):
            continue
        if bg["outcome"] == "changed":
            (home_take if bg["home"] == bg["opponent"] else road_take)[bg["opponent"]] += 1
        elif bg["outcome"].startswith("retained"):
            (home_def if bg["home"] == bg["holder"] else road_def)[bg["holder"]] += 1
        if bg.get("ot") and bg["outcome"] == "changed":
            ot.append(bg)
    tot_h = sum(1 for bg in d["belt_games"] if bg.get("holder") and bg["home"] == bg["holder"])
    def_h = sum(home_def.values())
    tot_r = sum(1 for bg in d["belt_games"] if bg.get("holder") and bg["home"] != bg["holder"] and not bg.get("neutral"))
    def_r = sum(road_def.values())
    tab = lambda c: "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono r">{v}</td></tr>' for t, v in c.most_common(10))
    ot_rows = "".join(f'<tr><td class="mono">{S.d_short(bg["date"], True)}</td><td>{_gline(lg, bg)}</td></tr>' for bg in ot[-20:][::-1])
    ot_word = {"nhl": "overtime and shootouts", "pwhl": "overtime and shootouts", "mlb": "extra innings",
               "mls": "extra time and penalties", "nwsl": "extra time and penalties"}.get(lg.get("key"), "overtime")
    # show the extra-time figure only where the data records it (soccer league play, international
    # matches and the CFL/NFL/MLB sources don't) (BH-7)
    has_ot = any(bg.get("ot") for bg in d["belt_games"])
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Home, road{" and extra time" if has_ot else ""}</h1></div>
  {numbers([(pct(def_h / tot_h) if tot_h else "—", "Holders defend at home"), (pct(def_r / tot_r) if tot_r else "—", "Holders defend on the road"), (f"{sum(road_take.values()):,}", "Title changes on the road")] + ([(f"{len(ot):,}", f"Title changes in {ot_word}")] if has_ot else []))}
  <div class="two">
    <div><h2 class="disp sub">Road warriors</h2><p class="mono note">Took the belt in the holder’s building</p><table class="history"><tbody>{tab(road_take)}</tbody></table></div>
    <div><h2 class="disp sub">Home fortresses</h2><p class="mono note">Most successful home defenses</p><table class="history"><tbody>{tab(home_def)}</tbody></table></div>
  </div>
  <div class="two">
    <div><h2 class="disp sub">Took it at home</h2><table class="history"><tbody>{tab(home_take)}</tbody></table></div>
    <div><h2 class="disp sub">Defended on the road</h2><table class="history"><tbody>{tab(road_def)}</tbody></table></div>
  </div>
  {f'<h2 class="disp sub">Title changes in {ot_word}</h2><div class="tablewrap"><table class="history"><tbody>{ot_rows}</tbody></table></div>' if ot_rows else ''}
</section>"""
    page(lg, f"{lg['name']} belt: home, road{' and extra time' if has_ot else ''}", body, "splits/",
         f"How the lineal {lg['name']} belt moves at home and on the road: road warriors, home fortresses"
         + (f" and title changes in {ot_word}." if has_ot else " and the holders who travel best."))


def build_standings(lg, d):
    if not caps(lg, d)["has_standings"]:
        return
    st = (d.get("models") or {}).get("standings") or []
    # a season's regular season is complete once none of its regular-season games are left on the schedule (BH-6)
    live = {s["season"] for s in d.get("seasons", []) if s.get("regular_open", s.get("in_progress"))}
    st = [x for x in st if x["season"] not in live]
    if not st:
        return
    rec = lambda v: f"{v[0]}–{v[1]}" + (f"–{v[2]}" if v[2] else "")
    m = sum(1 for x in st if x["match"])
    top3 = sum(1 for x in st if x["holder_rank"] <= 3)
    avg = sum(x["holder_rank"] for x in st) / len(st)
    have = {x["season"] for x in d.get("seasons", [])}      # seasons with belt games have a page

    def slink(s_):
        return f'<a href="{b(lg)}/seasons/{s_}/">{e(sl(lg, s_))}</a>' if s_ in have else e(sl(lg, s_))
    rows = "".join(f'<tr><td class="mono">{slink(x["season"])}</td>'
                   f'<td>{tlink(lg, x["best"], x["season"])} <small>{rec(x["best_rec"])}</small></td>'
                   f'<td>{tlink(lg, x["holder"], x["season"]) if x["holder"] else "—"} <small>{rec(x["holder_rec"])}</small></td>'
                   f'<td class="mono r">{S.ordinal(x["holder_rank"])} of {x["teams"]}{SAME_SHORT if x["match"] else ""}</td></tr>' for x in reversed(st))
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt vs. the standings</h1><span class="mono note">{len(st)} completed seasons</span></div>
  <p class="intro">Is the belt a good judge of the best team? Here's who held it when each regular season ended, next to the best record that year.</p>
  {numbers([(m, "Seasons it matched"), (pct(m / len(st)), "Match rate"), (top3, "Holder in the top 3"), (f"{avg:.1f}", "Holder's average rank")])}
  <div class="tablewrap"><table class="history"><thead><tr><th class="mono">Season</th><th class="mono">Best record</th><th class="mono">Holder at the end</th><th class="mono r">Holder's rank</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>"""
    page(lg, f"The {lg['name']} belt vs. the standings", body, "standings/",
         f"Season by season: who held the lineal {lg['name']} belt at the end of the regular season vs. the team with the best record.")


def build_data(lg, d):
    import csv
    import io
    n = lg["team_name"]
    f1 = io.StringIO()
    w = csv.writer(f1)
    w.writerow(["reign", "team", "team_reign_number", "start_date", "end_date", "defenses", "days", "won_from", "won_score"])
    for r in d["reigns"]:
        w.writerow([r["index"], n(r["team"], r.get("season")), r["reign_no"], r["start_date"], r.get("end_date") or "",
                    r.get("defenses", 0), r["days"], n(r["won_from"]) if r.get("won_from") else "", r.get("won_score") or ""])
    S.write(out(lg, "data/reigns.csv"), f1.getvalue())
    f2 = io.StringIO()
    w = csv.writer(f2)
    w.writerow(["belt_game", "date", "season", "season_type", "holder", "opponent", "home_team", "score_home_away", "outcome", "new_holder", "note"])
    for bg in d["belt_games"]:
        w.writerow([bg["n"], bg["date"], bg["season"], bg["season_type"], n(bg["holder"], bg["season"]) if bg.get("holder") else "",
                    n(bg["opponent"], bg["season"]), n(bg["home"], bg["season"]), bg["score"], bg["outcome"], n(bg["new_holder"], bg["season"]), bg.get("note") or ""])
    S.write(out(lg, "data/belt-games.csv"), f2.getvalue())
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block prose">
  <div class="head"><h1 class="disp">{e(lg['name'])} belt data &amp; press</h1></div>
  <p>Free to use with a link back. Updated every few hours.</p>
  <ul>
    <li><a href="{b(lg)}/data/reigns.csv">reigns.csv</a>: all {len(d['reigns']):,} reigns (holder, dates, defenses, days, how they won it)</li>
    <li><a href="{b(lg)}/data/belt-games.csv">belt-games.csv</a>: all {len(d['belt_games']):,} belt games with scores and outcomes</li>
    <li><a href="/api/current.json">/api/current.json</a>: the current holder and next defense, as JSON</li>
    <li><a href="{b(lg)}/feed.xml">RSS</a> and <a href="{b(lg)}/belt.ics">calendar</a> feeds</li>
    <li><a href="/embed/">Badges</a> for your site</li>
  </ul>
  <h2 class="disp sub">Writing about the belt?</h2>
  <p>The rules are simple: the belt starts with the first game on record and passes to whoever beats the holder. Ties go to the holder. Scores come from public game records; see <a href="/rules/">the rules</a> for sources. Questions or corrections: <a href="mailto:{'hello@collegebasketballbelt.com' if lg.get('key') in ('cbb', 'women') else 'hello@beltholders.com'}">email us</a>.</p>
</section>"""
    base = S.SITE_URL + b(lg)
    ld = {"@type": "Dataset", "name": f"Lineal {lg['name']} championship belt: reigns and belt games",
          "description": f"Every lineal {lg['name']} belt reign ({len(d['reigns']):,}) and belt game ({len(d['belt_games']):,}) since the first game on record, with holders, dates, scores and outcomes.",
          "url": f"{base}/data/", "isAccessibleForFree": True,
          "creator": {"@type": "Organization", "name": SITE_NAME},
          "temporalCoverage": f"{d['belt_games'][0]['date']}/{d['belt_games'][-1]['date']}" if d["belt_games"] else None,
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{base}/data/reigns.csv"},
                           {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{base}/data/belt-games.csv"}]}
    page(lg, f"{lg['name']} belt data: every reign and belt game (CSV)", body, "data/",
         f"Download every lineal {lg['name']} belt reign and belt game as CSV, plus the JSON API and feeds.", jsonld=ld)


def _recaps(lg):
    for p in (os.path.join("data", lg.get("key", ""), "recaps.json"), os.path.join("data", "recaps.json")):
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return json.load(f) or {}
            except ValueError:
                return {}
    return {}


def recap_html(lg, rc):
    if not rc:
        return ""
    n = lg["team_name"]
    paras = "".join(f"<p>{e(x)}</p>" for x in rc.get("recap") or [])
    lead = "".join(f'<tr><td>{e(l["player"])}<small>{e(n(l["team"])) if l.get("team") else ""}</small></td><td class="mono">{e(l.get("category") or "")}</td><td class="mono r">{e(l["line"])}</td></tr>'
                   for l in rc.get("leaders") or [])
    ls = rc.get("linescore") or []
    lsh = ""
    if ls and all(r.get("periods") for r in ls):
        k = max(len(r["periods"]) for r in ls)
        head = "".join(f'<th class="mono r">{i + 1}</th>' for i in range(k))
        rows = "".join(f'<tr><td>{e(r.get("team") or "")}</td>' + "".join(f'<td class="mono r">{e(x)}</td>' for x in r["periods"]) + f'<td class="mono r"><b>{e(str(r.get("score") or ""))}</b></td></tr>' for r in sorted(ls, key=lambda r: r.get("home_away") != "away"))
        lsh = f'<div class="tablewrap"><table class="history linescore"><thead><tr><th><span class="sr">Team</span></th>{head}<th class="mono r">T</th></tr></thead><tbody>{rows}</tbody></table></div>'
    return f"""<article class="pv-article recap">
  <div class="kicker">The recap · AI-written</div>
  <h2 class="disp">{e(rc.get('headline') or '')}</h2>
  {lsh}{paras}
  {f'<h3 class="kicker">Leaders</h3><div class="tablewrap"><table class="history"><tbody>{lead}</tbody></table></div>' if lead else ''}
  <p class="note">Written by Claude from ESPN's box score for this game.</p>
</article>"""


def build_game_pages(lg, d):
    """One page per title change (the game that opened each reign), plus
    every belt game with a recap."""
    rcs = _recaps(lg)
    n = lg["team_name"]
    bgs = d["belt_games"]
    reign_by_open = {r.get("opened_by"): r for r in d["reigns"] if r.get("opened_by")}
    by_index = {r["index"]: r for r in d["reigns"]}
    changes = [bg for bg in bgs if bg["outcome"] in ("changed", "established")]
    for i, bg in enumerate(changes):
        r = reign_by_open.get(bg["n"])
        if not r or not game_has_page(lg, bg["n"]):
            continue
        s = bg["season"]
        w, l = bg["new_holder"], bg.get("holder") or bg["opponent"]
        prev_r = by_index.get(r["index"] - 1)
        nxt_r = by_index.get(r["index"] + 1)
        p, s2 = lg["team_colors"](w)
        top, bottom, ink, accent = S.plate(p, s2)
        where = "at home" if bg["home"] == w else ("on a neutral floor" if bg.get("neutral") else "on the road")
        prev_txt = (f"{e(n(l, s))} had held it since {S.d_long(prev_r['start_date'])}, with {S.plural(prev_r.get('defenses', 0), 'defense')} over {prev_r['days']:,} days."
                    if prev_r and bg.get("holder") else "The first game on record: the belt starts here.")
        after = (f"{e(n(w, s))} held it for {r['days']:,} days and {S.plural(r.get('defenses', 0), 'defense')}"
                 + (f", then lost it to {e(n(nxt_r['team']))} on {S.d_long(nxt_r['start_date'])}." if nxt_r else ", and still hold it." if not lg.get("singular") else ", and still holds it."))
        pl = changes[i - 1] if i else None
        nl = changes[i + 1] if i + 1 < len(changes) else None
        prev_a = f'<a href="{game_url(lg, pl)}">← Belt change {pl["n"]:,}</a>' if pl else "<span></span>"
        next_a = f'<a href="{game_url(lg, nl)}">Next belt change →</a>' if nl else "<span></span>"
        nav = (f'<nav class="gnav mono">{prev_a}<a href="{b(lg)}/seasons/{s}/#g{bg["n"]}">{e(sl(lg, s))} season</a>{next_a}</nav>')
        body = f"""{S.subnav(lg, "history")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">Belt game {bg['n']:,} · {S.d_long(bg['date'])}{' · ' + post_word(lg) if bg['season_type'] != 'regular' else ''}</div>
    <h1 class="disp holder" style="--fit:{max(len(x) for x in n(w, s).split())}">{e(n(w, s))} {verb(lg, 'take', 'takes')} the belt</h1>
    <p class="lede">{e(n(w, s))} beat {e(n(l, s))} {_winner_score(bg)}{(' (' + e(bg['note']) + ')') if bg.get('note') else ''} {where} to start reign {r['index']:,} of the {e(lg['name'])} belt, the {S.ordinal(r['reign_no'])} for the {unit_one(lg)}.</p>
  </div>
</section>
<section class="wrap block prose">
  {recap_html(lg, rcs.get(f"{bg.get('holder')}|{bg['opponent']}|{bg['date']}"))}
  <p>{prev_txt}</p>
  <p>{after}</p>
  {numbers([(f"{r['index']:,}", "Reign number"), (r['reign_no'], "Team's reign"), (r.get('defenses', 0), "Defenses"), (f"{r['days']:,}", "Days held")])}
  {box_html(lg, d, bg)}
  <p class="mono more"><a href="{team_url(lg, w)}">{e(n(w))} belt history →</a> · <a href="{b(lg)}/compare/?a={w}&amp;b={l}">{e(lg['short_name'](w))} vs. {e(lg['short_name'](l))} →</a></p>
  {nav}
</section>"""
        page(lg, f"{lg['short_name'](w)} {_winner_score(bg)} {lg['short_name'](l)}: {belt_tag(lg)}, {S.d_short(bg['date'], True)}", body,
             f"games/{bg['n']}/",
             f"{n(w, s)} beat {n(l, s)} {_winner_score(bg)} on {S.d_long(bg['date'])} to take the lineal {lg['name']} championship belt. Reign {r['index']:,}: {S.plural(r.get('defenses', 0), 'defense')}, {r['days']:,} days.",
             og_title=f"{n(w, s)} beat {n(l, s)} {_winner_score(bg)} for the {lg['name']} belt ({S.d_short(bg['date'], True)})",
             jsonld=game_event_ld(lg, bg))


def build_defense_pages(lg, d):
    rcs = _recaps(lg)
    if not rcs:
        return
    n = lg["team_name"]
    by_index = {r["index"]: r for r in d["reigns"]}
    for bg in d["belt_games"]:
        rc = rcs.get(f"{bg.get('holder')}|{bg['opponent']}|{bg['date']}")
        if not rc or bg["outcome"] in ("changed", "established"):
            continue
        s = bg["season"]
        h, o = bg["holder"], bg["opponent"]
        r = by_index.get(bg.get("reign"))
        p, s2 = lg["team_colors"](h)
        top, bottom, ink, accent = S.plate(p, s2)
        k = (r.get("belt_games") or []).index(bg["n"]) if r and bg["n"] in (r.get("belt_games") or []) else None
        body = f"""{S.subnav(lg, "history")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">Belt game {bg['n']:,} · {S.d_long(bg['date'])}</div>
    <h1 class="disp holder" style="--fit:{max(len(x) for x in n(h, s).split())}">{e(n(h, s))} {verb(lg, 'keep', 'keeps')} the belt</h1>
    <p class="lede">{_gline(lg, bg)}.{(' Defense number ' + str(k + 1) + ' of reign ' + format(r['index'], ',') + '.') if k is not None and r else ''}</p>
  </div>
</section>
<section class="wrap block prose">
  {recap_html(lg, rc)}
  {box_html(lg, d, bg)}
  <p class="mono more"><a href="{b(lg)}/seasons/{s}/#g{bg['n']}">{e(sl(lg, s))} season →</a> · <a href="{team_url(lg, h)}">{e(n(h))} belt history →</a></p>
</section>"""
        page(lg, f"{rc.get('headline') or n(h, s) + ' keep the ' + lg['name'] + ' belt'} ({S.d_short(bg['date'], True)})", body, f"games/{bg['n']}/",
             f"{n(h, s)} defended the lineal {lg['name']} belt against {n(o, s)} on {S.d_long(bg['date'])}. Recap, line score and leaders.",
             jsonld=game_event_ld(lg, bg))


def latest_recap_card(lg, d):
    rcs = _recaps(lg)
    if not rcs:
        return ""
    key, rc = max(rcs.items(), key=lambda kv: kv[1]["date"])
    bg = next((x for x in reversed(d["belt_games"]) if f"{x.get('holder')}|{x['opponent']}|{x['date']}" == key), None)
    if not bg:
        return ""
    return (f'<section class="wrap block"><div class="head"><h2 class="disp">Last belt game</h2><a class="mono more" href="{game_url(lg, bg)}">Full recap →</a></div>'
            f'<a class="recapcard" href="{game_url(lg, bg)}"><span class="mono">{S.d_long(bg["date"])}</span><b class="disp">{e(rc.get("headline") or "")}</b>'
            f'<p>{e((rc.get("recap") or [""])[0])}</p></a></section>')


def build_batch2(lg, d):
    build_players(lg, d)
    build_schedule(lg, d)
    build_lean(lg, d)
    build_dod(lg, d)
    build_heartbreak(lg, d)
    build_playoffs(lg, d)
    build_splits(lg, d)
    build_standings(lg, d)
    build_data(lg, d)
    build_game_pages(lg, d)
    build_defense_pages(lg, d)
    build_what_if(lg, d)
    build_geo(lg, d)
    build_groups(lg, d)
    build_relocations(lg, d)
    build_polls(lg, d)


# ================================================== long tables (tablekit) ==

PAGE_SIZE = 100


def paged_table(lg, rel, *, title, description, heading, note, intro, columns, rows, filters=(), order_labels=("Newest first", "Oldest first"),
                subnav_on="more", extra="", empty="Nothing matches.", size=PAGE_SIZE):
    """A long table as real pages (/rel, /rel/page/N/) plus search, filters,
    sorting and client-side paging from rel/data.json via /tablekit.js.

    columns: [(label, css_class, sortable)]; rows (already in default order):
    {"c": [cell html], "t": search text, "k": [sort keys], "f": {filter: value}, "cur": bool}
    filters: [(key, label, [(value, label)])]"""
    S.write(out(lg, rel + "data.json"), json.dumps({"rows": rows}, separators=(",", ":")))
    cls = [c[1] for c in columns]
    total = max(1, -(-len(rows) // size))
    base = f"{b(lg)}/{rel}"
    head = "".join(f'<th class="mono {c[1]}"' + (f' data-k="{i}"' if c[2] else "") + f'>{e(c[0])}</th>' for i, c in enumerate(columns))
    sel = "".join(f'<select data-f="{k}" aria-label="{e(lab)}"><option value="">{e(lab)}</option>'
                  + "".join(f'<option value="{e(str(v))}">{e(t)}</option>' for v, t in opts) + "</select>" for k, lab, opts in filters)
    seg = (f'<div class="tk-seg" role="group" aria-label="Order"><button type="button" data-order="default" class="on">{e(order_labels[0])}</button>'
           f'<button type="button" data-order="reverse">{e(order_labels[1])}</button></div>') if order_labels else ""
    for p in range(1, total + 1):
        chunk = rows[(p - 1) * size: p * size]
        body_rows = "".join('<tr' + (' class="cur"' if x.get("cur") else "") + '>' + "".join(
            f'<td{f" class={chr(34)}{cls[i]}{chr(34)}" if cls[i] else ""}>{c}</td>' for i, c in enumerate(x["c"])) + "</tr>" for x in chunk)

        def link(q, label):
            return f'<a href="{base if q == 1 else base + f"page/{q}/"}">{label}</a>'

        nums = sorted({1, total, *[q for q in range(p - 2, p + 3) if 1 <= q <= total]})
        pager, last = [], 0
        if p > 1:
            pager.append(link(p - 1, "← Prev"))
        for q in nums:
            if q - last > 1:
                pager.append('<span class="tk-gap">…</span>')
            pager.append(f'<span class="tk-on">{q}</span>' if q == p else link(q, q))
            last = q
        if p < total:
            pager.append(link(p + 1, "Next →"))
        pg = "".join(pager) if total > 1 else ""
        cfg = json.dumps({"data": base + "data.json", "base": base, "size": size, "page": p, "cls": cls})
        start = (p - 1) * size + 1
        body = f"""{S.subnav(lg, subnav_on)}
<section class="wrap block" data-tablekit='{e(cfg)}'>
  <div class="head"><h1 class="disp">{e(heading)}{f' <span class="mono note">page {p}</span>' if p > 1 else ''}</h1><span class="mono note">{note}</span></div>
  {intro if p == 1 else ''}
  {extra if p == 1 else ''}
  <div class="tk-bar"><input class="tk-q" type="search" placeholder="Filter by team…" aria-label="Filter by team" autocomplete="off">{sel}{seg}<span class="tk-info mono">{start:,}–{start + len(chunk) - 1:,} of {len(rows):,} · page {p} of {total}</span></div>
  <nav class="tk-pager" aria-label="Pages, top">{pg}</nav>
  <div class="tablewrap"><table class="history"><thead><tr>{head}</tr></thead><tbody>{body_rows}</tbody></table></div>
  <p class="tk-empty">{e(empty)}</p>
  <nav class="tk-pager" aria-label="Pages, bottom">{pg}</nav>
</section>
<script src="/tablekit.js" defer></script>"""
        page(lg, title + (f" (page {p})" if p > 1 else ""), body, rel if p == 1 else f"{rel}page/{p}/",
             description + (f" Page {p} of {total}." if p > 1 else ""))


def _decade_opts(years):
    return [(dcd, f"{dcd}s") for dcd in sorted({y // 10 * 10 for y in years}, reverse=True)]


def build_history_table(lg, d):
    n = lg["team_name"]
    by_n = {bg["n"]: bg for bg in d["belt_games"]}
    cur_i = d["reigns"][-1]["index"]
    rows = []
    for r in reversed(d["reigns"]):
        t = r["team"]
        s = r.get("season") or int(r["start_date"][:4])
        how = (f"beat {e(n(r['won_from'], s))} {S.won_score_text(r)}" if r.get("won_from")
               else "reclaimed (previous holder left)" if r.get("reclaimed_after") else "first game" if not r.get("seed") else "starting holder")
        url = reign_link(lg, d, r)
        yr = int(r["start_date"][:4])
        rows.append({
            "c": [f'<a href="{url}">{r["index"]:,}</a>',
                  f'<i style="background:{lg["team_colors"](t)[0]}"></i><a href="{team_url(lg, t)}">{e(n(t, s))}</a><small>{how}</small>',
                  S.d_short(r["start_date"], True), S.d_short(r["end_date"], True) if r.get("end_date") else "Holding",
                  str(r.get("defenses", 0)), f'{r["days"]:,}'],
            "t": (n(t) + " " + n(t, s)).lower(),
            "k": [r["index"], n(t), r["start_date"], r.get("end_date") or "9999", r.get("defenses", 0), r["days"]],
            "f": {"decade": yr // 10 * 10, "team": t},
            "cur": r["index"] == cur_i})
    teams = sorted({r["team"] for r in d["reigns"]}, key=lambda t: n(t))
    paged_table(lg, "history/", title=f"{lg['long_name']}: every reign since {lg['first_season']}",
                description=f"The complete lineal {lg['name']} championship history: all {len(d['reigns']):,} reigns since {lg['first_season']}, searchable and sortable.",
                heading=f"Every {lg['name']} reign", note=f"{len(d['reigns']):,} reigns · {len(d['belt_games']):,} belt games since {lg['first_season']}",
                intro=f'<p class="intro">Every reign, newest first. Search a team, pick a decade, or click a column to sort. <a href="{b(lg)}/games/">Every belt game →</a></p>', subnav_on="history",
                columns=[("#", "mono n", True), ("Holder", "", True), ("Won", "mono", True), ("Lost", "mono", True), ("Def.", "mono r", True), ("Days", "mono r", True)],
                rows=rows, filters=[("decade", "Any decade", _decade_opts(int(r["start_date"][:4]) for r in d["reigns"])),
                                    ("team", "Any team", [(t, n(t)) for t in teams])],
                empty="No reigns match.")


def build_all_games(lg, d):
    n = lg["team_name"]
    rows = []
    for bg in reversed(d["belt_games"]):
        s = bg["season"]
        kind = "c" if bg["outcome"] in ("changed", "established") else "t" if bg["outcome"].endswith("(tie)") else "d"
        tag = CHG_TAG if kind == "c" else '<span class="tag">Tie · defense</span>' if kind == "t" else DEF_TAG
        link = f'<a href="{game_url(lg, bg)}">{bg["n"]:,}</a>' if kind == "c" else f'{bg["n"]:,}'
        teams_ = [x for x in (bg.get("holder"), bg["opponent"]) if x]
        rows.append({
            "c": [link, S.d_short(bg["date"], True), _gline(lg, bg) + (f' <span class="tag post">{post_word(lg).capitalize()}</span>' if bg["season_type"] != "regular" else ""), tag],
            "t": " ".join(n(x) + " " + n(x, s) for x in teams_).lower() + " " + str(s),
            "k": [bg["n"], bg["date"], n(bg["new_holder"]), kind],
            "f": {"kind": kind, "type": "p" if bg["season_type"] != "regular" else "r", "decade": int(bg["date"][:4]) // 10 * 10}})
    paged_table(lg, "games/", title=f"Every {lg['name']} belt game",
                description=f"All {len(d['belt_games']):,} games with the lineal {lg['name']} belt on the line, searchable by team, decade and result.",
                heading=f"Every {lg['name']} belt game", note=f"{len(d['belt_games']):,} games", subnav_on="history",
                intro=f'<p class="intro">Every game with the belt on the line, title changes and defenses. Filter by team, decade or result. <a href="{b(lg)}/history/">The reigns →</a></p>',
                columns=[("Game", "mono n", True), ("Date", "mono", True), ("Result", "", True), ("", "r", True)],
                rows=rows, filters=[("kind", "Any result", [("c", "Title changes"), ("d", "Defenses"), ("t", "Ties")]),
                                    ("type", "Regular + " + post_word(lg), [("r", "Regular season"), ("p", post_word(lg).capitalize())]),
                                    ("decade", "Any decade", _decade_opts(int(bg["date"][:4]) for bg in d["belt_games"]))],
                empty="No belt games match.")


def build_teams_table(lg, d):
    n = lg["team_name"]
    by = defaultdict(list)
    for r in d["reigns"]:
        by[r["team"]].append(r)
    recent = set((d.get("models") or {}).get("elo") or {})
    rows = []
    for t, rs in sorted(by.items(), key=lambda kv: -sum(r["days"] for r in kv[1])):
        days = sum(r["days"] for r in rs)
        last = rs[-1]
        rows.append({
            "c": [f'<i style="background:{lg["team_colors"](t)[0]}"></i><a href="{team_url(lg, t)}">{e(n(t))}</a>',
                  str(len(rs)), f"{days:,}", str(sum(r.get("defenses", 0) for r in rs)), str(max(r.get("defenses", 0) for r in rs)),
                  "Now" if not last.get("end_date") else last["end_date"][:4]],
            "t": n(t).lower(), "k": [n(t), len(rs), days, sum(r.get("defenses", 0) for r in rs), max(r.get("defenses", 0) for r in rs), last.get("end_date") or "9999"],
            "f": {"active": "y" if t in recent else "n"}, "cur": not last.get("end_date")})
    word = unit(lg)
    paged_table(lg, "teams/", title=f"{lg['name']} belt: every team", subnav_on="teams",
                description=f"Every {word[:-1]} that has held the lineal {lg['name']} championship belt, sortable by reigns, days and defenses.",
                heading=f"Every {word[:-1]} that has held the {lg['name']} belt", note=f"{len(by)} {word}",
                intro=f'<p class="intro">Sorted by total days with the belt. Click a column to re-sort.</p>',
                columns=[(word[:-1].capitalize(), "", True), ("Reigns", "mono r", True), ("Days", "mono r", True), ("Defenses", "mono r", True), ("Best reign", "mono r", True), ("Last held", "mono r", True)],
                rows=rows, filters=[("active", f"Current and former", [("y", "Active today"), ("n", "Former / defunct")])], order_labels=None,
                empty=f"No {word} match.")


def build_rivalries_table(lg, d, min_meetings=5):
    n = lg["team_name"]
    rv = [p for p in d.get("rivalries") or [] if p["meetings"] >= min_meetings]
    rows = []
    for p in rv:
        x, y = sorted((S.slug(n(p["a"])), S.slug(n(p["b"]))))
        url = f"{b(lg)}/rivalries/{x}-vs-{y}/"
        rows.append({"c": [f'<a href="{url}">{e(n(p["a"]))} vs. {e(n(p["b"]))}</a>', str(p["meetings"]),
                           f'{p["a_wins"]}–{p["b_wins"]}' + (f'–{p["ties"]}' if p["ties"] else ""), str(p["changes"]), p["last"][:4]],
                     "t": (n(p["a"]) + " " + n(p["b"])).lower(), "k": [n(p["a"]), p["meetings"], p["a_wins"] - p["b_wins"], p["changes"], p["last"]],
                     "f": {}})
    paged_table(lg, "rivalries/", title=f"{lg['name']} belt rivalries", subnav_on="rivalries",
                description=f"The rivalries that decided the lineal {lg['name']} championship belt most often, with every belt meeting.",
                heading=f"{lg['name']} belt rivalries", note=f"{len(rv):,} pairs with {min_meetings}+ belt meetings",
                intro=f'<p class="intro">The matchups that decided the belt most often. Want a pair that isn\'t here? <a href="{b(lg)}/compare/">Compare any two teams</a>.</p>',
                columns=[("Matchup", "", True), ("Meetings", "mono r", True), ("W–L", "mono r", True), ("Title changes", "mono r", True), ("Last", "mono r", True)],
                rows=rows, order_labels=None, empty="No rivalries match.")


def build_losers_table(lg, d):
    L = (d.get("models") or {}).get("losers") or {}
    reigns = L.get("all") or []
    if not reigns:
        return
    n = lg["team_name"]
    rows = []
    for i, r in enumerate(reversed(reigns)):
        rows.append({"c": [f'{r[0]:,}', f'<i style="background:{lg["team_colors"](r[1])[0]}"></i>{tlink(lg, r[1])}',
                           S.d_short(r[2], True), S.d_short(r[3], True) if r[3] else "Holding", str(r[4]), f"{r[5]:,}"],
                     "t": n(r[1]).lower(), "k": [r[0], n(r[1]), r[2], r[3] or "9999", r[4], r[5]],
                     "f": {"decade": int(r[2][:4]) // 10 * 10}, "cur": i == 0})
    paged_table(lg, "losers-belt/reigns/", title=f"Every {lg['name']} Losers Belt reign", subnav_on="more",
                description=f"All {len(reigns):,} reigns of the {lg['name']} Losers Belt, searchable and sortable.",
                heading=f"Every Losers Belt reign", note=f"{len(reigns):,} reigns",
                intro=f'<p class="intro">Lose to the holder and it\'s yours. <a href="{b(lg)}/losers-belt/">Back to the Losers Belt →</a></p>',
                columns=[("#", "mono n", True), ("Stuck with it", "", True), ("From", "mono", True), ("To", "mono", True), ("Losses", "mono r", True), ("Days", "mono r", True)],
                rows=rows, filters=[("decade", "Any decade", _decade_opts(int(r[2][:4]) for r in reigns))], empty="No reigns match.")


def build_tables(lg, d):
    build_history_table(lg, d)
    build_all_games(lg, d)
    build_teams_table(lg, d)
    build_rivalries_table(lg, d)
    build_losers_table(lg, d)
    build_more(lg, d)     # last, so it only lists pages that were built


def build_what_if(lg, d):
    wi = (d.get("models") or {}).get("what_if") or []
    if not wi:
        return
    n = lg["team_name"]
    today_holder = d["current"]["team"]
    cards = []
    bg_by_n = {bg["n"]: bg for bg in d["belt_games"]}
    for x in wi:
        bg = bg_by_n.get(x["n"])
        s = bg["season"] if bg else int(x["date"][:4])
        real = f'{e(n(x["flip_loser"], s))} beat {e(n(x["flip_winner"], s))} {_winner_score(bg)}' if bg else ""
        alt_path = x["path"][:max(1, x["alt_reigns"])] if x["rejoin"] else x["path"][:8]
        path = " → ".join(e(lg["short_name"](t)) for t in alt_path)
        if x["rejoin"]:
            days = (date.fromisoformat(x["rejoin"]) - date.fromisoformat(x["date"])).days
            verdict = (("History snaps back fast" if days < 60 else "It takes a while") + f": the belt is back on its real path by {S.d_long(x['rejoin'])}, "
                       f"{S.plural(days, 'day')} later" + (f", after {S.plural(x['alt_reigns'], 'reign')} that never happened." if x["alt_reigns"] else "."))
        else:
            verdict = f"The belt never finds its way back. Today it would belong to <b>{e(n(x['today']))}</b>, not {e(n(today_holder))}."
        cards.append(f"""<div class="wicard">
  <div class="kicker">{S.d_long(x['date'])} · {e(sl(lg, s))}</div>
  <h3 class="disp">What if {e(n(x['flip_winner'], s))} had won?</h3>
  <p class="mono note">Real result: {real}{(' · <a href="' + game_url(lg, bg) + '">the game</a>') if bg else ''}</p>
  <p>{verdict}</p>
  {f'<p class="mono note">The alternate belt: {path}</p>' if path else ''}
</div>""")
    changed = sum(1 for x in wi if not x["rejoin"])
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">What if?</h1><span class="mono note">{len(wi)} famous title changes, replayed the other way</span></div>
  <p class="intro">We took famous {e(lg['name'])} title changes, flipped the result, and replayed every game since through the same rules. Sometimes the belt finds its way home within days. {"Sometimes it never does." if changed else "So far, every alternate belt has found its way home."}</p>
  <div class="wigrid">{"".join(cards)}</div>
</section>"""
    page(lg, f"What if? {lg['name']} belt history replayed", body, "what-if/",
         f"Famous {lg['name']} belt title changes flipped and replayed: would the lineal belt ever find its way back?")


# ============================================================ player data ==
# Box scores for belt games (data/<lg>/box/belt_box.json):
#   {"games": {belt game n: {"gid", "players": [[id, name, side h/a, *stats]]}}}
# with the stat columns listed in BOX_SCHEMA for each league.

BOX_SCHEMA = {
    "nba": {"cols": ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA"],
            "since": {"REB": 1950, "MIN": 1951, "STL": 1973, "BLK": 1973, "3PM": 1979, "3PA": 1979},
            "show": ["MIN", "PTS", "REB", "AST", "STL", "BLK", ("FG", "FGM", "FGA"), ("3P", "3PM", "3PA"), ("FT", "FTM", "FTA")],
            "totals": ["PTS", "REB", "AST", "STL", "BLK", "3PM"], "key": "PTS",
            "leaders": [("PTS", "Points"), ("REB", "Rebounds"), ("AST", "Assists"), ("STL", "Steals"), ("BLK", "Blocks"), ("3PM", "Threes")],
            "source": ('Player box scores: <a href="https://www.kaggle.com/datasets/eoinamoore/historical-nba-data-and-player-box-scores">'
                       'Historical NBA Data and Player Box Scores</a> by Eoin Moore (CC0).')},
    "cbb": {"cols": ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA"], "since": {},
            "show": ["MIN", "PTS", "REB", "AST", "STL", "BLK", ("FG", "FGM", "FGA"), ("3P", "3PM", "3PA"), ("FT", "FTM", "FTA")],
            "totals": ["PTS", "REB", "AST", "STL", "BLK", "3PM"], "key": "PTS",
            "leaders": [("PTS", "Points"), ("REB", "Rebounds"), ("AST", "Assists"), ("STL", "Steals"), ("BLK", "Blocks"), ("3PM", "Threes")],
            "source": 'Player box scores: <a href="https://collegebasketballdata.com">CollegeBasketballData.com</a>.'},
    "nfl": {"cols": ["CMP", "ATT", "PYD", "PTD", "INT", "CAR", "RYD", "RTD", "REC", "TGT", "RECYD", "RECTD", "TKL", "SCK", "DINT", "FGM", "FGA"],
            "since": {}, "derived": {"YDS": ["PYD", "RYD", "RECYD"], "TD": ["PTD", "RTD", "RECTD"]},
            "show": [("C/ATT", "CMP", "ATT"), "PYD", "PTD", "INT", "CAR", "RYD", "RTD", "REC", "RECYD", "RECTD", "TKL", "SCK", "DINT"],
            "totals": ["YDS", "TD", "PYD", "RYD", "RECYD", "SCK", "DINT"], "key": "YDS",
            "leaders": [("PYD", "Passing yards"), ("RYD", "Rushing yards"), ("RECYD", "Receiving yards"), ("TD", "Touchdowns"), ("SCK", "Sacks"), ("DINT", "Interceptions")],
            "source": 'Player stats since 1999: <a href="https://github.com/nflverse/nflverse-data">nflverse</a> (CC-BY 4.0).'},
    "mlb": {"cols": ["AB", "R", "H", "HR", "RBI", "BB", "SO", "IP", "HA", "ER", "K", "BBA"], "since": {},
            "show": ["AB", "R", "H", "HR", "RBI", "BB", "SO", "IP", "HA", "ER", "K"],
            "totals": ["H", "HR", "RBI", "R", "K", "IP"], "key": "H",
            "leaders": [("H", "Hits"), ("HR", "Home runs"), ("RBI", "RBIs"), ("K", "Strikeouts (pitching)"), ("R", "Runs"), ("IP", "Innings pitched")],
            "source": "Box scores: MLB's Stats API (statsapi.mlb.com). HA, ER, K are pitching."},
    "nhl": {"cols": ["G", "A", "PTS", "PM", "PIM", "SOG", "HIT", "SV", "SA"], "since": {},
            "show": ["G", "A", "PTS", ("+/-", "PM", "PM"), "PIM", "SOG", "HIT", "SV", "SA"],
            "totals": ["PTS", "G", "A", "SV", "HIT", "PIM"], "key": "PTS",
            "leaders": [("G", "Goals"), ("A", "Assists"), ("PTS", "Points"), ("SV", "Saves"), ("HIT", "Hits"), ("PIM", "Penalty minutes")],
            "source": 'Box scores: the NHL\'s own game center.'},
}


# Page budget (BH-2): box scores older than this season don't become player or game pages.
# MLB's backfill reaches back to 1901; every season of box scores adds hundreds of pages,
# and GitHub Pages caps a published site at 1 GB. Raise the floor only with the size guard green.
BOX_PAGES_FROM = {"mlb": 1988}


def _box(lg):
    import glob
    out = {}
    floor = BOX_PAGES_FROM.get(lg.get("key"))
    for p in sorted(glob.glob(os.path.join("data", lg.get("key", "_"), "box", "*.json"))):
        name = os.path.basename(p)
        if not (name[:4].isdigit() or name == "belt_box.json"):
            continue
        if floor and name[:4].isdigit() and int(name[:4]) < floor:
            continue
        try:
            with open(p) as f:
                out.update((json.load(f) or {}).get("games") or {})
        except ValueError:
            continue
    return out


def _box_for(lg, d):
    """Box scores keyed by this lineage's belt game numbers. College
    basketball stores the API game id with each box score, so they're matched
    by that id (belt game numbers shift when older games are added)."""
    box = _box(lg)
    if lg.get("key") != "cbb":
        return box
    by_gid = {str(bg.get("game_id")): bg["n"] for bg in d["belt_games"] if bg.get("game_id")}
    return {str(by_gid[str(g.get("gid"))]): g for g in box.values() if str(g.get("gid")) in by_gid}


def _stat_rows(lg, box):
    """Normalize to {n: [(pid, name, side, {stat: value or None})]} with era gaps blanked."""
    sc = BOX_SCHEMA[lg["key"]]
    out = {}
    for n_, g in box.items():
        out[int(n_)] = g["players"]
    return sc, out


MIN_PLAYER_GAMES = 3      # players with fewer belt games are rows in the tables, not pages (BH-2)


def plink(p):
    """A player's name, linked when the player has a page."""
    return f'<a href="{p["url"]}">{e(p["name"])}</a>' if p.get("url") else e(p["name"])


def valid_player(pid, name):
    """Box-score rows without a real player id or name (team-total rows such as nflverse's "Team") never become players (BH-5)."""
    return str(pid) not in ("", "?", "0", "None") and (name or "").strip() not in ("", "?", "Team")


def player_slug(name, pid):
    pid = re.sub(r"[^a-z0-9-]", "", str(pid).lower())
    out = f"{S.slug(name)}-{pid}"
    assert re.fullmatch(r"[a-z0-9-]+", out), out
    return out


def build_players(lg, d):
    k = lg.get("key")
    if k not in BOX_SCHEMA:
        return
    box = _box_for(lg, d)
    if not box:
        return
    sc = BOX_SCHEMA[k]
    cols = sc["cols"]
    ix = {c: i + 3 for i, c in enumerate(cols)}
    n = lg["team_name"]
    by_n = {bg["n"]: bg for bg in d["belt_games"]}
    players = {}
    game_lines = defaultdict(list)   # belt game n -> rows with team code

    def val(row, c, season):
        v = row[ix[c]] if ix[c] < len(row) else None
        if v is None:
            return None
        if sc["since"].get(c) and season < sc["since"][c]:
            return None
        return v

    for n_str, g in box.items():
        bg = by_n.get(int(n_str))
        if not bg:
            continue
        s = bg["season"]
        home = bg["home"]
        away = bg["opponent"] if bg["home"] == bg.get("holder") else bg.get("holder") or bg["opponent"]
        hp, ap = (int(x) for x in bg["score"].split("-"))
        for row in g["players"]:
            pid, name, side = str(row[0]), row[1], row[2]
            if not valid_player(pid, name):
                continue
            team = home if side == "h" else away
            opp = away if side == "h" else home
            stats = {c: val(row, c, s) for c in cols}
            for dk, parts in (sc.get("derived") or {}).items():
                vals = [stats.get(x_) for x_ in parts]
                stats[dk] = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
            if (stats.get("FGA") is not None and stats.get("FGM") is not None and stats["FGA"] < stats["FGM"]):
                stats["FGA"] = None
            won = (hp > ap) if side == "h" else (ap > hp)
            p = players.setdefault(pid, {"name": name, "games": [], "teams": Counter()})
            p["teams"][team] += 1
            kind = ("took" if bg["outcome"] == "changed" and bg["new_holder"] == team else
                    "lost" if bg["outcome"] == "changed" else
                    "kept" if bg.get("holder") == team else "fell")
            p["games"].append((bg, team, opp, won, kind, stats))
            game_lines[bg["n"]].append((pid, name, team, stats))
    if not players:
        return
    # ---- player pages
    rows = []
    teams_all = set()
    for pid, p in players.items():
        gs = sorted(p["games"], key=lambda x: x[0]["n"])
        slug = player_slug(p["name"], pid)
        has_page = len(gs) >= MIN_PLAYER_GAMES
        url = f"{b(lg)}/players/{slug}/" if has_page else None
        p["url"] = url
        if has_page and len(gs) >= SEARCH_MIN_GAMES:
            SEARCH_PLAYERS.append([p["name"], f"{lg['name']} player", url, len(gs)])
        w = sum(1 for x in gs if x[3])
        took = sum(1 for x in gs if x[4] == "took")
        tot = {c: sum((x[5].get(c) or 0) for x in gs) for c in sc["totals"]}
        main_team = p["teams"].most_common(1)[0][0]
        teams_all |= set(p["teams"])
        best = max(gs, key=lambda x: x[5].get(sc["key"]) or 0)
        p.update({"n": len(gs), "w": w, "took": took, "tot": tot, "main": main_team, "best": best})
        head = "".join(f'<th class="mono r">{e(c if isinstance(c, str) else c[0])}</th>' for c in sc["show"])

        def cell(stats, c):
            if isinstance(c, str) or c[1] == c[2]:
                v = stats.get(c if isinstance(c, str) else c[1])
                return "—" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
            m, a = stats.get(c[1]), stats.get(c[2])
            return "—" if m is None or a is None else f"{m}-{a}"

        trs = "".join(
            f'<tr><td class="mono">{S.d_short(bg["date"], True)}</td><td>{e(lg["short_name"](team))} {"vs." if bg["home"] == team else "at"} {e(n(opp, bg["season"]))}'
            f'<small>{"Took the belt" if kind == "took" else "Lost the belt" if kind == "lost" else "Kept the belt" if kind == "kept" else "Challenger, lost"} · {_winner_score(bg)}</small></td>'
            f'<td class="mono">{"W" if won else "L"}</td>' + "".join(f'<td class="mono r">{cell(st, c)}</td>' for c in sc["show"]) + "</tr>"
            for bg, team, opp, won, kind, st in reversed(gs))
        teams_line = ", ".join(e(n(t)) for t, _ in p["teams"].most_common())
        pp, s2 = lg["team_colors"](main_team)
        top, bottom, ink, accent = S.plate(pp, s2)
        per = sc["key"]
        avg = tot.get(per, 0) / len(gs) if gs else 0
        body = f"""{S.subnav(lg, "more")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">{e(lg['name'])} belt games · {teams_line}</div>
    <h1 class="disp holder" style="--fit:{max(len(x) for x in p['name'].split())}">{e(p['name'])}</h1>
    <p class="lede">Played in {S.plural(len(gs), 'belt game')} from {S.d_long(gs[0][0]['date'])} to {S.d_long(gs[-1][0]['date'])}, winning {w}. {f"Helped take the belt {S.plural(took, 'time')}." if took else ""}</p>
  </div>
</section>
<section class="wrap block">
  {numbers([(len(gs), "Belt games"), (f"{w}–{len(gs) - w}", "Record"), (took, "Title-winning games"), (f"{avg:.1f}", f"{per} per belt game")])}
  <p class="intro">Belt-game totals: {", ".join(f"{tot[c]:,} {c}" for c in sc["totals"] if tot.get(c))}.</p>
  <div class="tablewrap"><table class="history box"><thead><tr><th class="mono">Date</th><th class="mono">Game</th><th class="mono">W/L</th>{head}</tr></thead><tbody>{trs}</tbody></table></div>
  <p class="mono note">{sc['source']} Stats a season didn't track show as —.</p>
  <p class="mono more"><a href="{b(lg)}/players/">All players →</a> · <a href="{b(lg)}/leaders/">Belt-game leaders →</a></p>
</section>"""
        if has_page:
            page(lg, f"{p['name']} in {lg['name']} belt games", body, f"players/{slug}/",
                 f"{p['name']}: {S.plural(len(gs), 'lineal ' + lg['name'] + ' belt game')}, {S.plural(w, 'win')}, {S.plural(took, 'title-winning game')}. Every belt-game stat line.",
                 jsonld={"@type": "Person", "name": p["name"], "url": S.SITE_URL + f"{b(lg)}/players/{slug}/",
                         "memberOf": [{"@type": "SportsTeam", "name": n(t)} for t in p["teams"]][:6]})
        rows.append({"c": [f'<i style="background:{pp}"></i>{plink(p)}<small>{e(lg["short_name"](main_team))}</small>',
                           str(len(gs)), f"{w}–{len(gs) - w}", str(took)] + [f"{tot.get(c, 0):,}" for c in sc["totals"][:3]] + [f"{avg:.1f}"],
                     "t": (p["name"] + " " + " ".join(n(t) for t in p["teams"])).lower(),
                     "k": [p["name"].split()[-1] + " " + p["name"], len(gs), w, took] + [tot.get(c, 0) for c in sc["totals"][:3]] + [round(avg, 2)],
                     "f": {"team": main_team}})
    rows.sort(key=lambda r: -r["k"][1])
    paged_table(lg, "players/", title=f"Every player in a {lg['name']} belt game", subnav_on="more",
                description=f"Every player who has appeared in a lineal {lg['name']} belt game, with belt-game records and stats.",
                heading=f"Players in {lg['name']} belt games", note=f"{len(players):,} players",
                intro=f'<p class="intro">Everyone who has played with the belt on the line. Search a name, filter by team, or sort any column. <a href="{b(lg)}/leaders/">Belt-game leaders →</a></p>',
                columns=[("Player", "", True), ("Belt games", "mono r", True), ("W–L", "mono r", True), ("Title wins", "mono r", True)]
                + [(c, "mono r", True) for c in sc["totals"][:3]] + [(f"{sc['key']}/G", "mono r", True)],
                rows=rows, order_labels=None, filters=[("team", "Any team", [(t, n(t)) for t in sorted(teams_all, key=lambda t: n(t))])],
                empty="No players match.")
    # ---- leaders
    plist = list(players.items())

    def lead_table(title, items):
        trs = "".join(f'<tr><td class="mono n">{i}</td><td>{plink(p)}<small>{e(lg["short_name"](p["main"]))}</small></td><td class="mono r">{v}</td></tr>'
                      for i, (p, v) in enumerate(items, 1))
        return f'<div><h2 class="disp sub">{e(title)}</h2><table class="history"><tbody>{trs}</tbody></table></div>'

    def top(f, k_=10):
        return sorted(((p, f(p)) for _, p in plist), key=lambda x: -x[1])[:k_]

    career = [lead_table("Most belt games", [(p, f"{v:,}") for p, v in top(lambda p: p["n"])]),
              lead_table("Most belt-game wins", [(p, f"{v:,}") for p, v in top(lambda p: p["w"])]),
              lead_table("Most title-winning games", [(p, f"{v:,}") for p, v in top(lambda p: p["took"])])]
    career += [lead_table(f"Career {lab.lower()} in belt games", [(p, f"{v:,}") for p, v in top(lambda p, c=c: p["tot"].get(c, 0))])
               for c, lab in sc["leaders"] if c in sc["totals"]]
    singles = []
    for c, lab in sc["leaders"][:4]:
        best = []
        for _, p in plist:
            for bg, team, opp, won, kind, st in p["games"]:
                if st.get(c) is not None:
                    best.append((st[c], p, bg, opp))
        best.sort(key=lambda x: -x[0])
        trs = "".join(f'<tr><td class="mono">{v}</td><td>{plink(p)}<small>vs. {e(n(opp, bg["season"]))} · {S.d_short(bg["date"], True)}</small></td></tr>'
                      for v, p, bg, opp in best[:10])
        singles.append(f'<div><h2 class="disp sub">Most {lab.lower()} in one belt game</h2><table class="history"><tbody>{trs}</tbody></table></div>')
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Belt-game leaders</h1><span class="mono note">{len(players):,} players · {len(box):,} belt games with box scores</span></div>
  <p class="intro">Who shows up when the belt is on the line. Counting only {e(lg['name'])} belt games. <a href="{b(lg)}/players/">Every player →</a></p>
  <div class="leadgrid">{"".join(career)}</div>
  <div class="leadgrid">{"".join(singles)}</div>
  <p class="mono note">{sc['source']}</p>
</section>"""
    page(lg, f"{lg['name']} belt-game leaders", body, "leaders/",
         f"Career and single-game leaders in lineal {lg['name']} belt games: points, rebounds, assists, wins and title-winning games.")
    d["_players"] = players
    d["_game_lines"] = game_lines


def box_html(lg, d, bg):
    """Full box score for a belt game (used on game pages)."""
    lines = (d.get("_game_lines") or {}).get(bg["n"])
    k = lg.get("key")
    if not lines or k not in BOX_SCHEMA:
        return ""
    sc = BOX_SCHEMA[k]
    players = d.get("_players") or {}
    n = lg["team_name"]
    out = []
    for team in [x for x in (bg["opponent"] if bg["home"] != bg["opponent"] else None, bg["home"]) if x] or []:
        pass
    teams = []
    for pid, name, team, st in lines:
        if team not in teams:
            teams.append(team)

    def cell(stats, c):
        if isinstance(c, str) or c[1] == c[2]:
            v = stats.get(c if isinstance(c, str) else c[1])
            return "—" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
        m, a = stats.get(c[1]), stats.get(c[2])
        return "—" if m is None or a is None else f"{m}-{a}"

    head = "".join(f'<th class="mono r">{e(c if isinstance(c, str) else c[0])}</th>' for c in sc["show"])
    for team in teams:
        rows = sorted([x for x in lines if x[2] == team], key=lambda x: -(x[3].get(sc["key"]) or 0))
        trs = "".join(f'<tr><td>{plink(players[pid])}</td>' + "".join(f'<td class="mono r">{cell(st, c)}</td>' for c in sc["show"]) + "</tr>"
                      for pid, name, t, st in rows if pid in players)
        out.append(f'<h3 class="disp sub">{e(n(team, bg["season"]))}</h3><div class="tablewrap"><table class="history box"><thead><tr><th class="mono">Player</th>{head}</tr></thead><tbody>{trs}</tbody></table></div>')
    return f'<section class="pv-sec"><h2 class="kicker">Box score</h2>{"".join(out)}<p class="mono note">{sc["source"]}</p></section>'


# ================================================= map, journey, states, web ==

D3 = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"
TOPO = "https://cdnjs.cloudflare.com/ajax/libs/topojson/3.0.2/topojson.min.js"


def _place(lg, code, season=None):
    fn = lg.get("place")
    if fn:
        return fn(code, season)
    try:
        import places
    except ImportError:
        return None
    return places.place(lg["team_name"](code, season) if season is not None else lg["team_name"](code))


def _geo_reigns(lg, d):
    out = []
    for r in d["reigns"]:
        p = _place(lg, r["team"], r.get("season"))
        if p:
            out.append((r, p))
    return out


def build_states(lg, d):
    gr = _geo_reigns(lg, d)
    if len(gr) < len(d["reigns"]) * 0.8:
        return
    STATE_NAMES = lg.get("state_names")
    if STATE_NAMES is None:
        try:
            from places import STATE_NAMES
        except ImportError:
            STATE_NAMES = {}
    days, reigns, teams = Counter(), Counter(), defaultdict(set)
    for r, (city, st, la, lo) in gr:
        days[st] += r["days"]
        reigns[st] += 1
        teams[st].add(r["team"])
    tot = sum(days.values()) or 1
    rows = "".join(
        f'<tr><td>{e(STATE_NAMES.get(s_, s_))}</td><td class="bar"><span style="width:{v / days.most_common(1)[0][1] * 100:.1f}%;background:var(--brass)"></span></td>'
        f'<td class="mono r">{v:,}</td><td class="mono r">{pct(v / tot)}</td><td class="mono r">{reigns[s_]:,}</td>'
        f'<td><small>{", ".join(e(lg["short_name"](t)) for t in sorted(teams[s_], key=lambda t: lg["short_name"](t)))}</small></td></tr>'
        for s_, v in days.most_common())
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The {e(lg['name'])} belt by state</h1><span class="mono note">{len(days)} states and provinces have held it</span></div>
  <p class="intro">Days with the belt, by where the holder played. <a href="{b(lg)}/map/">See it on the map →</a></p>
  <div class="tablewrap"><table class="history odds"><thead><tr><th class="mono">State / province</th><th><span class="sr">Share</span></th><th class="mono r">Days</th><th class="mono r">Share</th><th class="mono r">Reigns</th><th class="mono">Teams</th></tr></thead><tbody>{rows}</tbody></table></div>
</section>"""
    page(lg, f"The {lg['name']} belt by state", body, "states/", f"Which states and provinces have held the lineal {lg['name']} belt, and for how long.")


def build_map(lg, d):
    gr = _geo_reigns(lg, d)
    if len(gr) < len(d["reigns"]) * 0.8:
        return
    cities, cidx = [], {}
    agg = defaultdict(lambda: [0, 0, set()])
    reigns = []
    teams, tidx = [], {}
    for r, (city, st, la, lo) in gr:
        k = f"{city}, {st}"
        if k not in cidx:
            cidx[k] = len(cities)
            cities.append([k, lo, la])
        era = lg["team_name"](r["team"], r.get("season"))
        if era not in tidx:
            tidx[era] = len(teams)
            teams.append([era, lg["team_colors"](r["team"])[0]])
        a = agg[k]
        a[0] += r["days"]
        a[1] += 1
        a[2].add(lg["short_name"](r["team"]))
        reigns.append([r["start_date"], cidx[k], tidx[era], r.get("defenses", 0)])
    for c in cities:
        a = agg[c[0]]
        c += [a[0], a[1], ", ".join(sorted(a[2]))]
    S.write(out(lg, "map/data.json"), json.dumps({"cities": cities, "teams": teams, "reigns": reigns}, separators=(",", ":")))
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The {e(lg['name'])} belt map</h1><span class="mono note">{len(cities)} cities · circle size = days held</span></div>
  <div class="mapbar"><button class="mono" id="play">▶ Play the journey</button><input type="range" id="slider" min="0" value="0" aria-label="Reign"><span class="mono note" id="mlabel">Every city that has held the belt</span></div>
  <div id="map" class="mapbox"></div>
  <p class="mono note"><a href="{b(lg)}/states/">By state →</a> · <a href="{b(lg)}/web/">Web of the belt →</a></p>
</section>
<script src="{D3}"></script><script src="{TOPO}"></script>
<script>
(function(){{
var box=document.getElementById('map'),W=box.clientWidth,H=Math.round(W*0.62),svg=d3.select(box).append('svg').attr('viewBox','0 0 '+W+' '+H);
var tip=d3.select(box).append('div').attr('class','maptip');
Promise.all([fetch('{b(lg)}/map/data.json').then(function(r){{return r.json();}}),
 fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json').then(function(r){{return r.json();}}),
 fetch('https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json').then(function(r){{return r.json();}})]).then(function(a){{
 var D=a[0],world=a[1],us=a[2];
 var far=function(c){{return c[1]<-140;}};
 var pts={{type:'MultiPoint',coordinates:D.cities.filter(function(c){{return !far(c);}}).map(function(c){{return [c[1],c[2]];}})}};
 var P0=d3.geoConicConformal().parallels([30,50]).rotate([96,0]).fitExtent([[30,30],[W-30,H-30]],pts),path=d3.geoPath(P0);
 var proj=function(ll){{return ll[0]<-140?[36+(ll[0]+161)*9,H-34-(ll[1]-18.9)*9]:P0(ll);}};
 if(D.cities.some(far))svg.append('text').attr('x',30).attr('y',H-8).attr('class','mapnote').text('Hawaii (not to scale)');
 var countries=topojson.feature(world,world.objects.countries).features.filter(function(f){{return ['840','124','484'].indexOf(String(f.id))>=0;}});
 svg.append('g').selectAll('path').data(countries).join('path').attr('d',path).attr('class','land');
 svg.append('path').datum(topojson.mesh(us,us.objects.states,function(a,b){{return a!==b;}})).attr('d',path).attr('class','borders');
 var mx=d3.max(D.cities,function(c){{return c[3];}}),r=d3.scaleSqrt().domain([0,mx]).range([2,Math.max(18,W/40)]);
 var g=svg.append('g');
 var dots=g.selectAll('circle').data(D.cities).join('circle').attr('cx',function(c){{return proj([c[1],c[2]])[0];}}).attr('cy',function(c){{return proj([c[1],c[2]])[1];}})
  .attr('r',function(c){{return r(c[3]);}}).attr('class','city')
  .on('mousemove',function(ev,c){{tip.style('display','block').style('left',(ev.offsetX+12)+'px').style('top',(ev.offsetY+12)+'px').html('<b>'+c[0]+'</b><br>'+c[3].toLocaleString()+' days · '+c[4]+' reigns<br><small>'+c[5]+'</small>');}})
  .on('mouseleave',function(){{tip.style('display','none');}});
 var sl=document.getElementById('slider'),lab=document.getElementById('mlabel'),btn=document.getElementById('play'),timer=null;
 sl.max=D.reigns.length-1;
 var belt=g.append('circle').attr('r',9).attr('class','beltdot').style('display','none'),trail=g.append('path').attr('class','trail');
 function show(i){{var rg=D.reigns[i],c=D.cities[rg[1]],p=proj([c[1],c[2]]),t=D.teams[rg[2]];
  belt.style('display',null).attr('fill',t[1]).transition().duration(timer?120:0).attr('cx',p[0]).attr('cy',p[1]);
  var tr=D.reigns.slice(Math.max(0,i-12),i+1).map(function(x){{var cc=D.cities[x[1]];return proj([cc[1],cc[2]]);}});
  trail.attr('d',d3.line().curve(d3.curveCatmullRom)(tr));
  lab.textContent=rg[0].slice(0,4)+' · '+t[0]+' ('+c[0]+')';}}
 sl.oninput=function(){{show(+sl.value);}};
 btn.onclick=function(){{if(timer){{clearInterval(timer);timer=null;btn.textContent='▶ Play the journey';return;}}
  if(+sl.value>=D.reigns.length-1)sl.value=0;btn.textContent='❚❚ Pause';var step=Math.max(1,Math.round(D.reigns.length/900));
  timer=setInterval(function(){{var v=+sl.value+step;if(v>=D.reigns.length){{v=D.reigns.length-1;clearInterval(timer);timer=null;btn.textContent='▶ Play again';}}sl.value=v;show(v);}},60);}};
 }});
}})();
</script>"""
    page(lg, f"The {lg['name']} belt map and journey", body, "map/",
         f"Every city that has held the lineal {lg['name']} belt, and an animated journey of the belt from city to city since {lg['first_season']}.")


def build_web(lg, d, max_nodes=60):
    ch = [bg for bg in d["belt_games"] if bg["outcome"] == "changed" and bg.get("holder")]
    days = Counter()
    for r in d["reigns"]:
        days[r["team"]] += r["days"]
    keep = {t for t, _ in days.most_common(max_nodes)}
    pairs = Counter()
    for bg in ch:
        a, bb = bg["holder"], bg["new_holder"]
        if a in keep and bb in keep:
            pairs[(a, bb)] += 1
    nodes = [{"id": t, "n": lg["team_name"](t), "s": lg["short_name"](t), "c": lg["team_colors"](t)[0], "d": days[t], "u": team_href(lg, t)} for t in keep]
    links = [{"source": a, "target": bb, "w": w} for (a, bb), w in pairs.items()]
    S.write(out(lg, "web/data.json"), json.dumps({"nodes": nodes, "links": links}, separators=(",", ":")))
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">Web of the belt</h1><span class="mono note">{len(nodes)} teams · {sum(pairs.values()):,} handoffs</span></div>
  <p class="intro">Every line is a handoff: one team took the belt straight from another. Thicker lines, more handoffs. Bigger circles held it longer. Drag a team; tap one to see its belt page.</p>
  <div id="web" class="mapbox"></div>
</section>
<script src="{D3}"></script>
<script>
(function(){{
var box=document.getElementById('web'),W=box.clientWidth,H=Math.max(520,Math.round(W*0.7));
var svg=d3.select(box).append('svg').attr('viewBox','0 0 '+W+' '+H),tip=d3.select(box).append('div').attr('class','maptip');
fetch('{b(lg)}/web/data.json').then(function(r){{return r.json();}}).then(function(D){{
 var mx=d3.max(D.nodes,function(n){{return n.d;}}),r=d3.scaleSqrt().domain([0,mx]).range([4,Math.max(22,W/32)]);
 var lw=d3.scaleSqrt().domain([1,d3.max(D.links,function(l){{return l.w;}})||1]).range([.6,7]);
 var sim=d3.forceSimulation(D.nodes).force('link',d3.forceLink(D.links).id(function(n){{return n.id;}}).distance(90).strength(function(l){{return Math.min(1,l.w/20);}}))
  .force('charge',d3.forceManyBody().strength(-260)).force('x',d3.forceX(W/2).strength(.07)).force('y',d3.forceY(H/2).strength(.09)).force('collide',d3.forceCollide(function(n){{return r(n.d)+3;}}));
 var link=svg.append('g').attr('class','wlinks').selectAll('line').data(D.links).join('line').attr('stroke-width',function(l){{return lw(l.w);}});
 var node=svg.append('g').selectAll('g').data(D.nodes).join('g').attr('class','wnode').call(d3.drag().on('start',function(ev,n){{if(!ev.active)sim.alphaTarget(.3).restart();n.fx=n.x;n.fy=n.y;}}).on('drag',function(ev,n){{n.fx=ev.x;n.fy=ev.y;}}).on('end',function(ev,n){{if(!ev.active)sim.alphaTarget(0);n.fx=null;n.fy=null;}}));
 node.append('circle').attr('r',function(n){{return r(n.d);}}).attr('fill',function(n){{return n.c;}});
 node.append('text').text(function(n){{return n.s;}}).attr('dy',function(n){{return r(n.d)+12;}});
 node.on('click',function(ev,n){{if(n.u)location.href=n.u;}}).on('mousemove',function(ev,n){{
  var out=D.links.filter(function(l){{return l.source.id===n.id||l.target.id===n.id;}}).sort(function(a,b){{return b.w-a.w;}}).slice(0,4)
   .map(function(l){{return l.source.id===n.id?('lost it to '+l.target.s+' ×'+l.w):('took it from '+l.source.s+' ×'+l.w);}});
  tip.style('display','block').style('left',(ev.offsetX+12)+'px').style('top',(ev.offsetY+12)+'px').html('<b>'+n.n+'</b><br>'+n.d.toLocaleString()+' days<br><small>'+out.join('<br>')+'</small>');}})
  .on('mouseleave',function(){{tip.style('display','none');}});
 sim.on('tick',function(){{link.attr('x1',function(l){{return l.source.x;}}).attr('y1',function(l){{return l.source.y;}}).attr('x2',function(l){{return l.target.x;}}).attr('y2',function(l){{return l.target.y;}});
  node.attr('transform',function(n){{n.x=Math.max(20,Math.min(W-20,n.x));n.y=Math.max(20,Math.min(H-20,n.y));return 'translate('+n.x+','+n.y+')';}});}});
}});
}})();
</script>"""
    page(lg, f"Web of the {lg['name']} belt", body, "web/", f"Every handoff of the lineal {lg['name']} belt as a network: who took it from whom, and how often.")


def build_geo(lg, d):
    build_states(lg, d)
    build_map(lg, d)
    build_web(lg, d)


# ============================================================= group belts ==

GROUP_HUB = {"mlb": ("leagues/", "The AL and NL belts", "league"), "nfl": ("conferences/", "The AFC and NFC belts", "conference"),
             "cbb": ("conferences/", "Conference belts", "conference"), "women": ("conferences/", "Conference belts", "conference")}


def build_groups(lg, d):
    groups = (d.get("models") or {}).get("groups") or {}
    k = lg.get("key", "cbb")
    if not groups or k not in GROUP_HUB:
        return
    hub, hub_title, word = GROUP_HUB[k]
    n, sn = lg["team_name"], lg["short_name"]
    cards = []
    for gk, g in sorted(groups.items(), key=lambda kv: kv[1]["label"]):
        slug = S.slug(gk)
        cur = g["current"]
        t = cur["team"]
        p, s2 = lg["team_colors"](t)
        top, bottom, ink, accent = S.plate(p, s2)
        label = g["label"]
        belt_name = f"{label} belt"
        cards.append(f'<a class="morecard gcard" href="{b(lg)}/{hub}{slug}/" style="border-left:6px solid {p}"><span class="mono">{e(belt_name)}</span>'
                     f'<b class="disp">{e(n(t))}</b><span>since {S.d_short(cur["start"], True)} · {S.plural(cur["defenses"], "defense")}</span></a>')
        nxt = g.get("next")
        nxt_html = ""
        if nxt:
            opp = nxt[2] if nxt[1] == t else nxt[1]
            nxt_html = f'<p class="intro">Next {e(belt_name)} game: {S.weekday(nxt[0])}, {S.d_long(nxt[0])}, {"vs." if nxt[1] == t else "at"} {tlink(lg, opp)}.</p>'
        won = ""
        if cur.get("won_from"):
            won = f"Took it from {e(n(cur['won_from']))}, {S.won_score_text({'won_score': cur['won_score']})}, on {S.d_long(cur['start'])}."
        tab = lambda rows: "".join(f'<tr><td><i style="background:{lg["team_colors"](x)[0]}"></i>{tlink(lg, x)}</td><td class="mono r">{v:,}</td></tr>' for x, v in rows)
        longest = "".join(f'<tr><td>{tlink(lg, r[0])}</td><td class="mono">{S.d_short(r[1], True)} – {S.d_short(r[2], True) if r[2] else "now"}</td><td class="mono r">{r[3]}</td></tr>' for r in g["longest"])
        recent = "".join(f'<tr><td class="mono">{S.d_short(x[0], True)}</td><td>{tlink(lg, x[2])} beat {e(n(x[1]))}</td></tr>' for x in g["recent"])
        body = f"""{S.subnav(lg, "more")}
<section class="plate slim" style="--top:{top};--bottom:{bottom};--ink:{ink};--accent:{accent}">
  <div class="wrap-in">
    <div class="kicker dot">The {e(belt_name)} · current holder</div>
    <h1 class="disp holder" style="--fit:{max(len(w) for w in n(t).split())}">{e(n(t))}</h1>
    <p class="lede">{won} Only {e(label)} games count: the {word} belt passes to whoever beats the holder in a game between two {e(label)} teams.</p>
  </div>
</section>
<section class="wrap block">
  {numbers([(cur['defenses'], "Defenses this reign"), (f"{cur['days']:,}", "Days held"), (f"{g['reigns_n']:,}", "Reigns since " + str(g['first']['season'])), (f"{g['games']:,}", f"{word.capitalize()} belt games")])}
  {nxt_html}
  <div class="two">
    <div><h2 class="disp sub">Most days with it</h2><table class="history"><tbody>{tab(g['most_days'])}</tbody></table></div>
    <div><h2 class="disp sub">Most reigns</h2><table class="history"><tbody>{tab(g['most_reigns'])}</tbody></table></div>
  </div>
  <div class="two">
    <div><h2 class="disp sub">Longest reigns</h2><table class="history"><tbody>{longest}</tbody></table></div>
    <div><h2 class="disp sub">Latest title changes</h2><table class="history"><tbody>{recent}</tbody></table></div>
  </div>
  <p class="mono more"><a href="{b(lg)}/{hub}{slug}/reigns/">Every {e(belt_name)} reign →</a> · <a href="{b(lg)}/{hub}">All {word} belts →</a></p>
</section>"""
        page(lg, f"The {belt_name}: {n(t)} {verb(lg, 'hold', 'holds')} it", body, f"{hub}{slug}/",
             f"The lineal {belt_name}, counting only {label} games: {n(t)} {verb(lg, 'hold', 'holds')} it. Records, longest reigns and every title change since {g['first']['season']}.")
        rows = [{"c": [f'{r[0]:,}', f'<i style="background:{lg["team_colors"](r[1])[0]}"></i>{tlink(lg, r[1])}', S.d_short(r[2], True),
                       S.d_short(r[3], True) if r[3] else "Holding", str(r[4]), f"{r[5]:,}"],
                 "t": n(r[1]).lower(), "k": [r[0], n(r[1]), r[2], r[3] or "9999", r[4], r[5]], "f": {"decade": int(r[2][:4]) // 10 * 10},
                 "cur": i == 0} for i, r in enumerate(reversed(g["reigns"]))]
        paged_table(lg, f"{hub}{slug}/reigns/", title=f"Every {belt_name} reign", subnav_on="more",
                    description=f"All {g['reigns_n']:,} reigns of the lineal {belt_name}, searchable and sortable.",
                    heading=f"Every {belt_name} reign", note=f"{g['reigns_n']:,} reigns since {g['first']['season']}",
                    intro=f'<p class="intro"><a href="{b(lg)}/{hub}{slug}/">Back to the {e(belt_name)} →</a></p>',
                    columns=[("#", "mono n", True), ("Holder", "", True), ("Won", "mono", True), ("Lost", "mono", True), ("Def.", "mono r", True), ("Days", "mono r", True)],
                    rows=rows, filters=[("decade", "Any decade", _decade_opts(int(r[2][:4]) for r in g["reigns"]))], empty="No reigns match.")
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">{e(hub_title)}</h1><span class="mono note">{len(groups)} belts</span></div>
  <p class="intro">Same rules as the {e(lg['name'])} belt, but only games inside the {word} count. Beat the holder in a {word} game and it's yours.</p>
  <div class="moregrid">{"".join(cards)}</div>
</section>"""
    page(lg, f"{hub_title}: {lg['name']}", body, hub, f"{hub_title}: lineal belts that count only games inside each {word}, with current holders and records.")


def build_polls(lg, d):
    """The belt against the AP poll (college leagues with poll data)."""
    m = (d.get("models") or {}).get("polls")
    if not m or not m.get("polls"):
        return
    n, sl = lg["team_name"], lg["season_label"]
    cur = m["current"]
    lead = ""
    if cur.get("team"):
        rk = f"No. {cur['rank']}" if cur.get("rank") else "unranked"
        lead = (f'<p class="intro">{tlink(lg, cur["team"])} {"is" if cur.get("rank") else "was"} <b>{rk}</b> in the latest AP poll '
                f'({S.d_long(cur["date"])})' + (f'; No. 1 was {tlink(lg, cur["no1"])}.' if cur.get("no1") and cur["no1"] != cur["team"] else ".") + "</p>")
    seas = m["seasons"]
    rows = []
    for x in reversed(seas):
        yes = x["no1_held"]
        rows.append({"c": [sl(x["season"]), str(x["polls"]),
                           f'{x["ranked"]} <small>({pct(x["ranked"] / x["polls"])})</small>', str(x["top1"]),
                           (f'{tlink(lg, x["best_team"])} <small class="mono">No. {x["best"]}</small>' if x["best_team"] else "—"),
                           (tlink(lg, x["final_no1"]) if x["final_no1"] else "—"),
                           ("Yes" if yes else "No") if yes is not None else "—"],
                     "t": " ".join(n(t).lower() for t in x["holders"] + [x["final_no1"]] if t),
                     "k": [x["season"], x["polls"], x["ranked"] / x["polls"], x["top1"], x["best"] or 99, n(x["final_no1"]) if x["final_no1"] else "", 1 if yes else 0],
                     "f": {"decade": x["season"] // 10 * 10, "no1": "y" if yes else "n"}})
    unr = "".join(f'<tr><td><i style="background:{lg["team_colors"](t)[0]}"></i>{tlink(lg, t)}</td><td class="mono">{S.d_short(a, True)} – {S.d_short(z, True)}</td>'
                  f'<td class="mono r">{k}</td></tr>' for t, a, z, k in m["unranked"][:10])
    est = ""
    if m.get("estimated"):
        a, z = m["estimated"][0], m["estimated"][-1]
        est = (f'<p class="mono note">Poll dates for {sl(a)} through {sl(z)} are estimated from week numbers '
               f'(the source data has no dates for those seasons), so a holder can be off by a week around a title change.</p>')
    intro = f"""{lead}
  {numbers([(pct(m['ranked'] / m['polls']), "Of AP polls with a ranked holder"), (pct(m['top1'] / m['polls']), "Holder was No. 1"),
            (pct(m['top5'] / m['polls']), "Holder in the top 5"), (f"{m['polls']:,}", "AP polls since " + sl(seas[0]['season']))])}
  <p class="intro">The poll is voters' opinion; the belt is who actually beat whom. Here's how often they agree: first the longest stretches an unranked team held the belt, then every season.</p>{est}"""
    extra = f"""<h2 class="disp sub">Unranked, but holding the belt</h2>
  <p class="intro">The longest runs of AP polls in which the belt holder wasn't ranked at all.</p>
  <table class="history"><thead><tr><th class="mono">Holder</th><th class="mono">Stretch</th><th class="mono r">Polls</th></tr></thead><tbody>{unr}</tbody></table>"""
    paged_table(lg, "ap-poll/", title=f"The {lg['name']} belt vs. the AP poll", subnav_on="more",
                description=f"How often the lineal {lg['name']} belt holder was ranked, or No. 1, in the AP poll, season by season since {sl(seas[0]['season'])}.",
                heading="The belt vs. the AP poll", note=f"{len(seas)} seasons · {m['polls']:,} polls", intro=intro,
                columns=[("Season", "mono", True), ("Polls", "mono r", True), ("Holder ranked", "mono r", True), ("Holder No. 1", "mono r", True),
                         ("Best-ranked holder", "", True), ("Final AP No. 1", "", True), ("No. 1 held it?", "mono", True)],
                rows=rows, filters=[("decade", "Any decade", _decade_opts(x["season"] for x in seas)),
                                    ("no1", "Final No. 1: any", [("y", "Held the belt that season"), ("n", "Never held it that season")])],
                extra=extra, empty="No seasons match.")


def build_relocations(lg, d):
    """Franchises that moved, and how the belt treated them in each city."""
    try:
        import places  # noqa: F401
    except ImportError:
        return
    n = lg["team_name"]
    by = defaultdict(lambda: defaultdict(lambda: {"days": 0, "reigns": 0, "names": Counter(), "first": None, "last": None}))
    for r in d["reigns"]:
        p = _place(lg, r["team"], r.get("season"))
        if not p:
            continue
        c = by[r["team"]][f"{p[0]}, {p[1]}"]
        c["days"] += r["days"]
        c["reigns"] += 1
        c["names"][n(r["team"], r.get("season"))] += 1
        c["first"] = c["first"] or r["start_date"]
        c["last"] = r.get("end_date") or d["generated"]
    movers = {t: cs for t, cs in by.items() if len(cs) > 1}
    if not movers:
        return
    blocks = []
    for t, cs in sorted(movers.items(), key=lambda kv: -sum(c["days"] for c in kv[1].values())):
        tot = sum(c["days"] for c in cs.values()) or 1
        rows = "".join(f'<tr><td>{e(city)}<small>{e(", ".join(nm for nm, _ in c["names"].most_common()))}</small></td>'
                       f'<td class="mono">{c["first"][:4]}–{c["last"][:4]}</td><td class="mono r">{c["reigns"]:,}</td><td class="mono r">{c["days"]:,}</td>'
                       f'<td class="bar"><span style="width:{c["days"] / tot * 100:.0f}%;background:{lg["team_colors"](t)[0]}"></span></td></tr>'
                       for city, c in sorted(cs.items(), key=lambda kv: kv[1]["first"]))
        best = max(cs.items(), key=lambda kv: kv[1]["days"])[0]
        blocks.append(f'<h2 class="disp sub">{tlink(lg, t)}</h2><p class="mono note">Held it longest in {e(best)}</p>'
                      f'<div class="tablewrap"><table class="history odds"><thead><tr><th class="mono">City</th><th class="mono">With the belt</th><th class="mono r">Reigns</th><th class="mono r">Days</th><th><span class="sr">Share</span></th></tr></thead><tbody>{rows}</tbody></table></div>')
    body = f"""{S.subnav(lg, "more")}
<section class="wrap block">
  <div class="head"><h1 class="disp">The belt on the move</h1><span class="mono note">{len(movers)} {unit(lg)} that changed cities</span></div>
  <p class="intro">The belt follows the franchise, not the city. Here's every {e(lg['name'])} {unit(lg)[:-1]} that held it in more than one home, and where it did better.</p>
  {"".join(blocks)}
</section>"""
    page(lg, f"The {lg['name']} belt on the move: relocated franchises", body, "relocations/",
         f"Every {lg['name']} franchise that held the lineal belt in more than one city, and how each home compared.")
