# LunarWindow: Python ephemeris setup

This package is the Ephemeris lead's contribution. It runs independently of the frontend and can be imported by the Backend/data lead's future FastAPI application. Runtime dependencies are Python's standard library only. Python 3.11+ is required.

For a Docker-only setup, use `docker compose run --build --rm ephemeris --help` or follow [the Docker guide](../docs/docker.md). Native setup from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./backend

lunarwindow-ephemeris --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z --end 2026-11-15T00:00:00Z
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. All subsequent commands are the same.

Outputs:

- `data/processed/ephemeris/polar-example.json`: Sun/Earth series and provenance.
- `data/processed/ephemeris/polar-example.csv`: flat series for inspection.
- `data/raw/horizons/<request-hash>.json`: cached original NASA responses, request URLs, timestamps, and SHA-256 hashes.

The site in `data/sites.example.json` is explicitly illustrative. Obtain the verified catalog and altitude/reference-surface metadata from the Terrain/GIS lead before exporting named landing sites.

## Batch and precompute

The CLI processes every site in the input JSON array, one request at a time. Start is inclusive and end is exclusive: a 24-hour interval at a 60-minute step exports 24 rows. Requests are chunked on the sampling grid, with at most 30 days / 744 sample intervals per request. Aligned Horizons stop samples are removed at chunk boundaries.

Preview the team's proposed 2026-2030 hourly precompute without issuing requests:

```sh
lunarwindow-ephemeris --sites data/sites.example.json \
  --start 2026-01-01T00:00:00Z --end 2031-01-01T00:00:00Z --dry-run
```

There is a maximum of 200,000 samples per site per export. Existing valid cache entries are reused with their original retrieval timestamps. Use `--refresh` to retrieve them again. Failed exports can resume using completed request caches. Each successful site export replaces the previous JSON/CSV pair with that site ID in the chosen output directory; use `--output` to retain multiple runs.

This setup has been smoke-tested over three hours for one illustrative point. The full multi-site 2026-2030 precompute has not been run.

## Backend integration

```python
from pathlib import Path
from lunarwindow.ephemeris import HorizonsClient, Site, TimeRange

site = Site("verified-site-id", "Verified site name", -89.0, 0.0, 0.0,
            "Replace with verified coordinates, altitude, and source URL")
period = TimeRange("2026-11-14T00:00:00Z", "2026-11-15T00:00:00Z", 60)
dataset = HorizonsClient(Path("data/raw/horizons")).evaluate(site, period)
```

The numbers in this example are still illustrative. `evaluate` performs blocking I/O; run it in a worker/thread pool if calling it from an asynchronous FastAPI route. The CLI and client are designed for sequential jobs; do not share the same cache directory across concurrent writers without adding locking.

The export supplies the team's `site`, `lat`, `lon`, and `series` fields. Each series item has `t`, `sunAz`, `sunEl`, `earthAz`, `earthEl`. Backend/data joins the GIS horizon mask and computes `sunLit`, `earthVis`, and `metrics`; those fields are intentionally absent from the ephemeris-only export. Keep `altitudeKm`, `coordinateSource`, and `provenance` when combining files.

## Verification

```sh
python -m unittest discover -s backend/tests -v
```

Tests are offline and use the archived NASA response pair in `backend/tests/fixtures`. They cover invalid coordinates/times, sampling-grid boundaries, target/observer checks, unavailable angles, duplicate/missing timestamps, export shape, cache integrity, and cache reuse. No QuickMap validation is claimed by these tests.

See [your work package](../docs/ephemeris-lead.md), [libration notes](../docs/libration.md), and [QuickMap protocol](../docs/validation/quickmap.md).
