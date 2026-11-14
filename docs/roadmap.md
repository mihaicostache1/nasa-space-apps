# Implementation roadmap

## 0. Foundation — ready

Local setup, two-scenario input shell, validation, team-aligned export types, frontend health route, code quality checks, CI, and architecture/source documentation. The Python ephemeris package and CLI are now installed locally.

## 1. Ephemeris lead - reference milestone complete

Implemented: Python Horizons retrieval, chunking, cache/provenance, JSON/CSV export, observer verification, real archived response fixtures, and offline ingestion/contract tests. The hardened client also supplies angular radii, shared request/cache locks, version checks, Retry-After handling, and immutable validated run bundles. A 30-day dataset at three sourced NASA DEM grid cells, a month-long pointing plot, and three recorded QuickMap camera-observer checks are committed.

Next:

1. A validated terrain mask is available for Site01 (`data/reference/terrain-masks/lola-site01-reference-mast-0m.json`), matching the archived ephemeris observer (ground + 0 m mast above the 1737.4 km sphere).
2. Review the completed reference-point/camera-observer evidence, then add surface/terrain cases after that integration is available.
3. Run the agreed curated-site precompute after a `--dry-run` request estimate.
4. Backend/data integrates the ephemeris and GIS masks with the FastAPI visibility engine; frontend connects to that service.

See `docs/ephemeris-lead.md` for handoff details. A working NASA query is not yet independent scientific validation against QuickMap.

## 2. Usable comparison

Backend/data tasks 1 and 2 are complete: FastAPI serves explicit synthetic catalog/scenario data with HTTP contracts, validation, CORS, tests, and Docker startup. A reusable engine now calculates disc visibility, metrics, windows, and countdown brackets. See `docs/backend-data.md` and `docs/visibility.md`. Real-data integration, caching, and precomputation remain pending.

1. Connect each scenario to `POST /api/evaluations`, with loading, error, and stale-result states; the current API data is synthetic.
2. Add a 2D azimuth/elevation horizon view, elevation timelines, and a shared time cursor.
3. Calculation engine complete: visibility duration, next sunset/Earthset brackets, longest gaps, selectable disc rules, and truncated-range markers. Feed it verified real inputs and expose its precision/model details in the UI.
4. Compare the two scenarios side by side and include source/model details with each result.

Done when changing a location or date yields a clear comparison using verified data, including accessible text alongside charts.

## 3. Terrain and site catalog — P2 milestone complete

Implemented: checksummed LOLA 5 m/20 m/120 m downloads, exact ray-cast horizons, one validated demo mask (`data/reference/terrain-masks/lola-site01-reference-mast-0m.json`, `lunarwindow.terrain-mask.v1`), a sourced 17-site catalog with preliminary horizons that agree with PGDA long-term sunlight maps, and cached custom-coordinate horizons. See `docs/terrain-gis-lead.md`.

Next:

1. Backend/data loads the Site01 mask through `TerrainMask` and checks it against the archived ephemeris observer and frame.
2. Later, if time allows: ephemerides and horizons for further curated sites, and `HorizonService` for custom coordinates.
3. Add an explicit choice between geometric and terrain-aware visibility; show resolution, truncated-azimuth, and `terrainModel: "none"` limits.
4. Add contextual mapping or 3D views using `rays.el` and `rays.horizonDistanceKm`.

## 4. Presentation and delivery

Add scenario export/share support, educational explanations, mobile/keyboard checks, dataset attributions, a demo narrative, and an accurate AI-use disclosure. Document unresolved limitations before preparing the Space Apps submission.
