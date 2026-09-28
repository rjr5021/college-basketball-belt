"""
The College Basketball Belt as a single "league" dict, in the same shape
Belt Holders' league adapters use, so site_extras.py (ported from Belt
Holders) can build the deeper pages here too. Names and colors come from
data/lineage.json, which build_lineage.py writes first.
"""

import json
import os

from cbb_data import season_label

_T = {}


def _load():
    if not _T:
        path = os.path.join("data", "lineage.json")
        if os.path.exists(path):
            with open(path) as f:
                _T.update(json.load(f).get("teams", {}))


def team_name(code, season=None):
    _load()
    return (_T.get(str(code)) or {}).get("name", str(code))


def team_colors(code):
    _load()
    t = _T.get(str(code)) or {}
    return t.get("primary") or "#5b5140", t.get("secondary") or "#cfc4ad"


LEAGUE = {
    "key": "cbb", "name": "College Basketball", "long_name": "The College Basketball Belt", "first_season": 1950,
    "tie_rule": "holder", "sport": "Basketball", "team_name": team_name, "team_colors": team_colors,
    "short_name": team_name, "season_label": season_label,
}
LIVE = [LEAGUE]
