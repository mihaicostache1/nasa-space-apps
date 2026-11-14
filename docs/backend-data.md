# Backend/data — tasks 1 and 2

The FastAPI backend provides synthetic scenario demos and geometric evaluations of verified archived NASA ephemerides. The reference-data integration includes a validated loader, site catalog, date-range selection, request/response contracts, and the calculation-engine adapter. Terrain-mask integration, caching, and extended precomputation remain later tasks. See [the calculation model and migration details](visibility.md).

The [terrain-mask v1 handoff contract](terrain-mask.md) now defines validated observer coordinates/heights, reference frames, complete horizon profiles, and DEM/algorithm provenance. It is independent of the HTTP API; loading verified masks and using them for terrain-aware evaluations are subsequent tasks.

## Run

From the repository root, with Python 3.11+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'
python -m uvicorn lunarwindow.api.app:app --reload --port 8000
```

Or start just the API with Docker:

```sh
docker compose up --build -d --wait api
```

Interactive documentation: [localhost:8000/docs](http://localhost:8000/docs). OpenAPI schema: [localhost:8000/openapi.json](http://localhost:8000/openapi.json). No API keys, downloads, or database are needed after installing dependencies.

## Routes

| Method | Route                                      | Response                                                          |
| ------ | ------------------------------------------ | ----------------------------------------------------------------- |
| GET    | `/api/health`                              | Backend process health and `dataMode: "synthetic"`                |
| GET    | `/api/sites`                               | Three illustrative demo points, coordinates, and source labels    |
| GET    | `/api/sites/{site_id}`                     | One demo point's horizon and time series                          |
| POST   | `/api/evaluations`                         | Synthetic data for the existing frontend `Scenario` request       |
| POST   | `/api/reference/evaluations`               | Geometric visibility, metrics, and windows from verified archives |
| GET    | `/api/reference/sites`                     | Verified reference coordinates and archive availability           |
| GET    | `/api/reference/sites/{site_id}/ephemeris` | Verified archived Sun/Earth samples and original provenance       |

The site-data route accepts `startUtc`, `endUtc`, `stepMinutes`, `visibilityRule`, and `asOfUtc` query parameters. Defaults are 2026-11-14T00:00:00Z through 2026-12-14T00:00:00Z, at 60-minute steps, with `any-disc` visibility and countdowns relative to the range start. These fixed dates make demos reproducible. An unknown site returns HTTP 404.

```sh
curl http://localhost:8000/api/sites
curl 'http://localhost:8000/api/sites/demo-polar-a?startUtc=2026-11-14T00:00:00Z&endUtc=2026-11-15T00:00:00Z&stepMinutes=60'
curl http://localhost:8000/api/evaluations \
  -H 'Content-Type: application/json' \
  -d '{"name":"Scenario A","location":{"latitudeDeg":-89,"longitudeDeg":0,"altitudeKm":0},"startUtc":"2026-11-14T00:00:00Z","endUtc":"2026-12-14T00:00:00Z","stepMinutes":60,"visibilityRule":"any-disc","asOfUtc":"2026-11-14T12:00:00Z"}'
