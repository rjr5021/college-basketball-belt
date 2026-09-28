#!/usr/bin/env python3
"""
One-time download of Prof. John Trono's NCAA Men's Basketball Scores Archive
(St. Michael's College): every Division I vs. Division I game, 1949-50
through 1999-2000, plus the NCAA, NIT and other postseason files.

    https://academics.smcvt.edu/jtrono/BBallArchive.htm

The data this site gets from CollegeBasketballData is missing most
neutral-site games before 2000-01 (holiday and conference tournaments), so
build_supplement.py fills those in from this archive.

Writes data/trono/<file>.txt (one game per line, as published:
"date tm1 score1 tm2 score2 loc", date = month code 1-7 for Oct-Apr + day)
and data/trono/Translation.txt (team codes).
"""

import html
import os
import re
import time
import urllib.request

BASE = "https://academics.smcvt.edu/jtrono/"
OUT = os.path.join("data", "trono")
UA = {"User-Agent": "collegebasketballbelt.com data build (one-time archive download)"}


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read().decode("latin-1")
        except Exception as e:  # noqa: BLE001
            print("  retry", url, e)
            time.sleep(3 * (i + 1))
    return None


def text(page):
    page = re.sub(r"(?is)<(script|style).*?</\1>", "", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", page)
    return html.unescape(re.sub(r"<[^>]+>", "", page))


def main():
    os.makedirs(OUT, exist_ok=True)
    index = get(BASE + "BBallArchive.htm")
    links = sorted(set(re.findall(r'(?i)href="([^"]*NCAA_Archive/[^"]+\.htm)"', index or "")))
    print(len(links), "archive links")
    got = 0
    for href in links:
        url = href if href.startswith("http") else BASE + href.lstrip("./")
        name = url.rsplit("/", 1)[-1][:-4]
        page = get(url)
        if not page:
            print("  MISSING", url)
            continue
        body = text(page)
        if name == "Translation":
            lines = [l.strip() for l in body.splitlines() if re.match(r"^\s*\S{3}\s+\S", l)]
        else:
            lines = [l.strip() for l in body.splitlines() if re.match(r"^\s*\d{3,4}\s+\S+\s+\d+\s+\S+\s+\d+", l)]
        with open(os.path.join(OUT, name + ".txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        got += 1
        time.sleep(0.5)
    print(f"saved {got} files to {OUT}")


if __name__ == "__main__":
    main()
