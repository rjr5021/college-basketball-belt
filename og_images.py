#!/usr/bin/env python3
"""Share images (1200x630) showing each belt's current holder, written into
site/<lg>/og.png after build_site.py. Needs Pillow (the workflow installs it).
Every page under /<lg>/ points its og:image here, so a shared link shows who
holds the belt right now."""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
MONO = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"]


def font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def card(path, league, holder, since, defenses, primary, secondary, site, kicker="CURRENT HOLDER"):
    W, H = 1200, 630
    top = rgb(primary)
    bot = tuple(int(x * 0.62) for x in top)
    im = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)))
    ink = (246, 241, 230) if lum(top) < 0.45 else (33, 26, 18)
    acc = rgb(secondary) if secondary else (214, 176, 106)
    d.rectangle([0, 0, 18, H], fill=acc)
    d.text((70, 70), f"{league.upper()} BELT · {kicker}", font=font(MONO, 30), fill=ink)
    size = 150
    f = font(FONTS, size)
    words, lines = holder.upper().split(), []
    while True:
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= W - 140:
                cur = t
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= 3 and all(d.textlength(l, font=f) <= W - 140 for l in lines):
            break
        size -= 8
        f = font(FONTS, size)
    y = 150
    for l in lines:
        d.text((66, y), l, font=f, fill=ink)
        y += int(size * 1.02)
    d.text((70, H - 110), f"Since {since} · {defenses} defense{'s' if defenses != 1 else ''}", font=font(MONO, 32), fill=ink)
    d.text((70, H - 62), site, font=font(MONO, 26), fill=ink)
    im.save(path, optimize=True)


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "site"
    try:
        from leagues import LIVE
        targets = [(lg, os.path.join("data", lg["key"], "lineage.json"), os.path.join(site, lg["key"], "og.png"), "beltholders.com") for lg in LIVE]
    except ImportError:
        from cbb_league import LEAGUE
        targets = [(LEAGUE, os.path.join("data", "lineage.json"), os.path.join(site, "og-holder.png"), "collegebasketballbelt.com")]
    from datetime import date
    for lg, lp, outp, host in targets:
        with open(lp) as fh:
            d = json.load(fh)
        cur = d["current"]
        p, s = lg["team_colors"](cur["team"])
        dt = date.fromisoformat(cur["start_date"])
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        card(outp, lg["name"], lg["team_name"](cur["team"]), f"{dt:%b} {dt.day}, {dt.year}", cur.get("defenses", 0), p, s, host)
        print("wrote", outp)


if __name__ == "__main__":
    main()
