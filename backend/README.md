# LunarWindow backend and ephemeris tools

Backend/data task 1 adds a FastAPI skeleton serving synthetic horizon/series data. Run `python -m uvicorn lunarwindow.api.app:app --reload --port 8000` after installation, or `docker compose up --build -d --wait api` from the repo root. Open [localhost:8000/docs](http://localhost:8000/docs). See the [backend API work package](../docs/backend-data.md) for routes, requests, frontend response types, and the limits of the fake data. The real ephemeris tools below remain separate from the demo API.

P1 supplies traceable Sun/Earth pointing data to the team's Python/FastAPI backend. Python 3.11+ is supported. The package uses JSON Schema for the handoff contract; plotting and GIS acquisition are optional extras. The React UI is not yet connected to the Python pipeline.

## Start with Docker

From the repository root, with Docker running:

```sh
docker compose run --build --rm ephemeris \
  --sites data/sites.example.json \
  --start 2026-11-14T00:00:00Z --end 2026-11-15T00:00:00Z
```

The command prints the completed run directory. Exports are now written under `data/processed/ephemeris/<run-id>/`; each run contains one JSON/CSV pair per site and a `manifest.json` with hashes. Previous runs are preserved. The final directory appears only after every site passes validation. Consumers must use complete manifests rather than scanning individual files or hidden staging directories.

The default site is illustrative. Sourced NASA DEM reference points are available in `data/reference/sites.nasa.json`; they are reference grid cells, not team-approved landing coordinates.

```sh
docker compose run --build --rm validate data/reference/validation-30d
docker compose run --build --rm ephemeris-test
docker compose run --build --rm report data/reference/validation-30d \
  --quickmap-results docs/validation/quickmap-results.json
```

See [Docker setup](../docs/docker.md) for file ownership and native-image commands.

## Native setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev,analysis]'
lunarwindow-ephemeris --sites data/reference/sites.nasa.json \
  --start 2026-11-14T00:00:00Z --end 2026-12-14T00:00:00Z
lunarwindow-validate data/reference/validation-30d
python -m unittest discover -s backend/tests -v
python scripts/validate_quickmap.py
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Ruff is included in the `dev` extra; Matplotlib is in `analysis`; `gis` adds Rasterio for `scripts/prepare_reference_sites.py`.

## Contract v2

The packaged [JSON Schema](src/lunarwindow/ephemeris/ephemeris.schema.json) is accompanied by semantic validation in `contract.py`; matching TypeScript types live in `src/domain/ephemeris.ts`.

| Field                                          | Meaning                                                                               |
| ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| `t`                                            | UTC sample time; start included, end excluded                                         |
| `sunAz`, `earthAz`                             | Degrees clockwise from local north, normalized to [0, 360)                            |
| `sunEl`, `earthEl`                             | Apparent body-center elevation above the local horizontal plane                       |
| `sunAngularRadiusDeg`, `earthAngularRadiusDeg` | Equatorial angular radius in degrees, from Horizons diameter in arcseconds / 7200     |
| `altitudeKm`                                   | Observer altitude above the declared lunar reference surface, not mast height alone   |
| `provenance`                                   | Original request URLs, retrieval times, hashes, actual model headers, and conventions |

`schemaVersion` is now `lunarwindow.ephemeris.v2`: v1 consumers must migrate to the two required body-size fields and the declared quantities/model metadata. Field names for the original five time/angle columns are retained. A small real [sample dataset](tests/fixtures/dataset.json) is included. `validate_dataset` rejects schema errors, off-grid timestamps, wrong counts, missing targets, mixed reference models, and inconsistent observer coordinates. `verify_run` also checks JSON/CSV equivalence and manifest hashes.

```python
import json
from pathlib import Path
from lunarwindow.ephemeris.contract import validate_dataset, verify_run

run = Path("data/reference/validation-30d")
manifest = verify_run(run)
for item in manifest["datasets"]:
    dataset = validate_dataset(json.loads((run / item["json"]).read_text()))
    # Backend/data now joins its GIS mask and computes visibility/windows.
```

The producer is importable via `HorizonsClient`, `Site`, `TimeRange`, and `export_run`. Calls perform blocking I/O; use a worker when integrating with an async service. Backend/data owns terrain masks, body-disc visibility rules, eclipses, power/radio models, metrics, and API routes. The angular sizes support that handoff; they do not implement those models.

## Requests, caching, and concurrency

Requests are sequential and chunked on the original sampling grid: at most 30 days / 744 intervals per query, with at most 200,000 samples per site. Known API signatures 1.2 and 1.3 are accepted; unexpected versions fail explicitly. The live archived endpoint reports 1.2; the documentation describes 1.3.

Requests carry a product/version/contact User-Agent. Transient errors retry at most three times; valid `Retry-After` values are honored. Delays above 60 seconds fail with a resume-later message rather than retrying earlier than requested. Failed or malformed responses are not cached. Valid caches retain their original retrieval timestamps and are checked against the complete request URL and response hash. `--refresh` replaces cached responses explicitly.

OS advisory locks release automatically on process exit. Native processes share a default lock directory in the system temporary directory; `--lock-dir` or `LUNARWINDOW_LOCK_DIR` selects another. All cooperating workers must use the same directory on a filesystem supporting advisory locks. Compose configures `/app/data/raw/.locks`, shared through the data mount. Separate machines should share the completed data bundle and use one precompute coordinator; a local file lock cannot coordinate unrelated hosts. Writes use unique temporary files and atomic replacement.

Failed batches publish no final run; successfully cached chunks can be reused on the next invocation. A hard process termination can leave a hidden `.incomplete-*` directory; it is not consumable and can be removed after confirming no job is using it.

## Scientific evidence

The committed bundle contains 30 days at three sourced LOLA DEM reference points, including sampled surface heights and original source-file checksums. A reproducible plot shows the local Earth/Sun pointing changes. Three QuickMap numerical camera-observer cases agree within the UI's 0.01-degree display rounding. The [validation report](../docs/validation/report.md) explains scope, evidence, and limits: this is cross-tool pointing consistency, not terrain-visibility certification or mission-site approval. The full 2026-2030 precompute remains unexecuted.
