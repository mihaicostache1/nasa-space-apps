# Backend deployment readiness

The API exposes separate process and data checks:

| Route             | Success                | Checks                                                                                                                                               |
| ----------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/health` | 200, `status: "ok"`    | The process can answer HTTP. Its existing synthetic-demo contract is unchanged.                                                                      |
| `GET /api/ready`  | 200, `status: "ready"` | The reference archive, all registered terrain masks and their observer/frame compatibility, and the complete configured precomputed bundle validate. |

Readiness returns `schemaVersion: "lunarwindow.readiness.v1"`, `dataMode: "reference"`, site/mask counts, `precomputed: "verified"` or `"disabled"`, a saved-job count, and the process's configured cache limits. The shipped Docker release reports three sites, one reviewed mask, and four jobs. Native startup leaves saved lookup disabled unless `LUNARWINDOW_PRECOMPUTED_DIR` is exported.

Every readiness request checks the files again. It does not calculate visibility, populate the result cache, download data, or accept a terrain approximation for an evaluation caller. Missing, changed, incompatible, or invalid configured data returns the existing generic HTTP 503 error envelope without exposing filesystem paths. `/api/health` remains available while data is unready. The catalog and individual geometric evaluations retain their existing validation behavior.

The Docker API health check calls `/api/ready`; Compose waits for that check before starting the web service. `docker compose up --build -d --wait` therefore verifies data readiness as well as HTTP startup. The probe allows 14 seconds inside a 15-second Docker timeout, accommodating the observed validation latency under load; three failed checks mark the container unhealthy. After startup, an unhealthy status is visible to operators; Compose's restart policy restarts an exited process, not a merely unhealthy one.

## Resource settings

Export these variables for native startup, or set them in `.env` for Compose:

| Variable                        | Default    | Meaning                                                        |
| ------------------------------- | ---------- | -------------------------------------------------------------- |
| `LUNARWINDOW_CACHE_MAX_ENTRIES` | `32`       | Maximum retained reference response snapshots per API process. |
| `LUNARWINDOW_CACHE_MAX_BYTES`   | `16777216` | Maximum retained serialized response bytes per API process.    |

Cache values must be non-negative integers. Setting either to zero disables storage; blank, negative, and non-integer values fail application startup with the setting's name. The byte cap excludes object overhead, source loading, parsing, and temporary calculation buffers. It is not a total process-memory limit. Multiple worker processes have separate caches and multiply memory use.

Compose additionally configures:

| Variable                             | Default | Meaning                                                             |
| ------------------------------------ | ------- | ------------------------------------------------------------------- |
| `LUNARWINDOW_API_MEMORY_LIMIT`       | `1g`    | Container memory limit, using Docker's memory syntax.               |
| `LUNARWINDOW_API_CPUS`               | `2.0`   | Container CPU quota.                                                |
| `LUNARWINDOW_API_MAX_CONCURRENCY`    | `16`    | Uvicorn connection/task limit; excess concurrency returns HTTP 503. |
| `LUNARWINDOW_API_KEEP_ALIVE_SECONDS` | `5`     | Idle HTTP keep-alive timeout.                                       |

The API image also defaults to Uvicorn concurrency 16 and keep-alive 5 seconds when used directly. These two settings use Uvicorn's `UVICORN_LIMIT_CONCURRENCY` and `UVICORN_TIMEOUT_KEEP_ALIVE` environment variables internally; use those names when starting Uvicorn outside Compose. The image runs one worker. Existing request limits remain 31 days and 10,000 samples. See [the reproducible load test](backend-load-test.md) for measurements and the limits of the initial demo resource settings.

## Failure diagnostics

Reference validation failures emit a warning through the existing `uvicorn.error` logger:

```text
reference_data_unavailable operation=evaluation siteId=lola-site01-reference reason=...
```

The operation is `readiness`, `catalog`, `ephemeris`, or `evaluation`. The server log includes the underlying validation reason, including local paths when relevant; the public 503 remains generic. Ordinary 404/422 request errors do not emit this warning. Inspect failures with `docker compose logs api` and compare deployed paths and checksums with the [data-release instructions](data-releases.md).

## Deployed browser rehearsal

CI starts the production web/API images and runs `scripts/check_deployed_app.mjs` in Chromium. It checks that both default scenarios request the real API, receive reference results and the correct CORS header, and show results. It then changes the visibility rule, checks the stale-result message, submits the comparison, and checks the updated result. Browser-side fetches verify readiness and an unavailable-date 422 response. Uncaught browser exceptions fail the rehearsal.

Playwright is installed in temporary CI storage; it is not an application dependency. To repeat against an already running deployment:

```sh
npm install --prefix /tmp/lunarwindow-browser --no-audit --no-fund playwright@1.65.1
/tmp/lunarwindow-browser/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/lunarwindow-browser/node_modules \
  LUNARWINDOW_WEB_URL=http://localhost:3000 \
  LUNARWINDOW_API_URL=http://localhost:8000 \
  node scripts/check_deployed_app.mjs
```

On a minimal Linux machine, browser installation may also require `playwright install --with-deps chromium`. The browser-visible API address is compiled into the web image. Rebuild that image when changing it, and include the web origin in `LUNARWINDOW_CORS_ORIGINS`.

This rehearsal covers the current geometric frontend. Terrain backend regression tests and the packaged API check cover the reviewed Site01 mask separately. Data readiness verifies the supported contracts and provenance; it does not add independent scientific validation. The DE421/DE441 frame approximation, 0 m mast sensitivity, sample timing, disc model, and coverage limits remain documented in [terrain regression evidence](validation/terrain-regression.md) and [the data release](data-releases.md).
