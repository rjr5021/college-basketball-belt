#!/usr/bin/env python3
"""Static audit of a built GitHub-Pages-style site directory.

Usage: audit_site.py <site_dir> <canonical_host> <out_prefix>
"""
import sys, os, re, json, gzip, collections, urllib.parse, html
from concurrent.futures import ProcessPoolExecutor
from lxml import html as LH, etree

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
SITE, HOST, OUT = _args[0], _args[1], _args[2]
SITE = os.path.abspath(SITE)

LEFTOVER_PATTERNS = [
    (r">\s*None\s*<", "literal None"),
    (r"\bNone\b(?=[,.;:)]|\s+(?:since|held|days|defenses|games|reigns))", "None in text"),
    (r">\s*nan\s*<", "literal nan"),
    (r"\bNaN\b", "NaN"),
    (r"\bundefined\b", "undefined"),
    (r"\[object Object\]", "[object Object]"),
    (r"__ROOT__", "__ROOT__ marker"),
    (r"\{\{[^}]*\}\}", "{{ template }}"),
    (r"\{[a-z_]+\}", "{python_format}"),
    (r"%\([a-z_]+\)s", "%(fmt)s"),
    (r"&amp;amp;", "double-escaped &amp;"),
    (r"&lt;[a-z]+&gt;", "escaped HTML tag in text"),
    (r"\bTODO\b|\bFIXME\b|\bXXX\b", "TODO/FIXME"),
    (r"Lorem ipsum", "lorem ipsum"),
    (r"\b0 days? held\b", "0 days held"),
    (r"\(\s*\)", "empty parens"),
    (r"\s,\s", "space before comma"),
    (r"\bthe the\b|\ba a\b|\bof of\b|\bin in\b", "doubled word"),
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", "raw ISO datetime in text"),
    (r"(?<![\d-])\b1 (?:defenses|games|reigns|days|wins|losses|seasons|titles)\b", "1 plural"),
    (r"\b[A-Z][a-z]*[a-rt-z]' (?:\d|belt|reign)", "bare apostrophe possessive"),   # "Michigan' belt" (a dropped s); "Hurricanes' reign" is correct English
    (r"\b\d+ belt games?\b.{0,3}\b0 wins, 0 losses\b", "0-0 line"),
]
LEFTOVER_RE = [(re.compile(p), label) for p, label in LEFTOVER_PATTERNS]

def rel(path):
    return "/" + os.path.relpath(path, SITE).replace(os.sep, "/")

def url_of(path):
    r = rel(path)
    if r.endswith("/index.html"):
        r = r[:-len("index.html")]
    return r

def resolve_internal(href, from_path):
    p = urllib.parse.urlsplit(href)
    frag = p.fragment
    path = p.path
    if not path:
        return from_path, url_of(from_path), frag
    if path.startswith("/"):
        abs_path = path
    else:
        base = os.path.dirname(rel(from_path))
        abs_path = urllib.parse.urljoin(base + "/", path)
    abs_path = urllib.parse.unquote(abs_path)
    abs_path = os.path.normpath(abs_path).replace(os.sep, "/")
    if not abs_path.startswith("/"):
        abs_path = "/" + abs_path
    if path.endswith("/") and not abs_path.endswith("/"):
        abs_path += "/"
    cands = []
    if abs_path.endswith("/"):
        cands.append(abs_path + "index.html")
    else:
        cands.append(abs_path)
        cands.append(abs_path + ".html")
        cands.append(abs_path + "/index.html")
    for c in cands:
        fp = os.path.join(SITE, c.lstrip("/"))
        if os.path.isfile(fp):
            return fp, abs_path, frag
    return None, abs_path, frag

