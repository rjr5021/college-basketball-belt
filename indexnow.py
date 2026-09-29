#!/usr/bin/env python3
"""
IndexNow (CBB-7/BH-16, ported from the College Football Belt): tell Bing, DuckDuckGo, Yahoo
and Yandex which pages changed, so they re-crawl them within hours. Google ignores IndexNow
and keeps reading the sitemap.

build_site.py calls write() at the end of a build. It writes the key file the engines check
ownership with (/<KEY>.txt) and indexnow-changed.json: every sitemap URL whose <lastmod> is
today or yesterday, plus the homepage. The deploy workflow reads that list back from the live
site after the deploy and POSTs it once to api.indexnow.org. Never fails a build or a deploy.
"""

import json
import os
import re
from datetime import date, timedelta

SITE_URL = "https://collegebasketballbelt.com"
KEY = "543ebbf64935f9fb342a02781af5b38d"
MAX_URLS = 10000                 # the protocol's per-request limit


def _sitemaps(out):
    root = os.path.join(out, "sitemap.xml")
    if not os.path.exists(root):
        return []
    with open(root, encoding="utf-8") as f:
        xml = f.read()
    if "<sitemapindex" not in xml:
        return [xml]
    docs = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
        p = os.path.join(out, *loc[len(SITE_URL) + 1:].split("/"))
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                docs.append(f.read())
    return docs


def write(out="site"):
    since = (date.today() - timedelta(days=1)).isoformat()
    changed = [SITE_URL + "/"]
    for xml in _sitemaps(out):
        for loc, mod in re.findall(r"<url><loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", xml):
            if mod[:10] >= since and loc not in changed:
                changed.append(loc.replace("&amp;", "&"))
    with open(os.path.join(out, f"{KEY}.txt"), "w", encoding="utf-8") as f:
        f.write(KEY)
    with open(os.path.join(out, "indexnow-changed.json"), "w", encoding="utf-8") as f:
        json.dump({"host": SITE_URL.split("//")[1], "key": KEY, "keyLocation": f"{SITE_URL}/{KEY}.txt",
                   "urlList": changed[:MAX_URLS]}, f)
    print(f"IndexNow: {len(changed)} changed URLs listed")
    return len(changed)


if __name__ == "__main__":
    write()
