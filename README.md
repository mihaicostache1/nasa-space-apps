# LunarWindow - Lunar Landing Site Navigator

Project scaffold for the [NASA Space Apps 2026 challenge](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/).

The intended application compares lunar landing locations and dates through Sun/Earth positions, sunlight duration, and direct-to-Earth visibility windows. The initial focus is the lunar south pole. The team plan separates a Python/FastAPI data backend from a React frontend; this repository now includes the Ephemeris lead's Python package alongside the existing Next.js/React UI starter.

## Start with Docker

With Docker running, the team can start the web app without installing Node.js or Python:

```sh
docker compose up --build -d --wait
```

Open [localhost:3000](http://localhost:3000) for the UI and [localhost:8000/docs](http://localhost:8000/docs) for the FastAPI demo API. Run the ephemeris tool separately:

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z --end 2026-11-15T00:00:00Z
```

Exports and caches persist in `./data`. See [Docker instructions](docs/docker.md) for tests, Linux file ownership, port configuration, and image-only commands. FastAPI serves synthetic demos and geometric or reviewed-terrain evaluations of verified archived ephemerides. The React workspace is not connected to these results yet.

## Native setup: Backend/data

The first two backend tasks, **API skeleton with fake data** and **visibility metrics, windows, and countdowns**, are implemented:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'
python -m uvicorn lunarwindow.api.app:app --reload --port 8000
```

Open [localhost:8000/docs](http://localhost:8000/docs). `POST /api/evaluations` serves synthetic scenarios. `GET /api/reference/sites` lists verified reference points and available dates; `POST /api/reference/evaluations` calculates visibility, metrics, windows, and setting brackets from their archived NASA samples with an explicit geometric horizon. Optional `visibilityRule` and `asOfUtc` select the policy and countdown reference. See the [API contract](docs/backend-data.md) and [calculation model](docs/visibility.md) for request examples, source provenance, and precision limits.

## Native setup: Ephemeris lead

Python 3.11+; pip installs the declared contract-validation dependency. No NASA API key is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./backend
lunarwindow-ephemeris --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z --end 2026-11-15T00:00:00Z
python -m unittest discover -s backend/tests -v
```

Each export creates `data/processed/ephemeris/<run-id>/` with JSON/CSV pairs and a checksum manifest. Raw response caches stay under `data/raw/horizons/`. The sample site is illustrative. See [Python setup](backend/README.md), [your work package](docs/ephemeris-lead.md), [libration notes](docs/libration.md), and [QuickMap validation protocol](docs/validation/quickmap.md).

## Native setup: Terrain/GIS lead

```sh
python -m pip install -e './backend[gis,analysis]'
lunarwindow-terrain download --all          # ~3.7 GB of NASA PGDA rasters into data/raw/lola/
lunarwindow-terrain horizons --plots \
  --sites data/sites.curated.json data/sites.shackleton-rim.json data/sites.artemis-regions.json
python scripts/export_terrain_mask.py --site-id lola-site01-reference   # validated demo mask
```

Horizon profiles (360 whole-degree values plus 3,600 rays) are computed by exact spherical ray casting over the 20 m and 120 m LOLA south polar DEMs, out to 200 km, with ground + 2 m mast observers. The one validated demo mask is `data/reference/terrain-masks/lola-site01-reference-mast-0m.json`: same coordinates and observer altitude as the archived Site01 ephemerides, 5 m/20 m/120 m DEM tiers, full DEM provenance. Horizons for the other 16 curated sites are preliminary. See [the terrain work package](docs/terrain-gis-lead.md) for sources, algorithm, validation, and handoff.

## Native setup: React UI starter

Use Node.js 22.12+ on the 22.x line, or Node.js 24.x, with npm. An `.nvmrc` is included for Node 22.

```sh
nvm install
nvm use
npm ci
npm run dev
```

Open [localhost:3000](http://localhost:3000). No API keys, database, Docker, or environment variables are required. `.env.example` is provided for future configuration; copying it is optional.

## What is ready

- Next.js App Router, React, and strict TypeScript.
- Responsive two-scenario workspace with editable coordinates, UTC dates, sample intervals, and validation.
- FastAPI skeleton with deterministic synthetic site/scenario data, HTTP validation, CORS, OpenAPI, and Docker startup.
- Verified reference-data loader, site catalog, date-range selection, and geometric evaluations with original NASA evidence and archive coverage.
- Reusable visibility engine with partial-disc rules, circular horizon interpolation, metrics, merged windows, clipped-range flags, and countdown brackets.
- Python Horizons client/CLI with sequential chunked requests, caching, JSON/CSV export, observer checks, and source provenance.
- Flat Sun/Earth series matching the team's JSON field names, with corresponding TypeScript types.
- Offline Python regression tests, shared request locks, retry handling, immutable run bundles, and JSON Schema/semantic handoff checks.
- A sourced 30-day, three-point NASA reference dataset, pointing plot, and reproducible QuickMap comparison evidence.
- A validated terrain horizon mask for the Site01 reference point (`lunarwindow.terrain-mask.v1`), plus tooling for a sourced 17-site catalog (9 Artemis III regions, Shackleton rim, landing sites, contrast cases) whose preliminary horizons match NASA PGDA 18.6-year sunlight averages within 4 percentage points at 12 of 14 polar sites.
- Health endpoint at `GET /api/health`.
- ESLint, Prettier, Vitest, production build, and GitHub Actions checks.
- Challenge analysis, architecture, data-source notes, and an implementation roadmap.

The UI workspace validates inputs locally. It does not persist them or consume backend results yet. Charts, maps, and a site picker remain pending. The API calculates visibility and metrics from synthetic demos or verified archived ephemerides, with an explicit geometric or reviewed-terrain horizon mode. Terrain mode currently supports the Site01 0 m mask and requires acceptance of its frame approximation; sampling, disc-model, and near-field limitations remain. A sourced 17-site GIS catalog is also available (see the [terrain work package](docs/terrain-gis-lead.md)); its other horizons are preliminary and are not registered for reference API evaluations. The reference catalog contains sourced DEM grid cells, not approved landing targets. Three QuickMap camera-observer comparisons pass at display precision; they validate displayed Sun/Earth angles for observers about 100–144 km above the surface, not terrain shadows seen by a lander on the ground. See [the validation report](docs/validation/report.md).

## Structure

```text
.github/workflows/ci.yml       Automated checks
backend/
  pyproject.toml              Installable Python package and CLI
  src/lunarwindow/api/        FastAPI app, contracts, demo and reference providers
  src/lunarwindow/ephemeris/  Models, Horizons client/parser, export CLI
  src/lunarwindow/visibility/ Visibility engine, metrics, windows, and contracts
  src/lunarwindow/terrain/    LOLA downloads, horizon ray casting, site catalog, service
  tests/                     Offline tests and archived NASA fixtures
data/
  sites.example.json          Illustrative input catalog
  raw/                        Downloaded source data (ignored)
  processed/                  Derived data (ignored)
  README.md                   Provenance and storage conventions
docs/
  challenge.md                Requirements mapped from the NASA brief
  architecture.md             Module boundaries and API direction
  data-sources.md              NASA references and coordinate conventions
  roadmap.md                  Suggested implementation sequence
scripts/                      Reference-point, QuickMap, rim-band, and terrain validation tools
src/
  app/
    api/health/route.ts        Working health endpoint
    layout.tsx                Application metadata and root layout
    page.tsx                  Starter page
    globals.css               Base styling
  domain/
    scenario.ts               Input schemas and shared types
    ephemeris.ts              Team-aligned Python export types
    horizon.ts                Terrain horizon profile types
    evaluation.ts             FastAPI demo response types
  features/
    scenarios/components/     Editable comparison workspace
  server/
    providers/                Notes for optional frontend-side adapters
tests/                        Offline contract tests
```

## Commands

| Command                | Purpose                                           |
| ---------------------- | ------------------------------------------------- |
| `npm run dev`          | Run development server                            |
| `npm run build`        | Create production build                           |
| `npm start`            | Serve the production build                        |
| `npm run lint`         | Check code quality                                |
| `npm run typecheck`    | Generate Next.js route types and check TypeScript |
| `npm test`             | Run offline tests                                 |
| `npm run test:watch`   | Watch tests during development                    |
| `npm run format`       | Format source and documentation                   |
| `npm run format:check` | Check formatting                                  |
| `npm run check`        | Run lint, types, tests, and production build      |

## Next step

The [terrain-aware evaluation endpoint](docs/backend-data.md#terrain-aware-evaluation-contract) now connects archived ephemerides and the reviewed Site01 mask to the existing visibility engine, with checksum verification, observer/frame checks, and complete provenance. Geometric v1 remains available; terrain v2 requires explicit acceptance of the frame approximation. Next add dedicated terrain-blocking regression cases, then caching and curated-site precomputation, and connect the frontend. See the [backend work package](docs/backend-data.md), [visibility model](docs/visibility.md), and [ephemeris handoff](docs/ephemeris-lead.md). The long 2026-2030 batch is supported by the CLI but has not been run.