def analyze(path):
    rec = {"file": rel(path), "url": url_of(path), "size": os.path.getsize(path)}
    try:
        raw = open(path, "rb").read()
    except Exception as e:
        rec["error"] = f"read: {e}"
        return rec
    text = raw.decode("utf-8", "replace")
    rec["doctype"] = text.lstrip()[:15].lower().startswith("<!doctype")
    try:
        doc = LH.fromstring(raw)
    except Exception as e:
        rec["error"] = f"parse: {e}"
        return rec
    htmltag = doc if doc.tag == "html" else doc.getroottree().getroot()
    rec["lang"] = htmltag.get("lang")
    t = doc.find(".//title")
    rec["title"] = (t.text or "").strip() if t is not None else None
    def meta(name, attr="name"):
        for m in doc.iter("meta"):
            if (m.get(attr) or "").lower() == name:
                return m.get("content")
        return None
    rec["description"] = meta("description")
    rec["viewport"] = meta("viewport")
    rec["robots"] = meta("robots")
    rec["og_title"] = meta("og:title", "property")
    rec["og_desc"] = meta("og:description", "property")
    rec["og_image"] = meta("og:image", "property")
    rec["og_url"] = meta("og:url", "property")
    rec["twitter_card"] = meta("twitter:card")
    can = [l.get("href") for l in doc.iter("link") if (l.get("rel") or "").lower() == "canonical"]
    rec["canonical"] = can[0] if can else None
    rec["canonical_count"] = len(can)
    rec["h1"] = [(h.text_content() or "").strip()[:80] for h in doc.iter("h1")]
    imgs = list(doc.iter("img"))
    rec["img_count"] = len(imgs)
    rec["img_noalt"] = sum(1 for i in imgs if i.get("alt") is None)
    rec["img_external"] = sorted({urllib.parse.urlsplit(i.get("src") or "").netloc for i in imgs if (i.get("src") or "").startswith("http")})
    ld_ok, ld_bad, ld_types = 0, 0, []
    for s in doc.iter("script"):
        if (s.get("type") or "").lower() == "application/ld+json":
            try:
                d = json.loads(s.text or "")
                ld_ok += 1
                if isinstance(d, dict):
                    if "@graph" in d:
                        ld_types += [x.get("@type") for x in d["@graph"] if isinstance(x, dict)]
                    else:
                        ld_types.append(d.get("@type"))
                elif isinstance(d, list):
                    ld_types += [x.get("@type") for x in d if isinstance(x, dict)]
            except Exception:
                ld_bad += 1
    rec["jsonld_ok"], rec["jsonld_bad"], rec["jsonld_types"] = ld_ok, ld_bad, ld_types
    ids = collections.Counter()
    for el in doc.iter():
        i = el.get("id")
        if i:
            ids[i] += 1
        n = el.get("name")
        if n and el.tag == "a":
            ids[n] += 1
    rec["ids"] = sorted(ids)
    rec["dup_ids"] = sorted(k for k, v in ids.items() if v > 1)[:20]
    body = doc.find(".//body")
    # the text checks look at what a reader sees: inline scripts and styles are dropped from a copy first
    # (otherwise "r.json()" in a script reads as empty parens, and the word counts include JavaScript)
    import copy as _copy
    tbody = _copy.deepcopy(body if body is not None else doc)
    for el in list(tbody.iter("script", "style", "noscript")):
        el.drop_tree()
    btxt = tbody.text_content() or ""
    btxt = re.sub(r"\s+", " ", btxt)
    rec["words"] = len(btxt.split())
    found = []
    for rx, label in LEFTOVER_RE:
        m = rx.search(btxt)
        if m:
            s = max(0, m.start() - 40); e = min(len(btxt), m.end() + 40)
            found.append((label, btxt[s:e]))
    for marker in ("__ROOT__", "{{", "[object Object]"):
        if marker in text and not any(f[0].startswith(marker[:4]) for f in found):
            i = text.find(marker); found.append((marker, text[max(0, i-60):i+60].replace("\n", " ")))
    rec["leftovers"] = found[:8]
    internal, external, mailto, broken, badfrag, cross = [], [], 0, [], [], []
    for a in doc.iter("a"):
        href = a.get("href")
        if href is None:
            continue
        href = href.strip()
        if href.startswith(("mailto:", "tel:")):
            mailto += 1; continue
        if href.startswith(("javascript:", "data:")):
            continue
        p = urllib.parse.urlsplit(href)
        if p.scheme in ("http", "https"):
            host = p.netloc.lower()
            if host in (HOST, "www." + HOST):
                target, norm, frag = resolve_internal(p.path + ("#" + p.fragment if p.fragment else ""), path)
                internal.append(norm)
                if target is None:
                    broken.append((href, (a.text_content() or "").strip()[:40]))
            else:
                external.append(href)
                if host.endswith(("collegefootballbelt.com", "collegebasketballbelt.com", "beltholders.com")):
                    cross.append(href)
            continue
        if href.startswith("//"):
            external.append("https:" + href); continue
        target, norm, frag = resolve_internal(href, path)
        internal.append(norm)
        if target is None:
            broken.append((href, (a.text_content() or "").strip()[:40]))
        elif frag:
            badfrag.append((href, target))
    rec["internal_links"] = sorted(set(internal))
    rec["external_links"] = sorted(set(external))
    rec["cross_links"] = sorted(set(cross))
    rec["mailto"] = mailto
    rec["broken"] = broken[:50]
    rec["frag_links"] = [(h, rel(t)) for h, t in badfrag][:200]
    assets_missing, assets_ext = [], set()
    def chk(u, kind):
        if not u:
            return
        u = u.strip()
        if u.startswith(("data:", "blob:")):
            return
        p = urllib.parse.urlsplit(u)
        if p.scheme in ("http", "https") or u.startswith("//"):
            assets_ext.add(p.netloc or u[2:].split("/")[0]); return
        target, norm, _ = resolve_internal(u, path)
        if target is None:
            assets_missing.append((kind, u))
    for s in doc.iter("script"):
        chk(s.get("src"), "script")
    for l in doc.iter("link"):
        r = (l.get("rel") or "").lower()
        if any(k in r for k in ("stylesheet", "icon", "manifest", "preload", "alternate", "apple-touch-icon")):
            chk(l.get("href"), "link:" + r)
    for i in imgs:
        chk(i.get("src"), "img")
    for s in doc.iter("source"):
        chk(s.get("src") or (s.get("srcset") or "").split(" ")[0], "source")
    for f in doc.iter("iframe"):
        chk(f.get("src"), "iframe")
    rec["assets_missing"] = assets_missing[:30]
    rec["assets_ext"] = sorted(assets_ext)
    rec["mixed_content"] = bool(re.search(r'(src|href)=["\']http://', text))
    rec["inline_script_bytes"] = sum(len(s.text or "") for s in doc.iter("script") if not s.get("src"))
    rec["has_form"] = doc.find(".//form") is not None
    return rec

