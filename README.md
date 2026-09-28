# The College Basketball Belt

The lineal championship of men's college basketball — collegebasketballbelt.com.
Beat the holder, take the belt. Sister site of collegefootballbelt.com and part
of the Belt Holders network (beltholders.com).

```
fetch_games.py     CollegeBasketballData API -> data/games/<season>.csv (+ data/teams.json)
cbb_data.py        loads those files into the engine's game schema (Division I games only)
belt_engine.py     the belt walk + vacancy rules (shared with the College Football Belt)
build_lineage.py   -> data/lineage.json
build_site.py      -> site/
generate_assets.py favicon / touch icon / share card (run once, committed)
```

```
CBBD_API_KEY=... python fetch_games.py   # incremental; --full to backfill every season
python build_lineage.py
python build_site.py
python -m http.server -d site            # preview at http://localhost:8000
```

GitHub Actions (`.github/workflows/update.yml`) fetches new games every three
hours, commits them, rebuilds and deploys to GitHub Pages. The API key lives
only in the repo's `CBBD_API_KEY` Actions secret.

Rules: the game-by-game record starts with 1949–50, so the belt starts with
the 1949 national champion (Kentucky). Both teams must be Division I that
season. Full ruleset on the site's /rules/ page.

Settings in build_site.py: `ADSENSE_PUBLISHER_ID` (pub-3317069252410560 once
approved) and `GOATCOUNTER_CODE`.
