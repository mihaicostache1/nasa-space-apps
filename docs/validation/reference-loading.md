# Reference comparison loading optimization

The public API was measured before this change with the default full-month
geometric Site01/Site23 evaluations requested in parallel: 34.7 s / 36.4 s,
including public-network time. The catalog request measured 5.7 s. These are
observations of the hosted service at that time, not a latency guarantee or an
isolated CPU benchmark. The updated code has not yet been deployed there.

## Cause and change

One saved-result request repeatedly validated identical ephemeris JSON through
source-run checks, selections and every precomputed job. Local profiling identified
this repeated contract validation as the dominant cost.

`validation_session()` now reuses only successful validations of identical,
plain-JSON content within one operation. The fingerprint set is limited to 64
SHA-256 entries, stores no datasets, and is discarded on return or exception.
Nested calls share the same operation; separate requests have separate contexts.
Mutating a dictionary changes its fingerprint. Tuples, non-string dictionary keys,
non-JSON types and non-finite values cannot acquire a coerced JSON cache hit.

Every lookup still reads and hashes source files, checks CSV/manifest consistency,
verifies every listed precomputed output, checks source/mask compatibility and
returns a fresh response model. No file snapshot or successful response is trusted
across requests by this optimization. The existing invalid-source/error behavior,
scientific values, sampling and provenance remain unchanged.

Reference catalog, evaluation and readiness operations use the scope, as do
standalone verified-source and precomputed-bundle loads. Raw schema validation
outside such a scope keeps its original behavior.

Large API responses now use gzip when the client advertises support, with a
1,000-byte threshold and compression level 3. Decoded JSON is unchanged; CORS and
`Vary: Accept-Encoding` remain correct. Small health/error responses stay small.

The frontend retains an unchanged ready scenario when its partner changes. It
still retries failed/loading slots. Pressing Update with both inputs unchanged
explicitly refreshes both, and changing both scenarios evaluates both. This is not
a persistent browser result cache; prior results keep their source provenance and
changed inputs retain the existing stale/error behavior.

## Local measurement

[Raw measurements](reference-loading-benchmark.json) record five alternating
full-month Site01 saved-result evaluations on Python 3.12.16,
arm64. The baseline disables only operation-local validation
reuse to reproduce the former repeated-validation path. Both variants use fresh
response caches and the same source files; import/page-cache warmup is excluded.
Every compared response is byte-identical after serialization. Host network,
Render CPU quotas, cold starts and client rendering are outside this measurement.

| Measurement                              |                Baseline |                  Optimized |
| ---------------------------------------- | ----------------------: | -------------------------: |
| Median local evaluation                  |                606.7 ms |                   155.0 ms |
| Ephemeris schema validations per request |                      36 |                          3 |
| Example response transfer                | 244,884 bytes, identity | 41,187 bytes, gzip level 3 |

That is approximately 3.9× faster for this local request and
83.2% fewer transferred bytes for the
example compressed response. It is not a prediction of the same speedup on Render.

## Verification and deployment

- Focused tests cover fingerprint mutation, encoded type coercion, failed validation,
  nested/exception scopes, concurrent isolation and the retention bound.
- Existing warmed-cache/source-corruption and precompute integrity regressions remain
  active; the original demo release reproduces without changed response bytes.
- HTTP tests compare gzip and identity JSON and verify CORS, health and error behavior.
- Frontend tests cover selective updates, retries and explicit refresh. The browser
  rehearsal verifies that editing A submits only A while preserving B, and exercises
  terrain, playback, shared cursors and mobile layouts.

Deploy the backend optimization and the frontend request-planning change to apply
both improvements. First access to a sleeping Render Free service can still take
about a minute; this code does not remove the platform's idle spin-down behavior.
See [Render Free documentation](https://render.com/docs/free).

## Startup from the verified release

The home page now includes the initial geometric Site01 (A) and Site23 (B)
evaluations directly from `lunarwindow-demo-v1`. Next.js renders them at build time
and passes them as serialized page data. Loading the reference explorer and playing
its period require no catalog GET or evaluation POST. The page still needs to load
from the frontend host; this does not remove a frontend service's cold start.
Custom capabilities and custom evaluations continue to use the API independently.

These are the original release response objects, with 720 hourly samples each,
metrics, windows, observer data and NASA/JPL Horizons provenance intact. No synthetic
samples, interpolated visibility flags or replacement calculations are introduced.
Only the two initial geometric responses are included. Terrain, changed inputs and
explicit refreshes use the existing API evaluation path and its integrity checks.

The visible snapshot note identifies A/B and the release ID. The provenance panel
also records the original output SHA-256 for each snapshot. A successful API update
removes that slot's snapshot attribution; an unchanged partner keeps its own label.
Errors retain previous results with an explicit failure status. Inputs that differ
from retained data still mark those results stale. A failed refresh never presents
the startup snapshot as a new successful API response.

`data/frontend/reference-bootstrap.json` contains the release manifest checksum,
output identities and a snapshot of the verified reference catalog. Discovery is
therefore tied to this frontend build, rather than reflecting changes to a running
backend immediately. Regenerate it when publishing a new supported catalog/release:

```sh
python scripts/build_reference_bootstrap.py
python scripts/build_reference_bootstrap.py --check
```

Use the backend environment with its dependencies installed. Generation first
verifies the entire release, current archived evidence and reviewed terrain
registrations. It selects exactly the jobs matching the UI's default requests and
does not rewrite any evaluation output. Commit the generated metadata with the
frontend. Ordinary Node-only frontend builds need neither Python nor a running API.
Changing the release also requires updating the two server imports; tests verify
those imports against the metadata's original output hashes and full response data.

CI checks metadata reproducibility against the current source evidence. Frontend
tests check hashes, unchanged data/provenance and exact default input matching.
The Chromium rehearsal blocks all API traffic for an initial-load/playback check,
then checks explicit refresh failure and normal live refresh, terrain and mobile
flows. One local production rehearsal prepared the explorer in 129 ms with the API
blocked and zero reference requests; this is a local observation, not a hosted
latency guarantee.

Deploy the frontend changes to enable this startup path. The backend does not need
an additional deployment for startup snapshots; it remains necessary for updates
and custom evaluations.
