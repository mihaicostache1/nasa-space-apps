# Custom API load-test measurements

Recorded at 2026-11-15T09:17:11.119831+00:00. These are local, controlled-fixture measurements,
not live NASA performance, original LOLA raster performance, or independent science
validation. See [the harness and reproduction instructions](../custom-load-test.md).

## Full parameter run

Command:

```sh
.venv/bin/python scripts/load_test_custom.py \
  --image lunarwindow-custom-load:check --profile full --requests 4 \
  --output /tmp/lunarwindow-custom-load-full.json
```

The image was built from the current checkout with target `custom-test`.
Immutable image: `sha256:9386f01f1086c08ac81da88dbd08e6dacee054e306755ee870c5e52eb3ca6bcb`.
Python 3.14.10, aarch64;
full dependency versions, harness/source hashes and configuration are in the
[raw report](custom-load-test.json).

Settings: one worker, one custom admission slot, concurrency one, 1 GiB container
memory with swap disabled, two CPUs, four requests per path, and three samples per
request. Terrain used synthetic flat 20/120 m GeoTIFFs with the unchanged production
3,600-ray / 200 km parameters. The local fixture server delayed each response by
20 ms. This is warm-process testing; startup, fixture creation and warmups are not
included. Four samples per path are a small diagnostic measurement; nearest-rank
p95/p99 equal the maximum and do not establish a service-level guarantee.

| Execution path       | HTTP p50 ms | HTTP p95 ms | Sampled RSS peak MiB | Sampled cgroup peak MiB |
| -------------------- | ----------: | ----------: | -------------------: | ----------------------: |
| horizons-acquisition |        81.9 |        89.3 |                112.2 |                   170.8 |
| archive-reuse        |         4.0 |         4.9 |                112.6 |                   171.2 |
| terrain-generation   |       587.8 |       626.5 |                592.8 |                   651.5 |
| terrain-reuse        |        53.8 |        55.3 |                320.6 |                   378.7 |

Each fresh acquisition performed exactly eight local upstream calls across four
requests. Terrain generation performed four actual ray casts and eight full fixture
source hashes, with zero upstream calls during timing. Terrain reuse still hashed
both sources for each request, without ray casting or visibility recalculation.
The measured source sizes are much smaller than the original multi-gigabyte DEMs.
The memory columns are absolute process/container peaks, not incremental allocation;
allocator retention and page caches can carry memory across phases. Sampling every
20 ms gives lower bounds; raw reports also retain kernel lifetime cgroup peaks.

## Admission, deadlines and retention

- All 8 requests sent after occupying the admission slot
  returned structured `503 custom_busy` without starting acquisition or calculation.
  Releasing the held slot allowed its real evaluation to complete.
- A one-second budget against a 1.5-second delayed fixture returned
  `504 custom_upstream_timeout` after 1019.0 ms. Exactly one
  upstream attempt ran; no visibility calculation started. The following ordinary
  request succeeded, confirming admission recovery.
- Memory retention stayed within two entries / 1 MiB; each disk artifact store
  stayed within four entries / 16 MiB. Four distinct requests exercised memory
  eviction. No sampled cache-bound violations, monitoring errors or new OOM events
  were observed. The container remained alive.

## Concurrency and CI smoke

The [two-slot smoke report](custom-load-concurrency.json) covers concurrency one and
two, four requests per path, all eight normal phases, admission saturation and
post-timeout recovery. Peak admitted concurrency reached 2. It uses 360
rays to 1 km, so it validates concurrent paths/bounds rather than the resource cost
of two full production terrain requests. The default full run above retains the
production default of one custom slot.

The [CI-sized smoke report](custom-load-ci-smoke.json) covers two requests per path
at one slot with the same busy/deadline assertions. GitHub Actions now runs this
profile and uploads `custom-api-load-smoke` on success or failure. The existing
reference load test remains separate.

Increasing production slots or setting live-service latency targets requires a
new run with the deployed machine, original verified DEMs and real upstream access.
These fixture timings alone do not justify raising the default concurrency.
