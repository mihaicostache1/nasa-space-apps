# Backend/data — task 1

The first P3 task in the team plan (hours 3–12) is **API skeleton with fake data**. This milestone provides a FastAPI service and the shared horizon/series contract so the frontend can build against HTTP. Real Horizons/LOLA integration, metrics, windows, caching, and precomputation belong to later tasks.

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

| Method | Route                  | Response                                                       |
| ------ | ---------------------- | -------------------------------------------------------------- |
| GET    | `/api/health`          | Backend process health and `dataMode: "synthetic"`             |
| GET    | `/api/sites`           | Three illustrative demo points, coordinates, and source labels |
| GET    | `/api/sites/{site_id}` | One demo point's horizon and time series                       |
| POST   | `/api/evaluations`     | Synthetic data for the existing frontend `Scenario` request    |

The site-data route accepts `startUtc`, `endUtc`, and `stepMinutes` query parameters. Defaults are 2026-11-14T00:00:00Z through 2026-12-14T00:00:00Z, at 60-minute steps. These fixed dates make demos reproducible. An unknown site returns HTTP 404.

```sh
curl http://localhost:8000/api/sites
curl 'http://localhost:8000/api/sites/demo-polar-a?startUtc=2026-11-14T00:00:00Z&endUtc=2026-11-15T00:00:00Z&stepMinutes=60'
curl http://localhost:8000/api/evaluations \
  -H 'Content-Type: application/json' \
  -d '{"name":"Scenario A","location":{"latitudeDeg":-89,"longitudeDeg":0,"altitudeKm":0},"startUtc":"2026-11-14T00:00:00Z","endUtc":"2026-11-15T00:00:00Z","stepMinutes":60}'
```

## Frontend contract

`POST /api/evaluations` accepts the fields already defined in `src/domain/scenario.ts`. Python validates latitude [-90, 90], east-positive longitude [-180, 180], finite altitude in kilometers above the reference surface, a nonblank name up to 80 characters, and integer steps from 1 to 1440 minutes. Times must be whole-minute ISO UTC strings ending in `Z`, from 1962 onward, consistent with the ephemeris package. End must follow start; requests are limited to 31 days and 10,000 samples. Extra JSON fields and numeric strings/booleans are rejected.

Responses use `lunarwindow.evaluation.v1`, with matching TypeScript types in `src/domain/evaluation.ts`:

- `siteId`, `site`, `lat`, `lon`, `altitudeKm`, `coordinateSource`: echo the chosen demo point or custom scenario. Custom scenarios use `siteId: "custom"`; no scenario is saved.
- `dataMode: "synthetic"`: always present on evaluation and catalog responses.
- `horizon`: exactly 360 `{ az, el }` entries, ordered from azimuth 0 through 359 degrees, clockwise from north.
- `series`: UTC `t`, `sunAz`, `sunEl`, `earthAz`, `earthEl`, `sunAngularRadiusDeg`, `earthAngularRadiusDeg`, `sunLit`, and `earthVis`. Start is included, end is excluded. A nonaligned end still includes every on-grid sample before end.
- `metrics`: `pctSun`, `pctEarth`, `pctBoth`, `longestDarkHrs`, `nextSunset`, and `nextEarthset` are all `null` until task 2. Display an unavailable state for these fields.
- `provenance`: the generator name, requested period, UTC/end conventions, synthetic model labels, and an explicit warning.

Values repeat for identical requests, and overlapping date ranges share identical samples. Longitude and latitude vary the demo curves; altitude is echoed but has no effect. Visibility flags compare the fake body center with the synthetic horizon's lower integer azimuth bin. Angular radii are illustrative constants. This is a UI fixture, not the final terrain or partial-disc visibility algorithm. It does not read the real ephemeris cache or reference bundles, and it does not represent power availability or a validated radio link.

The existing React workspace remains independent. A frontend integration can submit its scenario directly:

```ts
import type { EvaluationDataset } from '@/domain/evaluation';
import type { Scenario } from '@/domain/scenario';

async function evaluate(scenario: Scenario): Promise<EvaluationDataset> {
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

The HTTP tests cover the catalog, response contract, time grid, repeatability, bounds, malformed inputs, errors, CORS, and OpenAPI. `get_provider` in `lunarwindow.api.app` is the dependency boundary for later real-data integration; the demo generator is never a fallback for failed NASA requests.
