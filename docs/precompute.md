# Offline evaluation precompute manifest

Offline precomputation defines, generates, verifies, and loads bundles of reference evaluations. Models are in `backend/src/lunarwindow/precompute/models.py`, exported as `PrecomputeManifest`, `PrecomputeJob`, and `PrecomputeOutput`. The packaged JSON Schema is `lunarwindow/precompute/precompute-manifest.schema.json`. The generator is in `generator.py`, the read-only verifier is in `verifier.py`, key-based lookup is in `loader.py`, and offline commands are in `cli.py`. The reference evaluation API can opt into a complete bundle through the server-side `LUNARWINDOW_PRECOMPUTED_DIR` setting.

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

The generator verifies the existing archive and reviewed masks, selects valid samples, checks compatibility, calculates and validates responses, writes/hashes the same serialized bytes, and publishes a complete manifest only after all outputs succeed. The standalone verifier independently reads the saved files and matches validated response metadata and provenance to both the recorded jobs and verified sources. Existing API source/compatibility checks and the documented reference-demo limitations continue to apply. Preliminary GIS horizons and unreviewed sites are not authorized by a manifest entry.

## Generate an explicit job list

`generate_bundle(jobs, *, run_id, reference_directory, output_directory, terrain_directory=None)` accepts a nonempty, unique sequence of pending `PrecomputeJob` objects and returns the completed `PrecomputeManifest`. The generator revalidates the whole plan before creating files and rejects non-pending jobs. It requires a fresh output directory, refusing to overwrite an existing file or directory. There is no automatic site/date expansion, network retrieval, resume mode, or result-cache use.

This example generates one geometric evaluation and one reviewed Site01 terrain evaluation from the committed archive:

```python
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.api.reference_cache_key import build_reference_evaluation_cache_key
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.precompute import PrecomputeJob, generate_bundle
from lunarwindow.reference import load_verified_reference_dataset
from lunarwindow.terrain.registry import load_reviewed_mask

root = Path("data/reference")
site_id = "lola-site01-reference"
archive = load_verified_reference_dataset(root / "validation-30d", site_id)
reviewed = load_reviewed_mask(root / "terrain-masks", "lola-site01-reference-mast-0m")
jobs = []
for terrain in (False, True):
    options = {
        "siteId": site_id,
        "horizonMode": "terrain" if terrain else "geometric",
        "startUtc": "2026-11-14T00:00:00Z",
        "endUtc": "2026-11-15T00:00:00Z",
    }
    if terrain:
        options.update(maskId=reviewed.mask.maskId, allowMeanEarthApproximation=True)
    request = TypeAdapter(ReferenceEvaluationRequestContract).validate_python(options)
    key = build_reference_evaluation_cache_key(
        request,
        ephemeris_sha256=archive.artifact_sha256,
        terrain_mask_sha256=reviewed.artifact_sha256 if terrain else None,
    )
    jobs.append(PrecomputeJob(evaluation=key, status="pending"))

manifest = generate_bundle(
    jobs,
    run_id="site01-reference-demo",
    reference_directory=root / "validation-30d",
    terrain_directory=root / "terrain-masks",
    output_directory=Path("data/processed/site01-evaluation-example"),
)
```

The initial reads create explicit planned identities. The provider verifies the sources again for each actual calculation. Its internal `expected_key` guard compares the verified byte-snapshot identity, requested options, and current model version with the planned key **before** calculation. A changed source, reviewed mask, or model version fails the job instead of silently generating under stale metadata. Range and terrain compatibility checks also run normally; a manifest cannot authorize a mismatched observer or unreviewed mask.

Each response is serialized to UTF-8 JSON with a final LF newline, revalidated against the existing response contract, and checked against the planned job identity. Output writes use the existing atomic-write helper without platform newline translation. The generator reads the saved file back, requires it to equal the validated serialized bytes, and hashes those saved bytes for `output.sha256`. It checks every completed output's existence and checksum again before publishing the complete manifest. Input artifacts are not modified.

## Checkpoints and failures

Before any calculations, the new directory contains an atomically written incomplete `manifest.json` with all jobs pending. Each successful job is checkpointed; the final checkpoint becomes complete only after every output succeeds and the final checksum checks pass. No complete manifest is published while jobs remain pending or failed.

A job failure stops execution, records a failed job with its diagnostic error, preserves other successful outputs, leaves later jobs pending, and raises `PrecomputeGenerationError` with the original exception as its cause. Failed jobs claim no published output. A failure can leave an unclaimed output file in the incomplete directory, for example if response writing succeeded but final manifest publication failed. Such a directory must not be consumed as a complete bundle.

