# Docker setup

Install Docker Desktop (Windows/macOS) or Docker Engine with the Compose v2 plugin (Linux), and start its engine. No local Node.js, npm, Python, or virtual environment is needed for container use. Run commands from the cloned repository root.

## Start the app

```sh
docker compose up --build -d --wait
```

Open [localhost:3000](http://localhost:3000) for the UI and [localhost:8000/docs](http://localhost:8000/docs) for the FastAPI demo API. The first run downloads base images, installs dependencies, and creates a production build; later starts reuse the built image. To change host ports, set `WEB_PORT` or `API_PORT` in `.env`, for example `WEB_PORT=3100` and `API_PORT=8100`. Update `LUNARWINDOW_CORS_ORIGINS` to match a changed web origin. No `.env` file is required for the default setup.

```sh
docker compose ps
docker compose logs -f web
docker compose down
```

The web image uses Next.js standalone output, runs as a non-root user, includes static assets, and has an HTTP health check. The API image also runs as a non-root user and checks `/api/health`. Both ports bind locally. The current UI remains the scenario starter; the separate FastAPI API serves explicitly synthetic data. See the [backend work package](backend-data.md). Real terrain models and UI/data integration remain pending.

Start the API alone with `docker compose up --build -d --wait api`; inspect it with `docker compose logs -f api`. No source-data mount or NASA access is needed for the demo API.

## Run ephemeris exports

The ephemeris service is an on-demand Python command, not a long-running server. Compose starts it only when requested; the `tools` profile keeps it out of a normal web startup.

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z \
  --end 2026-11-15T00:00:00Z
```

JSON/CSV exports and a completion/checksum manifest appear under a new `data/processed/ephemeris/<run-id>/` directory; original NASA response caches appear under `data/raw/horizons/`. They persist when the command exits or containers are removed. The bind mount also makes your verified site catalog available inside the container. Live exports require internet access to NASA; no API key is needed.

Preview requests without using the network:

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-01-01T00:00:00Z \
  --end 2031-01-01T00:00:00Z --dry-run
```

The default site is illustrative. Replace it with GIS-verified inputs before generating named-site results. Existing runs are retained. No final run directory is published if a site fails; validated request caches are reused on a later invocation.

The container uses UID/GID 1000 by default. Docker Desktop normally handles the host bind mount automatically. On Linux, if your checkout is owned by another UID/GID, put your numeric `LOCAL_UID` and `LOCAL_GID` in `.env` (obtain them with `id -u` and `id -g`), or override the user for one command:

```sh
docker compose run --build --rm --user "$(id -u):$(id -g)" ephemeris --help
```

## Run offline Python tests

```sh
docker compose run --build --rm ephemeris-test
```

Tests cover the FastAPI HTTP contract and use the archived real NASA fixtures and 30-day reference bundle in the separate test target. No network calls are made by the test process.

Validate the shipped handoff bundle and regenerate the pointing report:

```sh
docker compose run --build --rm validate data/reference/validation-30d
docker compose run --build --rm report data/reference/validation-30d \
  --quickmap-results docs/validation/quickmap-results.json
```

`validate` checks schema, grid, provenance models, manifest hashes, and CSV/JSON consistency. `report` uses an optional Matplotlib image. The report service mounts validation evidence read-only and writes its figures into the run directory. The ephemeris service uses a shared lock directory on the data mount to serialize cooperating request processes.

## Use images directly

Both images can be built without Compose. They build for the host's architecture; neither Dockerfile forces Intel or ARM.

```sh
docker build -t lunarwindow-web:local .
docker run --rm -p 127.0.0.1:3000:3000 lunarwindow-web:local

docker build -f backend/Dockerfile --target ephemeris -t lunarwindow-ephemeris:local .
docker run --rm lunarwindow-ephemeris:local --help
```

For direct-image exports, bind-mount your data directory at `/app/data` to retain outputs. Compose already configures that mount. Images are built locally; this setup does not publish them to a registry.

## Updating and contributing

After pulling code changes, rerun `docker compose up --build -d --wait`. This is a production image, so source edits require rebuilding. For hot reloading, use the native `npm run dev` workflow.

Use commit subjects in the requested form: `feat:[description]`, `fix:[description]`, `docs:[description]`, `test:[description]`, or `chore:[description]`. Keep each commit focused on a reviewable change.

The Docker CI job builds the web, API, ephemeris, test, and analysis targets, runs offline HTTP/regression/handoff checks, regenerates the reference plot, and verifies both service health endpoints and the web page. It does not publish images or run a long NASA export.
