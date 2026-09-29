#!/usr/bin/env python3
"""
NET-2 for college basketball: catch a game feed that stopped quietly. The fetch
steps are continue-on-error, so a blocked source used to freeze the belt while the
site looked fine. Run after the data updates and before build_site.py:

    python check_freshness.py          # writes data/health.json, prints a summary

A belt ("cbb" men, "women") is flagged "delayed" when
  * games scheduled in the last two weeks are 2+ days past with no result, and no
    result at all has come in since the first of them (one postponed game doesn't
    trip it; stale rows from old seasons are ignored), or
  * it's the heart of the season (Nov 10 to Apr 8) and the newest result is more
    than STALE_DAYS old.
build_site.py shows "Data delayed" on the holder card and puts data_ok in
api/current.json; the update workflow opens (or comments on) a GitHub issue.
(beltholders.com runs its own check_freshness.py over the pro leagues.)
"""

import json
import os
import sys
from datetime import date, timedelta

STALE_DAYS = 5        # there are games nearly every day from November to early April
WINDOW_DAYS = 14


def in_season(d):
    return (d.month, d.day) >= (11, 10) or (d.month, d.day) <= (4, 8)


def check(rows, today):
    newest = max((r["date"] for r in rows if r["status"] == "final" and r.get("home_points", "") != ""), default="")
    lo, hi = (today - timedelta(days=WINDOW_DAYS)).isoformat(), (today - timedelta(days=2)).isoformat()
    overdue = sorted(r["date"] for r in rows if r["status"] == "scheduled" and lo <= r["date"] <= hi)
    if overdue and newest < overdue[0]:
        return {"ok": False, "newest_result": newest,
                "reason": f"{len(overdue)} scheduled game(s) since {overdue[0]} have no result, and nothing newer has come in"}
    if in_season(today) and newest and newest < (today - timedelta(days=STALE_DAYS)).isoformat():
        return {"ok": False, "newest_result": newest, "reason": f"in season, but the newest result is from {newest}"}
    return {"ok": True, "newest_result": newest}


def main():
    import cbb_data
    import women_data
    today = date.today()
    out = {"checked": today.isoformat(), "leagues": {}}
    for key, mod in (("cbb", cbb_data), ("women", women_data)):
        try:
            out["leagues"][key] = check(list(mod._rows()), today)
        except Exception as e:  # noqa: BLE001
            out["leagues"][key] = {"ok": False, "reason": f"couldn't read the game files: {type(e).__name__}"}
    os.makedirs("data", exist_ok=True)
    with open(os.path.join("data", "health.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    for k, v in out["leagues"].items():
        print(f"{'ok     ' if v['ok'] else 'DELAYED'} {k:6} newest result {v.get('newest_result', '?')}" + ("" if v["ok"] else f" -- {v['reason']}"))
    bad = {k: v for k, v in out["leagues"].items() if not v["ok"]}
    if bad and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("### Data delayed\n" + "".join(f"- **{k}**: {v['reason']}\n" for k, v in bad.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
