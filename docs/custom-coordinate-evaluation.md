# Custom-coordinate evaluation

`POST /api/custom/evaluations` evaluates an exact lunar observer using the existing Horizons request builder, parser, and visibility engine. It returns the same metrics, operating windows, disc rules, and setting brackets used for reference evaluations, under the new `lunarwindow.custom-evaluation.v1` response schema.

Custom acquisition is **disabled by default**. Enable it explicitly when the API has outbound HTTPS access to NASA/JPL Horizons and writable archive storage. Existing reference and synthetic endpoints retain their contracts; reference evaluations continue using the shipped offline data. The frontend is unchanged: use the endpoint or FastAPI `/docs` to submit custom coordinates.

## Coordinates and observer height

`latitudeDeg` is in `[-90, 90]`; `longitudeDeg` is east-positive in `[-180, 180]`. `observerHeightM` is required and means metres **above the local ground**, from 0 through 1000. Ground elevation is measured above the 1737.4 km lunar reference sphere:

```text
Horizons altitudeKm = (surfaceElevationM + observerHeightM) / 1000
```

Geometric mode requires an explicit `surfaceElevationM`, from -20,000 through 20,000 m. The service cannot infer total observer altitude from antenna height alone without terrain data, so it does not silently assume zero elevation. This mode works independently of DEM files and GIS dependencies; the caller is responsible for the supplied ground elevation and coordinate frame.

Terrain mode derives ground elevation from the configured LOLA DEMs. If supplied, `surfaceElevationM` must agree with the DEM within 1 mm; it is not an override. The existing GIS profile stores surface elevation to 1 mm and total altitude to 1 mm, and the returned observer records the altitude sent to Horizons. That rounding does not imply physical accuracy at that precision.