def main():
    files = []
    for root, dirs, fs in os.walk(SITE):
        for f in fs:
            if f.endswith(".html"):
                files.append(os.path.join(root, f))
    files.sort()
    print(f"{len(files)} html files", flush=True)
    with ProcessPoolExecutor() as ex:
        recs = list(ex.map(analyze, files, chunksize=64))
    by_file = {r["file"]: r for r in recs}
    frag_broken = []
    for r in recs:
        for href, tfile in r.get("frag_links", []):
            frag = urllib.parse.urlsplit(href).fragment
            frag = urllib.parse.unquote(frag)
            t = by_file.get(tfile)
            if t is None:
                continue
            if frag and frag not in set(t["ids"]) and frag != "top":
                frag_broken.append((r["file"], href))
    sm_urls = set()
    sm_path = os.path.join(SITE, "sitemap.xml")
    sm_info = {}
    if os.path.exists(sm_path):
        try:
            tree = etree.parse(sm_path)
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            is_index = tree.getroot().tag.endswith("sitemapindex")
            sm_info["is_index"] = is_index
            locs = [e.text for e in tree.findall(".//s:loc", ns)]
            lastmods = [e.text for e in tree.findall(".//s:lastmod", ns)]
            if is_index:
                subs = locs; locs = []; lastmods = []
                sm_info["subs"] = len(subs)
                for s in subs:
                    sp = os.path.join(SITE, urllib.parse.urlsplit(s).path.lstrip("/"))
                    if os.path.exists(sp):
                        st = etree.parse(sp)
                        locs += [e.text for e in st.findall(".//s:loc", ns)]
                        lastmods += [e.text for e in st.findall(".//s:lastmod", ns)]
                    else:
                        sm_info.setdefault("missing_subs", []).append(s)
            sm_info["count"] = len(locs)
            sm_info["size_bytes"] = os.path.getsize(sm_path)
            sm_info["lastmod_count"] = len(lastmods)
            sm_info["lastmod_distinct"] = len(set(lastmods))
            sm_info["lastmod_sample"] = sorted(set(lastmods))[-3:]
            for l in locs:
                p = urllib.parse.urlsplit(l)
                sm_info.setdefault("hosts", set()).add(p.netloc)
                sm_urls.add(p.path)
            sm_info["hosts"] = sorted(sm_info.get("hosts", []))
        except Exception as e:
            sm_info["error"] = str(e)
    sm_missing_files = []
    for u in sm_urls:
        t, _, _ = resolve_internal(u, os.path.join(SITE, "index.html"))
        if t is None:
            sm_missing_files.append(u)
    indexable = [r for r in recs if not (r.get("robots") and "noindex" in r["robots"])]
    noindex_in_sitemap = [r["url"] for r in recs if r.get("robots") and "noindex" in r["robots"] and (r["url"] in sm_urls or r["file"] in sm_urls)]
    not_in_sitemap = [r["url"] for r in indexable if r["url"] not in sm_urls and (r["url"] + "index.html") not in sm_urls and r["url"].replace("/index.html", "/") not in sm_urls and r["file"] not in sm_urls]
    machine = {}
    for name in ("feed.xml", "sitemap.xml", "badge.svg", "manifest.json", "robots.txt", "llms.txt", "belt.ics", "ads.txt", "CNAME", "404.html", "sw.js", "offline.html", "api/current.json", "api/reigns.json", "api/games.json", "search/index.json", "favicon.ico"):
        p = os.path.join(SITE, name)
        if not os.path.exists(p):
            machine[name] = "MISSING"; continue
        info = {"size": os.path.getsize(p)}
        try:
            if name.endswith((".xml", ".svg")):
                etree.parse(p); info["valid"] = True
            elif name.endswith(".json"):
                json.load(open(p)); info["valid"] = True
            elif name == "robots.txt":
                info["text"] = open(p).read()[:600]
            elif name == "CNAME":
                info["text"] = open(p).read().strip()
        except Exception as e:
            info["valid"] = False; info["error"] = str(e)[:200]
        machine[name] = info
    titles = collections.Counter(r.get("title") for r in recs)
    descs = collections.Counter(r.get("description") for r in recs if r.get("description"))
    summary = {
        "site": SITE, "host": HOST, "html_files": len(files),
        "total_bytes": sum(r["size"] for r in recs),
        "no_doctype": sum(1 for r in recs if not r.get("doctype")),
        "no_lang": sum(1 for r in recs if not r.get("lang")),
        "no_title": [r["file"] for r in recs if not r.get("title")][:20],
        "no_description": sum(1 for r in recs if not r.get("description")),
        "no_description_sample": [r["file"] for r in recs if not r.get("description")][:15],
        "no_viewport": sum(1 for r in recs if not r.get("viewport")),
        "no_canonical": sum(1 for r in recs if not r.get("canonical")),
        "no_canonical_sample": [r["file"] for r in recs if not r.get("canonical")][:15],
        "multi_canonical": [r["file"] for r in recs if r.get("canonical_count", 0) > 1][:10],
        "canonical_mismatch": [(r["file"], r["canonical"]) for r in recs if r.get("canonical") and urllib.parse.urlsplit(r["canonical"]).path not in (r["url"], r["file"], r["url"].rstrip("/") or "/", r["url"] + "index.html")][:25],
        "canonical_mismatch_count": sum(1 for r in recs if r.get("canonical") and urllib.parse.urlsplit(r["canonical"]).path not in (r["url"], r["file"], r["url"].rstrip("/") or "/", r["url"] + "index.html")),
        "canonical_hosts": sorted({urllib.parse.urlsplit(r["canonical"]).netloc for r in recs if r.get("canonical")}),
        "no_og_title": sum(1 for r in recs if not r.get("og_title")),
        "no_og_image": sum(1 for r in recs if not r.get("og_image")),
        "og_image_values": collections.Counter(r.get("og_image") for r in recs).most_common(8),
        "no_twitter_card": sum(1 for r in recs if not r.get("twitter_card")),
        "no_h1": sum(1 for r in recs if not r.get("h1")),
        "no_h1_sample": [r["file"] for r in recs if not r.get("h1")][:15],
        "multi_h1": sum(1 for r in recs if len(r.get("h1", [])) > 1),
        "multi_h1_sample": [r["file"] for r in recs if len(r.get("h1", [])) > 1][:10],
        "dup_titles": [(t, c) for t, c in titles.most_common(15) if c > 1 and t],
        "dup_descriptions": [(d[:90], c) for d, c in descs.most_common(10) if c > 1],
        "title_too_long": sum(1 for r in recs if r.get("title") and len(r["title"]) > 70),
        "title_too_long_sample": [r["title"] for r in recs if r.get("title") and len(r["title"]) > 70][:8],
        "desc_too_long": sum(1 for r in recs if r.get("description") and len(r["description"]) > 170),
        "desc_too_short": sum(1 for r in recs if r.get("description") and len(r["description"]) < 50),
        "jsonld_bad": [r["file"] for r in recs if r.get("jsonld_bad")][:10],
        "jsonld_types": collections.Counter(t for r in recs for t in r.get("jsonld_types", [])).most_common(15),
        "pages_without_jsonld": sum(1 for r in recs if not r.get("jsonld_ok")),
        "pages_without_jsonld_sample": [r["file"] for r in recs if not r.get("jsonld_ok")][:12],
        "img_noalt_pages": sum(1 for r in recs if r.get("img_noalt")),
        "img_noalt_total": sum(r.get("img_noalt", 0) for r in recs),
        "img_noalt_sample": [r["file"] for r in recs if r.get("img_noalt")][:10],
        "img_external_hosts": collections.Counter(h for r in recs for h in r.get("img_external", [])).most_common(10),
        "asset_ext_hosts": collections.Counter(h for r in recs for h in r.get("assets_ext", [])).most_common(15),
        "assets_missing": collections.Counter(a[1] for r in recs for a in r.get("assets_missing", [])).most_common(30),
        "assets_missing_pages": sum(1 for r in recs if r.get("assets_missing")),
        "mixed_content": [r["file"] for r in recs if r.get("mixed_content")][:10],
        "broken_links_total": sum(len(r.get("broken", [])) for r in recs),
        "broken_links_pages": sum(1 for r in recs if r.get("broken")),
        "broken_links_top": collections.Counter(b[0] for r in recs for b in r.get("broken", [])).most_common(60),
        "broken_links_sample": [(r["file"], b) for r in recs for b in r.get("broken", [])][:40],
        "frag_broken_total": len(frag_broken),
        "frag_broken_sample": frag_broken[:30],
        "frag_broken_top": collections.Counter(urllib.parse.urlsplit(h).path or "(same page)" for _, h in frag_broken).most_common(15),
        "dup_ids_pages": sum(1 for r in recs if r.get("dup_ids")),
        "dup_ids_sample": [(r["file"], r["dup_ids"][:5]) for r in recs if r.get("dup_ids")][:10],
        "leftovers": collections.Counter(l[0] for r in recs for l in r.get("leftovers", [])).most_common(20),
        "leftovers_sample": [(r["file"], l) for r in recs for l in r.get("leftovers", [])][:80],
        "thin_pages": sum(1 for r in indexable if r.get("words", 0) < 120),
        "thin_pages_sample": sorted([(r.get("words", 0), r["file"]) for r in indexable])[:25],
        "thin_by_section": collections.Counter(r["file"].split("/")[1] + "/" + (r["file"].split("/")[2] if len(r["file"].split("/")) > 3 else "") for r in indexable if r.get("words", 0) < 120).most_common(20),
        "words_hist": collections.Counter((r.get("words", 0) // 100) * 100 for r in recs).most_common(12),
        "largest_pages": sorted([(r["size"], r["file"]) for r in recs], reverse=True)[:12],
        "external_hosts": collections.Counter(urllib.parse.urlsplit(u).netloc for r in recs for u in r.get("external_links", [])).most_common(40),
        "cross_links": collections.Counter(u for r in recs for u in r.get("cross_links", [])).most_common(40),
        "cross_link_pages": sum(1 for r in recs if r.get("cross_links")),
        "noindex_pages": sum(1 for r in recs if r.get("robots") and "noindex" in r["robots"]),
        "noindex_in_sitemap": len(noindex_in_sitemap),
        "noindex_in_sitemap_sample": noindex_in_sitemap[:20],
        "sitemap": sm_info,
        "sitemap_urls_missing_files": sorted(sm_missing_files)[:40],
        "sitemap_urls_missing_count": len(sm_missing_files),
        "indexable_not_in_sitemap": len(not_in_sitemap),
        "indexable_not_in_sitemap_sample": sorted(not_in_sitemap)[:40],
        "machine_files": machine,
        "forms": sum(1 for r in recs if r.get("has_form")),
        "inline_script_avg": sum(r.get("inline_script_bytes", 0) for r in recs) / max(1, len(recs)),
    }
    with open(OUT + "_summary.json", "w") as f:
        json.dump(summary, f, indent=1, default=str)
    with open(OUT + "_pages.jsonl", "w") as f:
        for r in recs:
            r2 = dict(r); r2.pop("ids", None)
            f.write(json.dumps(r2, default=str) + "\n")
    ext = collections.Counter(u for r in recs for u in r.get("external_links", []))
    with open(OUT + "_external.json", "w") as f:
        json.dump(ext.most_common(), f, indent=0)
    print("done", OUT)
    return summary


def ci_gate(summary):
    """Audit #2 (6.10): the checks a deploy must pass. Returns a list of failure strings."""
    fails = []
    if summary["broken_links_total"]:
        fails.append(f"{summary['broken_links_total']} broken internal links on {summary['broken_links_pages']} pages: {summary['broken_links_top'][:5]}")
    if summary["sitemap"].get("error"):
        fails.append("sitemap.xml invalid: " + summary["sitemap"]["error"])
    if summary["sitemap_urls_missing_count"]:
        fails.append(f"{summary['sitemap_urls_missing_count']} sitemap URLs have no file: {summary['sitemap_urls_missing_files'][:5]}")
    if summary["noindex_in_sitemap"]:
        fails.append(f"{summary['noindex_in_sitemap']} noindex pages listed in the sitemap: {summary['noindex_in_sitemap_sample'][:5]}")
    bad = {k: v for k, v in summary["leftovers"] if k in ("1 plural", "bare apostrophe possessive", "literal None", "None in text", "NaN", "undefined", "[object Object]", "__ROOT__ marker", "{{ template }}", "double-escaped &amp;")}
    if bad:
        samples = [x for x in summary["leftovers_sample"] if x[1][0] in bad][:5]
        fails.append(f"template leftovers {bad}: {samples}")
    if summary["no_description"] > 40 or summary["no_canonical"]:
        fails.append(f"{summary['no_description']} pages without a description, {summary['no_canonical']} without a canonical")
    if summary["assets_missing_pages"]:
        fails.append(f"{summary['assets_missing_pages']} pages reference missing assets: {summary['assets_missing'][:5]}")
    return fails


if __name__ == "__main__":
    summ = main()
    if "--ci" in sys.argv:
        problems = ci_gate(summ)
        line = (f"audit: {summ['html_files']:,} pages, {summ['broken_links_total']} broken links, sitemap {summ['sitemap'].get('count')} URLs, "
                f"{summ['thin_pages']} thin, leftovers {summ['leftovers'][:4]}")
        print(line)
        step = os.environ.get("GITHUB_STEP_SUMMARY")
        if step:
            with open(step, "a") as f:
                f.write("### Site audit\n" + line + "\n" + ("".join(f"- FAIL: {x}\n" for x in problems) or "- all checks passed\n"))
        for x in problems:
            print("::error::" + x)
        sys.exit(1 if problems else 0)