Manifest I/O errors can propagate as `OSError` if even the failure checkpoint cannot be saved; the last successful atomic checkpoint remains authoritative. `KeyboardInterrupt` and process termination can leave a job pending in that checkpoint. Retry in a fresh directory; this generator does not resume or overwrite runs. The completion marker is producer bookkeeping rather than independent scientific validation; use the verifier to audit persisted artifacts.

`backend/tests/test_precompute_generator.py` exercises real geometric/terrain generation, exact saved checksums, checkpoint ordering, source/model identity rejection, compatibility, invalid results, non-overwrite behavior, write failures, interruptions, and damaged outputs before completion.

## Verify a saved bundle

```python
from pathlib import Path

from lunarwindow.precompute import verify_bundle

verified_manifest = verify_bundle(
    Path("data/processed/site01-evaluation-example"),
    reference_directory=Path("data/reference/validation-30d"),
    terrain_directory=Path("data/reference/terrain-masks"),
)
```

`verify_bundle(directory, *, reference_directory, terrain_directory=None)` returns the validated `PrecomputeManifest` only after every listed job passes. `reference_directory` is required because evaluation responses do not duplicate the full archived JSON checksum. The source loader establishes that checksum from the exact source bytes it parses. The terrain directory defaults to `reference_directory.parent / "terrain-masks"`; geometric-only bundles remain independent of terrain files.

Verification checks:

1. The manifest contract and complete run/job states, including unique identities, safe filenames, timestamps, and output/mode schema declarations.
2. The current supported `VISIBILITY_MODEL_VERSION`. Future or historical model versions are rejected; the recorded version cannot authorize different calculation semantics.
3. Every listed output's existence, regular-file type, and exact-byte SHA-256. Symlinked manifests/outputs and special files are rejected. Each output is hashed and parsed from the same read.
4. The existing geometric v1 or terrain v2 response contract and its agreement with the output schema declaration and recorded job options: site, horizon mode, dates, interval, visibility rule, countdown reference, and terrain mask identity/acceptance.
5. The complete reference bundle, exact archived JSON checksum, and requested sample selection. Output site metadata, original NASA request evidence, native archive coverage, and all raw ephemeris values must match the verified source selection exactly.
6. For terrain results, the registered mask's pinned checksum and complete mask metadata, plus current observer/frame compatibility and its recorded assessment. A self-declared artifact checksum in an output is insufficient.

The generator and verifier share request/response identity rules in `validation.py`. The verifier independently loads artifacts and sources, performs no visibility calculations, and does not access caches, download data, or write files. A missing, corrupt, incomplete, unsupported, or inconsistent bundle raises `PrecomputeVerificationError` (a `ValueError`) with the original failure as its cause; no partial manifest is returned. Only manifest-listed output artifacts participate in verification.

The returned manifest describes the byte snapshots checked during the call. It contains metadata rather than retained response bytes. Use `load_precomputed_evaluation` below to obtain a response model directly from the verified snapshots; a later standalone file read requires its own verification. Matching checksums, contracts, and source provenance does not independently validate the numerical metrics/windows or establish mission accuracy. Those calculations retain the existing regression evidence and documented model limits.

Focused verifier tests in `backend/tests/test_precompute_verifier.py` cover generated geometric/terrain bundles, incomplete states, corrupted and rehashed outputs, changed options and provenance, stale source/model identities, symlink artifacts, read-only operation, geometric independence, and same-read hashing/parsing.

## Load one evaluation by its key

`load_precomputed_evaluation(directory, key, *, reference_directory, terrain_directory=None)` accepts a `ReferenceEvaluationCacheKey` and returns a fresh geometric/terrain response model or `None` for an absent identity. For example, using the explicit `jobs` from the generation example:

```python
from lunarwindow.precompute import load_precomputed_evaluation

evaluation = load_precomputed_evaluation(
    Path("data/processed/site01-evaluation-example"),
    jobs[0].evaluation,
    reference_directory=Path("data/reference/validation-30d"),
    terrain_directory=Path("data/reference/terrain-masks"),
)
if evaluation is None:
    print("No saved evaluation for this key.")
```

The loader revalidates the lookup key and rejects unsupported lookup-model versions. It then runs the same complete bundle/source verification used by `verify_bundle`, retaining the matching response parsed from the exact bytes whose checksum was verified. It returns a match or miss only after **all** listed jobs pass. A corrupt sibling or invalid source cannot be hidden by an early match or absent-key shortcut. During verification, at most one matching model is retained alongside the current job; outputs are not reread afterward.