```

## Reference site catalog

```sh
curl http://localhost:8000/api/reference/sites
```

The response declares `schemaVersion: "lunarwindow.reference-catalog.v1"`, provider `NASA/JPL Horizons`, UTC time, and east-positive longitude. Each entry in `sites` contains `id`, `name`, `lat`, `lon`, `altitudeKm`, the original `coordinateSource`, and `availability` with `startUtc`, `endUtc`, `endExclusive`, `stepMinutes`, and `sampleCount`.

The catalog is derived from the complete verified bundle. Currently it lists three LOLA DEM reference points, each with 720 hourly samples covering 2026-11-14T00:00:00Z through 2026-12-14T00:00:00Z (end excluded). Their source descriptions identify them as reference points rather than selected landing targets. Missing, corrupted, or invalid source data returns a structured HTTP 503; no partial catalog is published. The endpoint performs no downloads or writes.

Use an entry's `id` with the reference ephemeris endpoint below. Availability describes the full archive and its native sampling interval; optional selections do not change the catalog. The OpenAPI documentation includes the catalog's typed response schema.

## Read one verified reference dataset

```sh
curl http://localhost:8000/api/reference/sites/lola-site01-reference/ephemeris
```

Without query parameters, this endpoint returns the selected site's original `lunarwindow.ephemeris.v2` dataset unchanged: all 720 hourly samples from 2026-11-14 through 2026-12-14 UTC (end excluded), angular radii, coordinates, and NASA/JPL provenance. It validates the complete reference bundle first. The response matches `EphemerisDataset` in `src/domain/ephemeris.ts` and contains no terrain, visibility flags, or metrics.

Optional query parameters select a contained range and sampling interval:

```sh
curl 'http://localhost:8000/api/reference/sites/lola-site01-reference/ephemeris?startUtc=2026-11-15T00:00:00Z&endUtc=2026-11-16T00:00:00Z&stepMinutes=120'
```

This returns 12 existing samples, starting at 00:00 and ending at 22:00 on November 15. `startUtc` is inclusive and must lie on the archive's sampling grid. `endUtc` is exclusive and may fall between samples; the returned timestamps still stay strictly before it. Both bounds must be whole-minute UTC strings ending in `Z` and remain within archive coverage. Omitted bounds default independently to the archive's start/end.

`stepMinutes` defaults to the archive interval (currently 60 minutes). Supported values are positive whole-number multiples of that interval, up to 1440 minutes. A larger step selects every corresponding archived sample, anchored at the requested start; it does not interpolate. Requests for unavailable dates, off-grid starts, invalid UTC times, empty/reversed ranges, or unsupported intervals return structured HTTP 422 errors. No bounds are silently clipped and no missing samples are filled.

Filtered responses retain the `lunarwindow.ephemeris.v2` contract. Their `provenance.startUtc`, `endUtc`, and `stepMinutes` describe the returned grid. All original NASA request URLs, response hashes, retrieval times, model headers, coordinates, and angular values are preserved. The source archive is unchanged; use the catalog or unfiltered endpoint for its full coverage. The reusable `select_reference_dataset` helper also validates its selected output against the existing ephemeris contract.

Unknown sites return a structured HTTP 404. Missing or invalid bundle data returns a structured HTTP 503 with no synthetic fallback or filesystem paths in the response. Availability is checked when the reference endpoint is called; the existing demo routes remain independent.

Native startup from the repository root reads `data/reference/validation-30d`. Set the process environment variable `LUNARWINDOW_REFERENCE_DIR` to another reference-root directory containing `validation-30d` if needed. The Docker API image includes the committed bundle at `/app/data/reference/validation-30d`; no downloads or bind mounts are required.

## Evaluate a verified reference site

`POST /api/reference/evaluations` validates the complete reference bundle, selects the requested site's archived samples, and runs the visibility engine against a flat zero-degree horizon. The adapter is in `backend/src/lunarwindow/api/reference_provider.py`; request/response models are in `reference_models.py`, with matching TypeScript types in `src/domain/evaluation.ts`. The operation performs no downloads or writes.

`ReferenceEvaluationRequest` selects a catalog entry by `siteId` and requires an explicit `horizonMode: "geometric"`, plus `startUtc` and `endUtc`. Optional fields are `stepMinutes` (default 60), `visibilityRule` (default `any-disc`), and `asOfUtc` (default to the selected start during calculation). It uses the existing UTC, range-length, sample-count, countdown-reference, and archive-grid validation. Custom coordinates and unsupported horizon modes are rejected.

```json
{
  "siteId": "lola-site01-reference",
  "horizonMode": "geometric",
  "startUtc": "2026-11-15T00:00:00Z",
  "endUtc": "2026-11-16T00:00:00Z",
  "stepMinutes": 60,
  "visibilityRule": "any-disc"
}
```

Submit this JSON body to `POST /api/reference/evaluations` with `Content-Type: application/json`, or use [the interactive API documentation](http://localhost:8000/docs). Invalid requests, unavailable dates, and unsupported steps return structured HTTP 422 body errors. Unknown site IDs return HTTP 404. Missing or invalid archive data returns HTTP 503; it is never replaced with synthetic data.

The `ReferenceEvaluation` response declares `schemaVersion: "lunarwindow.reference-evaluation.v1"`, `dataMode: "reference"`, and `horizonMode: "geometric"`. It includes the source site's identity/coordinates, a 360-point zero-degree horizon, augmented Sun/Earth samples, metrics, windows, and calculation details using the existing visibility models. A geometric horizon must have ordered azimuths 0..359 and zero elevation in both the mask and the sample horizon fields.

`provenance.ephemeris` retains the selected dataset's complete P1 provenance, including the original NASA request URLs, response hashes, retrieval times, model headers, and coordinate/time conventions. Its period and step describe the selected samples. `provenance.archive` records the original archive's start/end, end-exclusive convention, native step, and sample count. The response also supplies a model-limitation message explaining the flat horizon and the absence of terrain, eclipse, electrical-power, and radio-link models.

Contract validation reuses the P1 provenance schema and dataset checks, including observer-coordinate consistency and the selected sampling grid. It also checks archive coverage/counts, archive/selection grid alignment, calculation step, countdown reference, and evaluated duration. The loader verifies source checksums before the adapter calls the engine. The models validate contract coherence without fetching data or computing visibility. Their schemas are published in OpenAPI, and can also be obtained with `ReferenceEvaluationRequest.model_json_schema()` and `ReferenceEvaluation.model_json_schema()`.

## Synthetic scenario evaluation contract

`POST /api/evaluations` accepts the fields already defined in `src/domain/scenario.ts`. Python validates latitude [-90, 90], east-positive longitude [-180, 180], finite altitude in kilometers above the reference surface, a nonblank name up to 80 characters, and integer steps from 1 to 1440 minutes. Times must be whole-minute ISO UTC strings ending in `Z`, from 1962 onward, consistent with the ephemeris package. End must follow start; requests are limited to 31 days and 10,000 samples. Extra JSON fields and numeric strings/booleans are rejected.

Existing frontend `Scenario` request bodies remain valid. The optional `visibilityRule` is `any-disc` (default), `body-center`, or `full-disc`. The optional `asOfUtc` is a whole-minute UTC timestamp within `[startUtc, endUtc)`, defaulting to the start, and affects only countdowns. These calculation options are included in the TypeScript `EvaluationRequest` type.

Responses use `lunarwindow.evaluation.v2`, with matching TypeScript types in `src/domain/evaluation.ts`:

- `siteId`, `site`, `lat`, `lon`, `altitudeKm`, `coordinateSource`: echo the chosen demo point or custom scenario. Custom scenarios use `siteId: "custom"`; no scenario is saved.
- `dataMode: "synthetic"`: always present on evaluation and catalog responses.
- `horizon`: exactly 360 `{ az, el }` entries, ordered from azimuth 0 through 359 degrees, clockwise from north.
- `series`: UTC `t`, the existing Sun/Earth angles and angular radii, interpolated `sunHorizonEl`/`earthHorizonEl`, `hidden`/`partial`/`full` disc states, and flags `sunLit`/`earthVis` following the chosen rule. Start is included, end is excluded. A nonaligned end still includes every on-grid sample before end.
- `metrics`: duration-weighted `pctSun`, `pctEarth`, `pctBoth`, visibility hours, longest darkness/Earth-blackout/combined intervals, selected-time countdowns, and next-setting observation brackets. Durations and percentages are numbers; event-related values are null if no qualifying transition is observed in the range.
- `windows`: merged `sunlit`, `earthVisible`, `both`, `darkness`, and `earthBlackout` intervals, with durations and flags indicating unknown extents outside the requested range.
- `calculation`: the selected visibility rule, circular linear horizon interpolation, local horizontal-disc approximation, sample-and-hold time model, event bracketing, and sampling step.
- `provenance`: the generator name, requested period, UTC/end conventions, synthetic model labels, and an explicit warning.

Values repeat for identical requests, and overlapping date ranges share identical samples. Longitude and latitude vary the demo curves; altitude is echoed but has no effect. Angular radii are illustrative constants in the demo provider; the calculation engine accepts each sample's supplied radius. The engine computes metrics and partial-disc states, while the demo source remains synthetic. It does not read the real ephemeris cache or reference bundles, and it does not represent power availability or a validated radio link. Read [the visibility model](visibility.md) before interpreting sampling precision or partial visibility.

The React workspace now uses the reference endpoints (`src/lib/api-client.ts`). A synthetic-scenario client would look like this:

```ts
import type { EvaluationDataset, EvaluationRequest } from '@/domain/evaluation';

