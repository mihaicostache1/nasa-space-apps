# Implementation roadmap

## 0. Foundation — ready

Local setup, two-scenario input shell, validation, team-aligned export types, frontend health route, code quality checks, CI, and architecture/source documentation. The Python ephemeris package and CLI are now installed locally.

## 1. Ephemeris lead - reference milestone complete

Implemented: Python Horizons retrieval, chunking, cache/provenance, JSON/CSV export, observer verification, real archived response fixtures, and offline ingestion/contract tests. The hardened client also supplies angular radii, shared request/cache locks, version checks, Retry-After handling, and immutable validated run bundles. A 30-day dataset at three sourced NASA DEM grid cells, a month-long pointing plot, and three recorded QuickMap camera-observer checks are committed.

Next:

1. Agree verified GIS inputs, mast/altitude conventions, and the extended JSON contract.
2. Review the completed reference-point/camera-observer evidence, then add surface/terrain cases after that integration is available.
3. Run the agreed curated-site precompute after a `--dry-run` request estimate.
4. Backend/data integrates the ephemeris into the FastAPI skeleton, adds the terrain join and derived metrics; frontend connects to that service.

See `docs/ephemeris-lead.md` for handoff details. A working NASA query is not yet independent scientific validation against QuickMap.

## 2. Usable comparison

Backend/data task 1 is complete: FastAPI serves explicit synthetic catalog/scenario data with HTTP contracts, validation, CORS, tests, and Docker startup. See `docs/backend-data.md`. Metrics and real-data integration remain pending.

1. Connect each scenario to `POST /api/evaluations`, with loading, error, and stale-result states; the current API data is synthetic.
2. Add a 2D azimuth/elevation horizon view, elevation timelines, and a shared time cursor.
3. Compute geometric sunlight/Earth visibility duration, next sunset/Earthset, and longest gaps. State the visibility rule and event-time precision. Mark intervals truncated by the selected range.
4. Compare the two scenarios side by side and include source/model details with each result.

Done when changing a location or date yields a clear comparison using verified data, including accessible text alongside charts.

## 3. Terrain and site catalog

1. Add a small, sourced catalog of historic or candidate sites.
2. Download a bounded LOLA region; preserve source metadata and reference-surface conventions.
3. Generate and validate azimuth-dependent horizon profiles.
4. Add an explicit choice between geometric and terrain-aware visibility; show resolution and missing-data limits.
5. Add contextual mapping or 3D views once the science path is reliable.

## 4. Presentation and delivery

Add scenario export/share support, educational explanations, mobile/keyboard checks, dataset attributions, a demo narrative, and an accurate AI-use disclosure. Document unresolved limitations before preparing the Space Apps submission.
