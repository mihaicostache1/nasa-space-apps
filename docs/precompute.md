# Offline evaluation precompute manifest

This first precomputation step defines bookkeeping for bundles of reference evaluations. Models are in `backend/src/lunarwindow/precompute/models.py`, exported as `PrecomputeManifest`, `PrecomputeJob`, and `PrecomputeOutput`. The packaged JSON Schema is `lunarwindow/precompute/precompute-manifest.schema.json`. Result generation, bundle file verification, and serving persisted results are later tasks; this step does not change the API or its in-memory cache.

## Run contract

`PrecomputeManifest` declares `schemaVersion: "lunarwindow.precompute-manifest.v1"` and contains:

| Field            | Meaning                                                        |
| ---------------- | -------------------------------------------------------------- |
| `runId`          | Required lowercase slug identifying the run                    |
| `createdAtUtc`   | Required valid UTC creation timestamp ending in `Z`            |
| `completedAtUtc` | Successful completion timestamp, or null for an incomplete run |
| `status`         | Required `incomplete` or `complete`                            |
| `jobs`           | Nonempty list of unique evaluation jobs                        |

A complete run requires every job to be complete and a completion timestamp at or after creation. An incomplete run must contain at least one pending or failed job and cannot declare a successful completion timestamp. Partial outputs remain recorded in an incomplete run. A run with failed jobs is incomplete; a future consumer must not treat it as a successfully published bundle. Run timestamps allow seconds and microseconds, separately from whole-minute evaluation times.

## Job identity and state

Each `PrecomputeJob` contains an `evaluation`, required `status`, optional `output`, and optional `error`. The evaluation is the existing `ReferenceEvaluationCacheKey`, not a separate request format. It records:

- Site, geometric/terrain horizon mode, inclusive start, exclusive end, sampling interval, visibility rule, and effective countdown reference time.
- The full archived ephemeris JSON checksum and calculation-model version.
- Mask ID and full mask artifact checksum for terrain mode, plus explicit frame-approximation acceptance. Geometric jobs have null mask fields and false terrain acceptance.
- The versioned cache-key namespace and its existing UTC/default normalization rules.

The evaluation digest identifies a job. Duplicate digests are rejected, including keys with equivalent UTC spellings that normalize to the same values. Source or model revisions produce different identities. Terrain precompute jobs require explicit `allowMeanEarthApproximation: true` for the currently supported pairing. This declaration does not prove that the observer or frames are compatible: the generator must still run the existing compatibility checks.

| Job status | Output       | Error                         |
| ---------- | ------------ | ----------------------------- |
| `pending`  | Must be null | Must be null                  |
| `complete` | Required     | Must be null                  |
| `failed`   | Must be null | Required nonblank description |

Only complete jobs can claim published output artifacts. A failed job can coexist with completed jobs in an incomplete manifest. Retrying and finalizing a run must construct and validate a new consistent manifest; the contract does not implement a scheduler or state-transition engine.

## Output contract

`PrecomputeOutput` records:

| Field                   | Meaning                                                                                                          |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `filename`              | Exactly `<evaluation.digest>.json`, beside the manifest                                                          |
| `sha256`                | SHA-256 of the exact serialized response bytes written to that file                                              |
| `responseSchemaVersion` | `lunarwindow.reference-evaluation.v1` for geometric mode; `lunarwindow.reference-evaluation.v2` for terrain mode |

The input identity determines the filename; the output checksum independently identifies the serialized result. Filenames contain 64 lowercase hexadecimal characters and `.json`, so paths, directories, URLs, drive names, and collisions with `manifest.json` are rejected. The filename must agree with its job's digest. All checksums require 64 lowercase hexadecimal characters. Output format/version must match horizon mode.

## Validation boundary

Use the Python model for structural and semantic validation:

```python
from lunarwindow.precompute import PrecomputeManifest

manifest = PrecomputeManifest.model_validate_json(manifest_bytes)
schema = PrecomputeManifest.model_json_schema()
```

The packaged JSON Schema describes field shapes, literals, checksums, and nested key fields. Cross-field rules such as run completeness, duplicate jobs, timestamp ordering, and filename/digest agreement are enforced by the Python model. The checked-in schema is tested against the model's exported schema.

Contract validation performs no artifact reads, writes, downloads, calculations, or API calls. It reuses strict models with forbidden extra fields and revalidates nested model instances. Valid metadata, a completion claim, or a checksum with correct syntax does not prove that files exist, hashes match, scientific sources are verified, or calculations are correct.

The next generator task must verify the existing archive and reviewed masks, select valid samples, check compatibility, calculate and validate responses, write/hash the same serialized bytes, and publish a complete manifest only after all outputs succeed. A future bundle loader must independently verify those files and match their validated response metadata to the recorded jobs before reuse. Existing API source/compatibility checks and the documented reference-demo limitations continue to apply. Preliminary GIS horizons and unreviewed sites are not authorized by a manifest entry.

Focused tests are in `backend/tests/test_precompute_contract.py`:

```sh
python -m unittest discover -s backend/tests -p test_precompute_contract.py -v
```
