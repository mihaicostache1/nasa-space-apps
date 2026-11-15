# Packaged API load test

`scripts/load_test_api.py` measures real HTTP requests against the packaged API in a separate Docker container. It uses only Python 3.11+ standard-library modules on the host and the existing API dependencies inside the image. It does not change the running app, API contracts, or source data.

From the repository root, with Docker running:

```sh
docker build -f backend/Dockerfile --target api -t lunarwindow-api:load-test .
python scripts/load_test_api.py \
  --image lunarwindow-api:load-test \
  --output /tmp/lunarwindow-load-test.json
```

Use the Python executable from your activated project environment. The host default `python3` on some macOS installations is older than 3.11.

The default run sends 24 requests per phase at concurrency 1, 4, and 8, for both geometric and reviewed Site01 terrain evaluations. Each response covers the full 30-day archive with 720 hourly samples. All requests select Site01 so the two horizon modes use the same observer. Terrain retains its explicit frame-approximation acceptance and the 0 m reference mast.

## Three execution paths

| Path              | Request selection                                                          | Required measured behavior                                                             |
| ----------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Saved result      | Exact packaged full-month job, countdown at the range start                | Every successful request loads the saved result; no memory lookup or calculation.      |
| Memory hit        | Countdown moved one minute after the range start; one warmup before timing | Every measured success misses the saved bundle and hits memory; no calculation.        |
| Fresh calculation | A unique countdown minute for every request, starting at minute two        | Every success misses both saved and memory storage, calculates, and stores the result. |

Changing the countdown gives distinct validated cache keys without reducing the series or changing the observer. The cache is cleared before each path, not between its concurrency levels. Fresh phases therefore accumulate enough unique results to exercise bounded retention in the default full run. Warmup requests are excluded from the measured counts and latency. Disk caches and the API process are warm; this is not a cold-boot benchmark.

The test-only factory wraps the real loader, cache, and calculation functions to count calls. It does not skip source checks, change the numerical engine, or substitute responses. Unexpected paths fail the run. Successful responses are checked for mode, sample count, countdown, and terrain frame labeling. Control routes are token-protected, mounted only in the isolated test container, and absent from the normal API image startup.

## Measurements and checks

The JSON report includes:

- Successful requests per second, HTTP status counts, response bytes, and nearest-rank p50/p95/p99/maximum latency **separately for each status**. HTTP timing ends after reading the full body. There are no retries; timeouts and errors remain visible and fail normal phases.
- Execution-path counts and final cache entry/payload-byte counts. Cache limits are checked during sampling and after cache writes.
- API process RSS, whole-container cgroup memory, before/after values, sampled peaks, the kernel's lifetime cgroup peak, and cgroup OOM counters. Sampling runs nominally every 20 ms; CPU contention can delay it, so sampled peaks are lower bounds. Kernel lifetime peaks are not reset between phases.
- The immutable image ID, package/runtime versions, release checksums, and actual Docker memory/CPU settings. The load generator runs on the host and is excluded from API container memory and CPU quotas.

Defaults match the demo: 1 GiB container memory with swap disabled, two CPUs, a 32-entry/16 MiB payload cache, and the image's Uvicorn concurrency 16 and keep-alive five seconds. Use `--memory`, `--cpus`, `--requests`, `--concurrency`, `--timeout`, and `--horizon-modes` to repeat a different resource profile. Normal concurrency must remain below the image's rejection boundary. The test requires Linux cgroup v2 memory counters, as provided by the tested Docker Desktop and CI runner environments; missing counters fail the run.

By default, the harness disables periodic Docker health probes during measurement so their validation work does not contaminate individual path timings. It explicitly verifies readiness before and after load. Use `--with-healthcheck` for an operational rehearsal with the image's real periodic probes: normal phases must not become unhealthy, and recovery must include a new successful Docker health probe. The report retains per-phase Docker health status and probe logs. The server still executes all usual request/source/bundle/terrain validation. Instrumentation and host scheduling add overhead; these measurements describe this image and machine, not a general service-level guarantee.

For a longer readiness regression check at eight concurrent requests:

```sh
python scripts/load_test_api.py --image lunarwindow-api:load-test \
  --requests 32 --concurrency 8 --horizon-modes geometric \
  --with-healthcheck --output /tmp/lunarwindow-load-health.json
```

After normal phases, each horizon mode receives a burst at twice the configured concurrency limit. Expected Uvicorn 503 rejections are recorded separately from successful latency; JSON data-validation 503 responses fail the test. A second check holds partial HTTP headers on 16 real connections and requires a new request to be rejected. Closing those connections must restore data readiness. Ordinary phases must return only 200, cache bounds must hold, and OOM events or an exited API fail the run. The harness removes only its uniquely named container in `finally` and publishes an automatically selected loopback port.

Reports use `lunarwindow.api-load-test.v1`; exit status is zero on success, one on a failed run, and two on invalid command arguments. A failed run retains completed measurements and its error in the output file. Latencies are observations, without an arbitrary pass/fail threshold.

## CI smoke check

The Docker job runs a short version with two requests at concurrency 1 and 2, both horizon modes, both overload checks, periodic health probes, and the same resource settings. It uploads the JSON as `api-load-smoke`. This catches wrong execution paths, errors, resource-bound violations, and failed overload recovery. Its small sample size is not a performance baseline or a substitute for the longer readiness regression. The native Python matrix also tests the report logic to ensure fast rejections cannot hide slow successful requests or mislabeled cache paths.

```sh
python -m unittest discover -s scripts/tests -v
python scripts/load_test_api.py --image lunarwindow-api:load-test \
  --requests 2 --concurrency 1 2 --with-healthcheck --output /tmp/lunarwindow-load-smoke.json
```

Recorded full-run measurements and their interpretation are in [the load-test report](validation/backend-load-test.md).

Custom acquisition and generated terrain have a separate [custom load-test harness](custom-load-test.md), with local Horizons fixtures, actual GIS computation, admission and deadline recovery checks.