async function evaluate(
  scenario: EvaluationRequest,
): Promise<EvaluationDataset> {
  const response = await fetch('http://localhost:8000/api/evaluations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scenario),
  });
  if (!response.ok) throw new Error('Evaluation failed');
  return response.json();
}
```

The backend allows browser origins `http://localhost:3000` and `http://127.0.0.1:3000` by default. Set `LUNARWINDOW_CORS_ORIGINS` to a comma-separated list for another frontend origin, including when `WEB_PORT` changes. `API_PORT` changes the Docker host port; native startup uses Uvicorn's `--port` argument.

## Errors and checks

Invalid requests return HTTP 422 with a stable envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Invalid request. Check the listed fields.",
    "details": [
      {
        "location": ["body", "location", "latitudeDeg"],
        "message": "Input should be greater than or equal to -90",
        "type": "greater_than_equal"
      }
    ]
  }
}
```

404s use the same envelope with `code: "not_found"`. `/api/health` describes the FastAPI process; the Next.js `/api/health` on port 3000 remains a separate frontend health check.

```sh
python -m unittest discover -s backend/tests -v
python -m ruff check backend scripts
python -m ruff format --check backend scripts
# Container equivalent, including the existing ephemeris regression tests:
docker compose run --build --rm ephemeris-test
```

The tests cover analytical visibility/metrics cases, the catalog, response contract, time grid, repeatability, calculation options, bounds, malformed inputs, errors, CORS, and OpenAPI. `get_provider` in `lunarwindow.api.app` is the dependency boundary for later real-data integration; the demo generator is never a fallback for failed NASA requests.
