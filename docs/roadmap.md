# Implementation roadmap

## 0. Foundation — ready

Local setup, two-scenario input shell, validation, team-aligned export types, frontend health route, code quality checks, CI, and architecture/source documentation. The Python ephemeris package and CLI are now installed locally.

## 1. Ephemeris lead - reference milestone complete

Implemented: Python Horizons retrieval, chunking, cache/provenance, JSON/CSV export, observer verification, real archived response fixtures, and offline ingestion/contract tests. The hardened client also supplies angular radii, shared request/cache locks, version checks, Retry-After handling, and immutable validated run bundles. A 30-day dataset at three sourced NASA DEM grid cells, a month-long pointing plot, and three recorded QuickMap camera-observer checks are committed.

Next:

1. A validated terrain mask is available for Site01 (`data/reference/terrain-masks/lola-site01-reference-mast-0m.json`), matching the archived ephemeris observer (ground + 0 m mast above the 1737.4 km sphere).
2. Review the completed reference-point/camera-observer evidence, then add surface/terrain cases after that integration is available.
3. Run the agreed curated-site precompute after a `--dry-run` request estimate.
4. The backend now integrates the reviewed Site01 mask with archived ephemerides and the FastAPI visibility engine. Frontend integration remains pending.

See `docs/ephemeris-lead.md` for handoff details. A working NASA query is not yet independent scientific validation against QuickMap.

## 2. Usable comparison

The backend serves synthetic scenarios and verified reference-data geometric or Site01 terrain evaluations, with HTTP contracts, validation, CORS, tests, and Docker startup. Archived-data and reviewed-terrain integration are complete, including loaders, range selection, observer/frame checks, response provenance, engine integration, and dedicated model regression baselines. See `docs/backend-data.md`, `docs/visibility.md`, and `docs/validation/terrain-regression.md`. Extended precomputation and frontend terrain integration remain pending.

Reference evaluations now use the versioned cache-key contract and bounded in-memory LRU storage after source integrity, date selection, and terrain compatibility checks. Repeated requests reuse validated response snapshots and skip visibility calculation while preserving source checks, provenance, and HTTP errors. Tests cover source/mask/model invalidation, isolation, bounds, and warmed-cache failure cases. Extended curated-site precomputation remains separate.

The [offline evaluation precompute manifest contract and generator](precompute.md) are implemented with job identities, verified-source checks, checksummed atomic outputs, and complete/incomplete checkpoints. Explicit geometric and Site01 terrain job lists are tested against existing verified archives and reviewed masks, including failure handling. Next small task: independently verify generated bundles before adding a CLI or persisted-result API integration.

1. Connect the frontend to the reference site catalog and `POST /api/reference/evaluations`, with loading, error, and stale-result states. Synthetic custom-coordinate demos remain at `POST /api/evaluations`.
2. Add a 2D azimuth/elevation horizon view, elevation timelines, and a shared time cursor.
3. The engine and verified geometric/terrain reference integrations are complete. Expose the visibility rule, timing precision, source provenance, frame approximation, and truncated-range markers in the UI.
4. Compare the two scenarios side by side and include source/model details with each result.
5. Done: the frontend uses the reference site catalog and `POST /api/reference/evaluations`, with loading, error, and stale-result states.
6. Done: three-lane timeline with a shared cursor, longest simultaneous operation and communication outage, mission window finder, and a 2D azimuth/elevation sky explorer.
7. Done: the visibility rule, timing precision, source, geometric model, and truncated-range markers are shown in the UI.
8. Next: load the validated Site01 terrain mask, demo rehearsal in a clean browser, and deployment.

Done when changing a location or date yields a clear comparison using verified data, including accessible text alongside charts.

## 3. Terrain and site catalog — P2 milestone complete

Implemented: checksummed LOLA 5 m/20 m/120 m downloads, exact ray-cast horizons, one validated demo mask (`data/reference/terrain-masks/lola-site01-reference-mast-0m.json`, `lunarwindow.terrain-mask.v1`), a sourced 17-site catalog with preliminary horizons that agree with PGDA long-term sunlight maps, and cached custom-coordinate horizons. See `docs/terrain-gis-lead.md`.

Next:

1. Independently validate surface/terrain predictions and agree on a real antenna height before generating further matched observer datasets. The reviewed 0 m reference backend integration is complete, with explicit frame-approximation acceptance and regression coverage.
2. Later, if time allows: ephemerides and horizons for further curated sites, and `HorizonService` for custom coordinates.
3. The API exposes an explicit geometric/terrain choice. Add that control to the frontend and show source resolution, observer height, frame assumptions, and coverage limits; preliminary GIS horizons remain distinct from registered reference masks.
   The reference site catalog now advertises supported horizon modes and verified mask selection metadata, including observer heights, checksums, DEM sources, and the explicit frame-approximation requirement.
4. Add contextual mapping or 3D views using `rays.el` and `rays.horizonDistanceKm`.

## 4. Presentation and delivery

Add scenario export/share support, educational explanations, mobile/keyboard checks, dataset attributions, a demo narrative, and an accurate AI-use disclosure. Document unresolved limitations before preparing the Space Apps submission.
