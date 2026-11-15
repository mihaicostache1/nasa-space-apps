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