Coordinates are not rounded to merge nearby observers. Longitude +180 is canonicalized to -180, signed zero to zero, and UTC times to their canonical spelling. Provider headers must declare the supported lunar Mean Earth orientation, airless positions, and 1737.4 km sphere. See the [Horizons API specification](https://ssd-api.jpl.nasa.gov/doc/horizons.html) and [Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html) for observer coordinate order and altitude units.

## Request examples

Geometric evaluation with explicitly supplied ground elevation:

```json
{
  "location": {
    "latitudeDeg": -89,
    "longitudeDeg": 0,
    "surfaceElevationM": 0,
    "observerHeightM": 2
  },
  "horizonMode": "geometric",
  "startUtc": "2026-11-14T00:00:00Z",
  "endUtc": "2026-11-15T00:00:00Z",
  "stepMinutes": 60,
  "visibilityRule": "any-disc"
}
```

The example's zero ground elevation is an explicit input, not a claim about terrain at that point. Geometric mode uses a flat zero-degree local horizon, consistent with reference geometric evaluations. It does not model terrain or the depressed bare-sphere horizon of an elevated observer.

Terrain evaluation derives ground height and requires explicit frame acceptance:

```json
{
  "location": {
    "latitudeDeg": -89,
    "longitudeDeg": 0,
    "observerHeightM": 2
  },
  "horizonMode": "terrain",
  "allowMeanEarthApproximation": true,
  "startUtc": "2026-11-14T00:00:00Z",
  "endUtc": "2026-11-15T00:00:00Z",
  "stepMinutes": 60,
  "visibilityRule": "any-disc"
}
```

Save either example as `request.json` and submit it with:

```sh
curl --fail-with-body http://localhost:8000/api/custom/evaluations \
  -H 'Content-Type: application/json' --data-binary @request.json
```

Both modes support `any-disc`, `body-center`, and `full-disc`. Optional `asOfUtc` selects a countdown reference within `[startUtc, endUtc)`; it defaults to the start. Dates must be whole-minute UTC strings ending in `Z`, within 2000–2039, and cover at most 31 days. `stepMinutes` is an integer from 1 through 1440. The custom runtime defaults to **744 samples per request**, in addition to the shared contract's 10,000-sample ceiling; shorten the range or increase the step when necessary.

Numeric strings, booleans used as numbers, nonfinite values, unknown fields, unsupported modes, and missing required values are rejected. Geometric requests cannot accept a terrain-frame approximation.

## Response and provenance

A successful response has `schemaVersion: "lunarwindow.custom-evaluation.v1"` and `dataMode: "custom"`. FastAPI `/openapi.json` describes every field; the table below describes the result without inventing example metrics.

| Field                                        | Content                                                                                                                                                  |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `siteId`, `site`                             | Stable ID derived from exact coordinates and total altitude; custom observer label                                                                       |
| `observer`                                   | Coordinates, ground elevation, mast height, total altitude, and coordinate/height source                                                                 |
| `horizonMode`, `allowMeanEarthApproximation` | Actual horizon policy and explicit frame acceptance                                                                                                      |
| `horizon`                                    | 360 ordered azimuth/elevation values; zero elevation in geometric mode                                                                                   |
| `series`                                     | Archived Horizons angles/body sizes and derived visibility fields                                                                                        |
| `metrics`, `windows`, `calculation`          | Existing engine contracts, including sampling, disc model, and bracketed event timing                                                                    |
| `provenance.ephemeris`                       | Request URLs, raw-response hashes, retrieval times, model/observer headers, and sampling grid                                                            |
| `provenance.ephemerisSha256`                 | SHA-256 of the canonical parsed dataset archived with the raw responses                                                                                  |
| `provenance.terrain`                         | `null` geometrically; otherwise complete generated `profile` and `mask`, `profileSha256`, `maskSha256`, compatibility, and `reviewStatus: "preliminary"` |
| `provenance.warning`                         | Scientific limitations of the evaluated mode                                                                                                             |

Custom terrain uses the existing spherical ray caster over the **20 m near-field and 120 m far-field** LOLA DEMs, with 3600 rays, conservative whole-degree max-binning, and a 200 km search. Sampling starts 60 m away and follows the existing variable-distance steps. Every required sample must have DEM data: holes or truncated rays reject the evaluation. Locations outside the supported 60–90°S region reject explicitly, and points within that region can still fail complete ray coverage. There is no fallback to another point or a flat terrain horizon.

The actual DEM bytes, download provenance, product identity, resolution, and projection are checked before terrain cache reuse. Generated masks retain source hashes, CRS, retrieval evidence, generation timestamp, and algorithm/version. Full DEM rehashing can consume a substantial part of the request budget.

The mask declares DE421 MOON_ME. The backend supports the existing `mean-earth-reference-v1` approximation when pairing it with the supported Horizons Mean Earth orientation; **no frame transformation is applied**. Explicit acceptance does not establish exact frame equivalence. Generated terrain is preliminary and does not inherit the GIS review status of the Site01 reference mask. Adding reviewed Site04/Site23 masks remains a separate [handoff task](terrain-coverage.md).

Terrain within 60 m is excluded, DEM pixels miss smaller obstacles, and sample-and-hold timing and the horizontal-disc model remain approximations. Eclipses, electrical power, radio-link budgets, landing safety, and mission accuracy are not modeled.

## Verified geometric response excerpt

A live smoke test requested three hourly samples for `2026-11-14T00:00:00Z` through `2026-11-14T03:00:00Z`, at latitude -89 degrees, longitude 0 degrees, explicitly supplied ground elevation 0 m, and observer height 2 m. It returned the following **excerpt**, and an identical repeated evaluation reused the verified archive. The full response also includes the observer source, horizon, series, windows, calculation metadata, and complete provenance described above. This verifies acquisition and integration; it does not verify that the supplied ground elevation describes the actual lunar terrain.

```json
{
  "schemaVersion": "lunarwindow.custom-evaluation.v1",
  "dataMode": "custom",
  "horizonMode": "geometric",
  "metrics": {
    "evaluatedHrs": 3,
    "pctSun": 100,
    "pctEarth": 0
  },
  "provenance": {
    "ephemerisSha256": "ec36ac6559ac79d0485f836de2af2fd14abfa441213e0b90bab23b290278367d"
  }
}
```

## Archival, caching, and resource controls

Each successful acquisition atomically publishes one entry containing the exact observer/grid identity, original provider responses, parsed dataset, and checksums. Reuse validates the dataset and replays the raw responses through the real parser, requiring an identical result. Corrupted local data fails explicitly without a hidden network refresh; an operator can remove or move the bad entry to permit reacquisition. API requests cannot choose storage paths or upstream URLs.

Disk archives and generated terrain caches have count and byte limits. Acquisition archives evict the oldest entries; they are bounded working storage, not permanent evidence retention. Copy an analysis separately when it must be retained for a release or publication. Response snapshots use a separate immutable-byte LRU. Every response-cache lookup follows current source and policy checks. Observer, height, period, sampling, rule, as-of time, source hashes, algorithm/model versions, and approximation acceptance participate in cache identity.

Admission is bounded per process; excess custom work returns immediately without an unbounded queue. One cooperative deadline covers acquisition, locks, and computation checks. Custom Horizons calls use one attempt and an 8 MiB response limit, with remaining-time socket timeouts. Terrain checks the deadline around file blocks, GIS reads, and ray-casting chunks. This is not an OS-enforced deadline for a stalled filesystem or native GIS call; no timed-out background computation is launched. Multiple API workers have separate admission and memory-cache budgets, while shared archive file locks coordinate publication.

| Environment setting                      | Default                                       | Meaning                                                     |
| ---------------------------------------- | --------------------------------------------- | ----------------------------------------------------------- |
| `LUNARWINDOW_CUSTOM_ENABLED`             | `false`                                       | Enable live/custom acquisition                              |
| `LUNARWINDOW_CUSTOM_TERRAIN_ENABLED`     | `false`                                       | Enable custom DEM terrain; requires custom enabled          |
| `LUNARWINDOW_CUSTOM_ARCHIVE_DIR`         | `data/processed/custom-ephemeris`             | Writable provider archive                                   |
| `LUNARWINDOW_CUSTOM_DEM_DIR`             | `data/raw/lola`                               | Read-only source rasters and provenance                     |
| `LUNARWINDOW_CUSTOM_TERRAIN_CACHE_DIR`   | Sibling `custom-terrain` of archive directory | Writable generated terrain cache                            |
| `LUNARWINDOW_CUSTOM_MAX_CONCURRENCY`     | `1`                                           | Concurrent custom evaluations per process, configurable 1–4 |
| `LUNARWINDOW_CUSTOM_TIMEOUT_SECONDS`     | `30`                                          | Cooperative budget, configurable 1–120 seconds              |
| `LUNARWINDOW_CUSTOM_MAX_SAMPLES`         | `744`                                         | Per-request sample limit, configurable 1–744                |
| `LUNARWINDOW_CUSTOM_ARCHIVE_MAX_ENTRIES` | `64`                                          | Entry cap for each disk archive/cache                       |
| `LUNARWINDOW_CUSTOM_ARCHIVE_MAX_BYTES`   | `67108864`                                    | Byte cap for each disk archive/cache                        |
| `LUNARWINDOW_CUSTOM_CACHE_MAX_ENTRIES`   | `16`                                          | Response entry cap; zero disables storage                   |
| `LUNARWINDOW_CUSTOM_CACHE_MAX_BYTES`     | `16777216`                                    | Retained response bytes; zero disables storage              |

Boolean settings accept `true` or `false`. Invalid settings fail application creation with the setting name. Cache byte limits exclude parsing, terrain grids, and temporary computation buffers; container memory limits are separate. The existing reference-only load report does not characterize custom-coordinate performance.

## Local startup and deployment

Geometric native startup needs the ordinary backend dependencies and writable archive storage:

```sh
python -m pip install -e './backend[dev]'
LUNARWINDOW_CUSTOM_ENABLED=true python -m uvicorn lunarwindow.api.app:app --port 8000
```

For terrain, install `./backend[dev,gis]`, download the original 20 m/120 m rasters and their provenance using the [GIS workflow](terrain-gis-lead.md), and enable both custom flags. The source rasters occupy about 3.5 GB. Evaluation requests do not download DEMs; missing data or dependencies return an explicit error.

The optional Docker target `custom-api` includes GIS dependencies. The ordinary `api` target keeps the default API dependencies and opt-in policy. The supplied override enables both custom flags, mounts local DEMs read-only, and persists generated data in a named volume:

```sh
docker compose -f compose.yaml -f compose.custom.yaml up --build -d --wait api
```

The regular API resource limits apply; one expensive custom request runs at a time by default. Set `LUNARWINDOW_CORS_ORIGINS` for a browser client. The existing frontend needs separate UI work to submit arbitrary coordinates.

On a hosted service, build/select `custom-api` if terrain is needed, supply rasters/provenance through a read-only volume, and provide writable persistent archive/cache storage. These files are not bundled into the source checkout or default image. Keep custom terrain disabled on deployments without them. `/api/ready` continues to verify the reference release; it does not establish coverage for a custom terrain point.

## Errors and verification

Errors use the existing `{ "error": { "code", "message", "details" } }` envelope without local file paths or raw provider content.

| HTTP | Meaning                                                                                                        |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| 422  | Invalid input, sample limit, missing frame acceptance, unavailable terrain coverage, or ground-height mismatch |
| 502  | Horizons unavailable, invalid response, wrong observer, missing samples, or unsupported source model           |
| 503  | Custom disabled, busy (`Retry-After: 1`), terrain disabled/missing, or invalid local archive/cache             |
| 504  | Acquisition or cooperative computation budget exceeded                                                         |

Tests use real archived Horizons response fixtures, controlled upstream HTTP mocks, and explicitly synthetic DEMs/source changes. They exercise the real request builder, parser, archival/replay, engine, and HTTP path without NASA access. Terrain tests cover generation, complete/incomplete coverage, heights, corrupt sources/cache entries, and deadlines. Existing reference, cache, terrain, and release regressions remain active. The `custom-test` Docker target includes GIS extras for terrain tests; passing tests is not an independent scientific review of generated custom masks.

## Implementation inventory

Seven focused agents handled contracts, Horizons acquisition/archival, cache/limits, evaluation integration, terrain generation, HTTP/GIS regressions, and documentation. The main agent integrated routing and deployment, reviewed source consistency and limits, and ran the final checks.

- New API modules under `backend/src/lunarwindow/api/`: `custom_models.py`, `custom_provider.py`, `custom_routes.py`, `custom_runtime.py`, and shared `snapshot_cache.py`.
- New data/geometry modules: `backend/src/lunarwindow/ephemeris/custom.py`, `backend/src/lunarwindow/terrain/custom.py`, and `backend/src/lunarwindow/observer.py`.
- Existing backend wiring: `api/app.py` registers the opt-in endpoint/runtime; `api/reference_cache.py` delegates storage to the shared LRU without changing its public interface; `ephemeris/horizons.py` adds optional deadline/response limits while preserving CLI defaults; `terrain/horizon.py` adds an optional cooperative callback; `terrain/dem.py` closes Rasterio handles if constructor validation fails.
- New tests under `backend/tests/`: `test_custom_contract.py`, `test_custom_ephemeris.py`, `test_custom_evaluation.py`, `test_custom_gis.py`, `test_custom_integration.py`, `test_custom_runtime.py`, and `test_custom_terrain.py`.
- Deployment/configuration: `backend/Dockerfile`, `compose.yaml`, new `compose.custom.yaml`, `.env.example`, and `.github/workflows/ci.yml`. GIS targets install the required `libexpat1` system library and verify Rasterio imports during the build.
- Documentation: this guide and the README entry linking it.
