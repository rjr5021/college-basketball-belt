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


_P = {}

# data/places.json: {team id: [city, state, lat, lon]}, each program's home
# city, geocoded once from the API's team and venue fields against GeoNames
# (the cities.json npm package, CC-BY 4.0).


def place(code, season=None):
    if not _P:
        path = os.path.join("data", "places.json")
        if os.path.exists(path):
            with open(path) as f:
                _P.update(json.load(f))
    v = _P.get(str(code))
    return tuple(v) if v else None


STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "Washington, D.C.", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


LEAGUE = {
    "key": "cbb", "name": "College Basketball", "long_name": "The College Basketball Belt", "first_season": 1950,
    "tie_rule": "holder", "sport": "Basketball", "team_name": team_name, "team_colors": team_colors,
    "short_name": team_name, "season_label": season_label,
    "place": place, "state_names": STATE_NAMES,
    "singular": True, "unit": "programs", "post_word": "postseason", "feed": False,
    "champions_note": "Here the champion is the NCAA tournament winner.",
}
LIVE = [LEAGUE]
