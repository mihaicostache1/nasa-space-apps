# Backend load-test results

The full run in [backend-load-test.json](backend-load-test.json) passed all path, HTTP, cache-bound, OOM, and overload-recovery checks. All **432 normal-load requests returned 200**. The 64 additional burst requests produced 27 successes and 37 expected Uvicorn 503 rejections. A separate connection-cap probe also returned 503 and recovered to readiness after its connections closed.

The command was:

```sh
python scripts/load_test_api.py --image lunarwindow-api:deployment-check \
  --output docs/validation/backend-load-test.json
```

This measured the packaged single-worker Python 3.14 API on Linux ARM64 in Docker Desktop on macOS, with two CPUs, a 1 GiB memory cap and swap disabled, concurrency limit 16, and a five-second keep-alive timeout. The JSON records the image ID, package versions, release checksums, request settings, and counters. Each normal phase had 24 requests; Site01 geometric and reviewed terrain requests covered 720 hourly samples over the full reference month. The run spans an interrupted session; use its per-phase monotonic timings rather than the overall start timestamp as a duration. See [the procedure and measurement limits](../backend-load-test.md).

## Response times

Measured p95 latency in seconds, separated by path and normal client concurrency:

| Horizon   | Path   | 1 concurrent | 4 concurrent | 8 concurrent |
| --------- | ------ | -----------: | -----------: | -----------: |
| Geometric | Saved  |        0.715 |        2.849 |        5.504 |
| Geometric | Memory |        0.797 |        4.884 |        5.871 |
| Geometric | Fresh  |        0.743 |        2.951 |        6.063 |
| Terrain   | Saved  |        0.814 |        3.219 |        6.377 |
| Terrain   | Memory |        0.891 |        3.436 |        6.992 |
| Terrain   | Fresh  |        0.849 |        3.682 |        7.009 |

Throughput stayed around 1.19–1.52 successful requests/second across normal phases. Extra concurrency increased waiting time rather than increasing throughput substantially. The burst's accepted requests reached p95 8.254 seconds for geometric and 11.346 seconds for terrain; fast rejections are kept out of those percentiles.

Saved and memory hits still perform full source and configured-bundle validation. Their latency being close to fresh calculation is consistent with that repeated work dominating this workload; this is an inference from timings and path counts, not a CPU profile. Cache hits are verified by call counters rather than inferred from response speed. Increasing cache size alone has no demonstrated latency benefit here.

## Memory and retained cache

- Highest sampled API RSS: **166.6 MiB**, including overload bursts.
- Highest kernel-recorded lifetime cgroup memory: **159.5 MiB** against the 1024 MiB cap.
- No recorded OOM events, OOM kills, transport failures, or sampled cache-bound violations.
- Both fresh-workload runs generated 72 distinct successful calculations. Retention stopped at **32 entries**, demonstrating eviction under the default entry cap.
- Final retained serialized payloads were **7,836,558 bytes** for geometric and **9,032,452 bytes** for terrain, each below the 16,777,216-byte budget. The entry cap bound this dataset before the byte cap; this run does not demonstrate eviction caused by a saturated byte budget. Existing cache unit tests cover that behavior.

Process RSS and cgroup accounting count shared pages differently and are not interchangeable; cgroup memory is the container-limit measure. Sampled RSS can miss short peaks, and later phases inherit allocations from earlier ones. The cgroup lifetime peak is a separate kernel measurement across the whole container lifetime. These values do not establish long-duration leak freedom or the memory needs of larger future data releases.

## What the limits establish

The default memory budget had substantial headroom in this tested workload. The configured connection cap rejected excess work and the process stayed running and returned ready after pressure ended. That confirms bounded retention and overload protection for the current packaged demo.

The concurrency setting is a protection limit, not a promise to serve 16 simultaneous evaluations quickly. Normal p95 rose to roughly 5.5–7 seconds at eight concurrent requests, and bursts had longer accepted-request latency. A future performance task should profile source/bundle validation and response-contract validation, then reduce repeated work while preserving file-integrity checks, compatibility policy, and provenance. Further tuning needs a team-agreed latency target and a repeat on the actual hosting machine.

## Readiness timeout regression

A separate run enabled the production image's periodic Docker readiness probes while sending 32 geometric requests per path at concurrency eight. The [original four-second URL timeout failed](backend-load-health-before.json): all 96 normal evaluation requests succeeded, but repeated readiness timeouts marked the container unhealthy during the fresh-calculation phase. This was a deployment-health failure, rather than a failed visibility calculation.

The API Dockerfile now gives the readiness URL 14 seconds inside a 15-second Docker health timeout. The [same sustained-load regression with that correction](backend-load-health.json) passed: all 96 normal evaluations succeeded, each normal phase stayed healthy, and all recorded periodic probes exited successfully. Some probe durations exceeded seven seconds under load, confirming that the original timeout was too short for this image. The overload burst returned 14 successes and 18 expected rejections; after closing the held connections, readiness recovered and a new Docker health probe completed successfully.

Including those periodic probes and the overload burst, this second run peaked at 170.5 MiB sampled API RSS and 154.7 MiB kernel cgroup memory, with no OOM or cache-bound violations.

The original full latency/memory baseline above had health probes disabled, so it remains useful as a measurement of the three execution paths. The separate health regression records the rebuilt image ID and corrected health configuration. The larger timeout addresses the measured false-unhealthy behavior; it does not improve evaluation latency. CI now includes periodic health checks in its short load rehearsal.
