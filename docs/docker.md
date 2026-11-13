# Docker setup

Install Docker Desktop (Windows/macOS) or Docker Engine with the Compose v2 plugin (Linux), and start its engine. No local Node.js, npm, Python, or virtual environment is needed for container use. Run commands from the cloned repository root.

## Start the app

```sh
docker compose up --build -d --wait
```

Open [localhost:3000](http://localhost:3000). The first run downloads base images, installs dependencies, and creates a production build; later starts reuse the built image. To change the host port, set `WEB_PORT` in `.env`, for example `WEB_PORT=3100`. No `.env` file is required for the default setup.

```sh
docker compose ps
docker compose logs -f web
docker compose down
```

The web image uses Next.js standalone output, runs as a non-root user, includes static assets, and has an HTTP health check. Port binding is local to your computer. The current UI remains the scenario starter: Docker does not add the pending FastAPI API, terrain models, or UI/data integration.

## Run ephemeris exports

The ephemeris service is an on-demand Python command, not a long-running server. Compose starts it only when requested; the `tools` profile keeps it out of a normal web startup.

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z \
  --end 2026-11-15T00:00:00Z
```

JSON/CSV exports appear in your checkout under `data/processed/ephemeris/`; original NASA response caches appear under `data/raw/horizons/`. They persist when the command exits or containers are removed. The bind mount also makes your verified site catalog available inside the container. Live exports require internet access to NASA; no API key is needed.

Preview requests without using the network:

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-01-01T00:00:00Z \
  --end 2031-01-01T00:00:00Z --dry-run
```

The default site is illustrative. Replace it with GIS-verified inputs before generating named-site results. Existing per-site exports in the chosen output directory are replaced on a successful run.

The container uses UID/GID 1000 by default. Docker Desktop normally handles the host bind mount automatically. On Linux, if your checkout is owned by another UID/GID, put your numeric `LOCAL_UID` and `LOCAL_GID` in `.env` (obtain them with `id -u` and `id -g`), or override the user for one command:

```sh
docker compose run --build --rm --user "$(id -u):$(id -g)" ephemeris --help
```

## Run offline Python tests

```sh
docker compose run --build --rm ephemeris-test
```

Tests use the archived real NASA fixtures bundled into the separate test target. No network calls are made by the test process.

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

The Docker CI job builds both runtime images, runs the Python test image and CLI dry run, and verifies the web health endpoint and page. It does not publish images or run a long NASA export.
