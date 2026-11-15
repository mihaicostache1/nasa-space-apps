# Custom-coordinate API load tests

`scripts/load_test_custom.py` measures the custom HTTP endpoint in a disposable,
GIS-enabled Docker container. It does not change the running deployment or production
routes. The host needs Python 3.11+ standard-library modules and Docker.

```sh
docker build --target custom-test -f backend/Dockerfile -t lunarwindow-custom-test .
.venv/bin/python scripts/load_test_custom.py \
  --image lunarwindow-custom-test --profile full --requests 4 \
  --output /tmp/lunarwindow-custom-load-full.json
```

Use `python` instead of `.venv/bin/python` in an activated environment or CI.
Both `custom-test` and `custom-api` images support this harness; source Horizons
fixtures are mounted read-only from the checkout.

## Measured paths

| Path                   | Required work during measurement                                                                                                                                                                                                                                      |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `horizons-acquisition` | A unique observer per request, two local upstream HTTP calls, actual Horizons parsing, source archival, visibility calculation, and memory-cache insertion.                                                                                                           |
| `archive-reuse`        | Repeated requests for a warmed observer, archive verification/replay and memory hits; no upstream calls or visibility calculation.                                                                                                                                    |
| `terrain-generation`   | Unique observer heights, both source hashes, actual Rasterio/CRS/window reads, ray casting, mask generation/validation, visibility calculation and cache insertion. Exact terrain-observer ephemerides are prewarmed outside timing; there must be no upstream calls. |
| `terrain-reuse`        | Repeated warmed requests, both source hashes and archive verification, generated terrain reuse and memory hits; no ray casting, upstream calls, or visibility calculation.                                                                                            |

Requests cover three hourly samples from 2026-11-14 00:00 UTC to 03:00 UTC, with
latitude −89° and longitude 0°. Observer height changes create exact distinct
identities. Terrain and geometric archive identities retain their different
coordinate provenance. Warmup calls are excluded from timing and counters.

The report fails if any measured path performs different work, if normal requests
fail, if memory/disk cache bounds are exceeded, if monitoring fails, or if the
container encounters OOM conditions. Default runs use one admission slot, matching
the service default. To measure two slots and concurrency one/two:

```sh
.venv/bin/python scripts/load_test_custom.py --image lunarwindow-custom-test \
  --profile smoke --slots 2 --concurrency 1 2 --requests 4 \
  --output /tmp/lunarwindow-custom-load-concurrency.json
```

Normal concurrency must not exceed admission slots. Up to four requests per phase
keep the separately prewarmed terrain archives within the deliberately small
four-entry disk retention limit. The memory cache holds two entries / 1 MiB, and
each on-disk artifact store is capped at four entries / 16 MiB. Unique requests
exercise eviction when four requests are selected. No production limits change.

## Fixtures and interpretation

The fake upstream is a real loopback HTTP server inside the container. It serves
archived Sun/Earth angle fixtures with explicitly synthetic observer headers and
20 ms response delay. The adapter sends only the query to that loopback server;
it never opens the NASA URL. Production request construction, timeouts, parser,
observer matching, archive checks, and visibility calculation remain connected.
This measures acquisition processing with controlled local I/O, **not NASA latency**
or the scientific validity of angles at the altered observer heights.

Terrain uses two explicitly synthetic flat GeoTIFFs at the production 20 m and
120 m pixel resolutions and the checked lunar stereographic CRS. Each file is
hashed and its size is registered only inside the test factory. They are not
NASA DEMs or reviewed masks. The complete source hashes and actual parameters
are included in the report.

- `full` (default) uses production parameters: 3,600 rays, 200 km extent, 25 km
  near field, 60 m minimum distance, and the production variable sampling steps.
  Synthetic raster widths are 3,200 / 4,000 pixels, covering the required search.
- `smoke` uses 360 rays, 1 km extent and 0.5 km near field, with smaller rasters.
  It tests paths and limits quickly; its timings are not a production baseline.

Neither profile measures hashing of the original multi-gigabyte LOLA products,
terrain-dependent nodata failures, cold boot, or live upstream behavior. Production
GIS/native-call deadlines remain cooperative. Fixture setup, image startup and
warmups are outside measured phases; OS disk/page caches may already be warm.

## Metrics and recovery

JSON uses `lunarwindow.custom-load-test.v1` and includes:

- HTTP status counts, successful requests/second, response bytes, and nearest-rank
  p50/p95/p99/max latencies per status. Failed/rejected calls cannot make successful
  latency appear lower. Timing includes reading the complete response body.
- Independent counters and stage latencies for acquisition/archive verification,
  terrain preparation, source hashing, ray casting and visibility calculation.
  Stage timings nest and must not be added together; wrapper overhead is included.
- Process RSS, container cgroup v2 memory before/after, sampled peaks, kernel lifetime
  peak, OOM counters, cache occupancy and observed admission concurrency. Sampling
  runs nominally every 20 ms; sampled peaks are lower bounds. No invented zeros
  are used when cgroup metrics are unavailable.
- Immutable image ID, runtime/dependency versions, source fixture/harness hashes,
  declared fixture limitations, and Docker memory/CPU settings. The host load
  generator is outside the container budget. Defaults are 1 GiB, swap disabled,
  two CPUs, a 120-second custom budget and one process/worker.

After normal phases, the harness occupies every real custom admission slot behind
a test-only gate. Eight extra requests must immediately return structured
`503 custom_busy` errors and must start no acquisition or calculation. It then
releases the gate and requires the admitted work to succeed. The gate is outside
the calculation timer; admitted request latency here is not a performance measure.
Uvicorn is set to 32 connections so this test reaches custom admission rather than
accidentally testing transport-level rejection.

A final fresh request uses a one-second custom budget and a local upstream delayed
by 1.5 seconds. It must return `504 custom_upstream_timeout`, release admission,
and allow a following ordinary evaluation to succeed. Transport failures, other
503/504 causes, and leaked work fail the run. Periodic Docker health probes are
disabled to avoid adding reference-data validation to these custom measurements;
this harness does not replace the existing reference readiness rehearsal.

Control routes are token-protected, hidden from OpenAPI, and installed only by
the mounted test factory. A unique container and temporary data are removed on
completion or failure. Exit codes are 0 (passed), 1 (failed with retained report)
and 2 (invalid arguments). There is no arbitrary latency pass/fail threshold.

## CI

The Docker job runs a two-request `smoke` profile with the same admission, busy,
deadline and resource checks. Its JSON is uploaded as `custom-api-load-smoke` even
on failure. Native matrix tests validate report/path logic without GIS or Docker:

```sh
python -m unittest discover -s scripts/tests -v
```

Recorded measurements and their limits are in
[the custom load-test report](validation/custom-load-test.md).