Lookup uses the full canonical key, including source/mask checksums, model version, request options, and approximation acceptance. Equivalent normalized timestamps match; differing options or checksums identify different requests and can produce a miss. `None` means the key is absent from an otherwise valid complete bundle. Missing/incomplete/corrupt bundles, mismatched recorded sources, unsupported bundle models, and invalid masks raise `PrecomputeVerificationError` rather than becoming misses. Malformed lookup keys raise Pydantic validation errors before artifact reads.

Every call verifies the current bundle and sources again and returns newly parsed model objects. Mutating returned samples or nested provenance cannot affect another call or the saved files. The loader performs no calculation, cache access, downloads, or writes. A mixed geometric/terrain bundle requires valid masks even for a geometric lookup because verification covers the whole bundle; a geometric-only bundle remains independent of terrain files.

The loader itself returns a miss rather than calculating a fallback. The reference evaluation API now uses it after request/source/compatibility checks when `LUNARWINDOW_PRECOMPUTED_DIR` is configured: an exact saved match returns directly; a verified miss uses memory cache or normal calculation. An invalid configured bundle returns HTTP 503 even when memory contains a previous result. Unset or blank disables persisted lookup. The existing HTTP contracts and provenance remain unchanged, and the API performs no slicing of larger saved results. See [API configuration and error behavior](backend-data.md#serve-precomputed-reference-evaluations). Tests in `backend/tests/test_precompute_loader.py` cover hits, exact-key misses, returned-model isolation, same-read snapshots, corrupted siblings, invalid bundles/keys/models, source revalidation, terrain requirements, and read-only operation.

## Offline command-line interface

Install or refresh the backend package to register `lunarwindow-precompute`:

```sh
python -m pip install -e ./backend
lunarwindow-precompute --help
```

The same commands are available through `python -m lunarwindow.precompute`. Both entry points support `generate` and `verify`; all sources are local and the commands perform no NASA requests, DEM downloads, or automatic job expansion.

Generation takes an explicit pending manifest plan. To save the verified `jobs` list constructed in the Python example above:

```python
from datetime import datetime, timezone

from lunarwindow.precompute import PrecomputeManifest

plan = PrecomputeManifest(
    runId="site01-reference-demo",
    createdAtUtc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    status="incomplete",
    jobs=jobs,
)
plan_path = Path("data/processed/site01-plan.json")
plan_path.parent.mkdir(parents=True, exist_ok=True)
with plan_path.open("x", encoding="utf-8", newline="") as stream:
    stream.write(plan.model_dump_json(indent=2) + "\n")
```

All plan jobs must be pending, without outputs or errors. Complete runs and failed/partially completed manifests are rejected as plans. The CLI preserves `runId` and job identities; the generator records fresh run creation/completion timestamps. Source checksums and approximation acceptance must be explicit in the plan. Reusing a plan after a source/model change fails through the existing identity checks.

Generate into a fresh directory and then independently verify it:

```sh
lunarwindow-precompute generate data/processed/site01-plan.json \
  --reference-dir data/reference/validation-30d \
  --terrain-dir data/reference/terrain-masks \
  --output data/processed/site01-cli-example

lunarwindow-precompute verify data/processed/site01-cli-example \
  --reference-dir data/reference/validation-30d \
  --terrain-dir data/reference/terrain-masks
```

`--reference-dir` is required on both commands and points directly to the archive directory containing its source `manifest.json`. `--terrain-dir` is optional and defaults to its sibling `terrain-masks`. `--output` is required for generation; existing paths are never overwritten. The plan is not modified. Verification remains read-only.

On success, stdout contains one JSON summary with `command`, `status`, `runId`, `jobCount`, and the `manifest` path. Generation success reports completed generation; the separate verification command checks the saved bundle against its sources. Errors go to stderr with no success summary or traceback for expected operational failures. Generation errors identify the retained incomplete manifest and include the underlying cause.

| Exit code | Meaning                                                                         |
| --------- | ------------------------------------------------------------------------------- |
| `0`       | Successful command or help                                                      |
| `1`       | Invalid plan, failed generation/verification, or filesystem error               |
| `2`       | Argument/usage error from argparse                                              |
| `130`     | Interrupted by the user; inspect the last generation checkpoint before retrying |

`backend/tests/test_precompute_cli.py` covers both commands on real archived inputs, argument validation, stdout/stderr separation, custom directories, paths with spaces, generation and verification failures, interruption, and module-entry-point exit codes.

Focused tests are in `backend/tests/test_precompute_contract.py`:

```sh
python -m unittest discover -s backend/tests -p test_precompute_contract.py -v
```
