# Backend/data — tasks 1 and 2

The FastAPI backend provides synthetic scenario demos and geometric or reviewed-terrain evaluations of verified archived NASA ephemerides. Reference-data integration includes validated loaders, a site catalog, date-range selection, request/response contracts, observer/frame compatibility checks, calculation-engine adapters, bounded result caching, and dedicated terrain-blocking regressions. Extended precomputation remains a later task. See [the calculation model and migration details](visibility.md).

The [terrain-mask v1 handoff contract, offline loader, and compatibility helper](terrain-mask.md) define validated observer coordinates/heights, reference frames, complete horizon profiles, and DEM/algorithm provenance. `load_terrain_mask(path, expected_sha256=...)` verifies the artifact's exact bytes. `check_terrain_compatibility(mask, dataset)` checks observer geometry and frame evidence, rejecting the untransformed DE421/Horizons pairing by default. The [terrain-aware evaluation endpoint](#terrain-aware-evaluation-contract) requires explicit reference-demo acceptance and records the approximation and scientific sources.

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

| Method | Route                                      | Response                                                        |
| ------ | ------------------------------------------ | --------------------------------------------------------------- |
| GET    | `/api/health`                              | Backend process health and `dataMode: "synthetic"`              |
| GET    | `/api/sites`                               | Three illustrative demo points, coordinates, and source labels  |
| GET    | `/api/sites/{site_id}`                     | One demo point's horizon and time series                        |
| POST   | `/api/evaluations`                         | Synthetic data for the existing frontend `Scenario` request     |
| POST   | `/api/reference/evaluations`               | Geometric or reviewed-terrain metrics and windows from archives |
| GET    | `/api/reference/sites`                     | Verified reference coordinates and archive availability         |
| GET    | `/api/reference/sites/{site_id}/ephemeris` | Verified archived Sun/Earth samples and original provenance     |

The site-data route accepts `startUtc`, `endUtc`, `stepMinutes`, `visibilityRule`, and `asOfUtc` query parameters. Defaults are 2026-11-14T00:00:00Z through 2026-12-14T00:00:00Z, at 60-minute steps, with `any-disc` visibility and countdowns relative to the range start. These fixed dates make demos reproducible. An unknown site returns HTTP 404.

```sh
curl http://localhost:8000/api/sites
curl 'http://localhost:8000/api/sites/demo-polar-a?startUtc=2026-11-14T00:00:00Z&endUtc=2026-11-15T00:00:00Z&stepMinutes=60'
curl http://localhost:8000/api/evaluations \
  -H 'Content-Type: application/json' \
  -d '{"name":"Scenario A","location":{"latitudeDeg":-89,"longitudeDeg":0,"altitudeKm":0},"startUtc":"2026-11-14T00:00:00Z","endUtc":"2026-12-14T00:00:00Z","stepMinutes":60,"visibilityRule":"any-disc","asOfUtc":"2026-11-14T12:00:00Z"}'
```

## Reference site catalog

```sh
curl http://localhost:8000/api/reference/sites
```

The response declares `schemaVersion: "lunarwindow.reference-catalog.v1"`, provider `NASA/JPL Horizons`, UTC time, and east-positive longitude. Each entry in `sites` contains `id`, `name`, `lat`, `lon`, `altitudeKm`, the original `coordinateSource`, and `availability` with `startUtc`, `endUtc`, `endExclusive`, `stepMinutes`, and `sampleCount`.

Each site also includes `supportedHorizonModes` and `terrainMasks`. These are additive v1 fields; existing identity and archive-coverage fields retain their meanings. Site01 advertises `["geometric", "terrain"]` and the reviewed `lola-site01-reference-mast-0m` mask. Site04 and Site23 advertise `["geometric"]` with an empty mask list. A mask entry contains:

| Field                            | Meaning                                                                  |
| -------------------------------- | ------------------------------------------------------------------------ |
| `maskId`                         | Server-reviewed ID to pass to the evaluation endpoint                    |
| `artifactSha256`                 | Pinned checksum verified against the exact artifact bytes                |
| `observer`                       | Original coordinates, surface elevation, mast height, and total altitude |
| `referenceFrame`                 | Original lunar frame declaration and reference sphere                    |
| `demSources`                     | Original DEM product IDs, versions, resolutions, URLs, and checksums     |
| `requiresMeanEarthApproximation` | Whether evaluation requires explicit `allowMeanEarthApproximation: true` |
| `framePolicy`, `limitation`      | Compatibility policy and its reference-demo limitation                   |

The current mask records `observer.mastHeightM: 0`, meaning ground level rather than a chosen lander antenna height. Its `requiresMeanEarthApproximation` is `true`; the backend applies no frame transformation. Catalog discovery does not accept this approximation on the user's behalf. The frontend can enable its toggle using `supportedHorizonModes`, select a returned `maskId`, and explain the observer and frame assumptions before requesting a terrain evaluation. A new antenna height requires matching reviewed mask and ephemeris artifacts.

Before advertising a mask, the API checks its server registration, pinned checksum, strict `TerrainMask` contract, and observer/frame compatibility against the site's full archived period. A missing, corrupted, or incompatible registered mask returns HTTP 503 for the catalog, with no partial catalog or filesystem paths. Unregistered files and preliminary GIS horizons are ignored. Geometric evaluations and the raw ephemeris endpoint remain independent of terrain artifacts. Full horizon samples are returned by evaluations, not this discovery endpoint.

The catalog is derived from the complete verified bundle. Currently it lists three LOLA DEM reference points, each with 720 hourly samples covering 2026-11-14T00:00:00Z through 2026-12-14T00:00:00Z (end excluded). Their source descriptions identify them as reference points rather than selected landing targets. Missing, corrupted, or invalid source data returns a structured HTTP 503; no partial catalog is published. The endpoint performs no downloads or writes.

Use an entry's `id` with the reference ephemeris endpoint below. Availability describes the full archive and its native sampling interval; optional selections do not change the catalog. The OpenAPI documentation includes the catalog's typed response schema.

## Read one verified reference dataset

```sh
curl http://localhost:8000/api/reference/sites/lola-site01-reference/ephemeris
```

Without query parameters, this endpoint returns the selected site's original `lunarwindow.ephemeris.v2` dataset unchanged: all 720 hourly samples from 2026-11-14 through 2026-12-14 UTC (end excluded), angular radii, coordinates, and NASA/JPL provenance. It validates the complete reference bundle first. The response matches `EphemerisDataset` in `src/domain/ephemeris.ts` and contains no terrain, visibility flags, or metrics.

Optional query parameters select a contained range and sampling interval:

```sh
curl 'http://localhost:8000/api/reference/sites/lola-site01-reference/ephemeris?startUtc=2026-11-15T00:00:00Z&endUtc=2026-11-16T00:00:00Z&stepMinutes=120'
```

This returns 12 existing samples, starting at 00:00 and ending at 22:00 on November 15. `startUtc` is inclusive and must lie on the archive's sampling grid. `endUtc` is exclusive and may fall between samples; the returned timestamps still stay strictly before it. Both bounds must be whole-minute UTC strings ending in `Z` and remain within archive coverage. Omitted bounds default independently to the archive's start/end.

`stepMinutes` defaults to the archive interval (currently 60 minutes). Supported values are positive whole-number multiples of that interval, up to 1440 minutes. A larger step selects every corresponding archived sample, anchored at the requested start; it does not interpolate. Requests for unavailable dates, off-grid starts, invalid UTC times, empty/reversed ranges, or unsupported intervals return structured HTTP 422 errors. No bounds are silently clipped and no missing samples are filled.

Filtered responses retain the `lunarwindow.ephemeris.v2` contract. Their `provenance.startUtc`, `endUtc`, and `stepMinutes` describe the returned grid. All original NASA request URLs, response hashes, retrieval times, model headers, coordinates, and angular values are preserved. The source archive is unchanged; use the catalog or unfiltered endpoint for its full coverage. The reusable `select_reference_dataset` helper also validates its selected output against the existing ephemeris contract.

Unknown sites return a structured HTTP 404. Missing or invalid bundle data returns a structured HTTP 503 with no synthetic fallback or filesystem paths in the response. Availability is checked when the reference endpoint is called; the existing demo routes remain independent.

Native startup from the repository root reads `data/reference/validation-30d`. Set the process environment variable `LUNARWINDOW_REFERENCE_DIR` to another reference-root directory containing `validation-30d` if needed. The Docker API image includes the committed bundle at `/app/data/reference/validation-30d`; no downloads or bind mounts are required.

## Evaluate a verified reference site

With `horizonMode: "geometric"`, `POST /api/reference/evaluations` validates the complete reference bundle, selects the requested site's archived samples, and runs the visibility engine against a flat zero-degree horizon. The adapter is in `backend/src/lunarwindow/api/reference_provider.py`; geometric request/response models are in `reference_models.py`, with matching TypeScript types in `src/domain/evaluation.ts`. The operation performs no downloads or writes. Terrain mode is described below.

`ReferenceEvaluationRequest` selects a catalog entry by `siteId` and requires an explicit `horizonMode: "geometric"`, plus `startUtc` and `endUtc`. Optional fields are `stepMinutes` (default 60), `visibilityRule` (default `any-disc`), and `asOfUtc` (default to the selected start during calculation). It uses the existing UTC, range-length, sample-count, countdown-reference, and archive-grid validation. Custom coordinates and unsupported horizon modes are rejected.

```json
{
  "siteId": "lola-site01-reference",
  "horizonMode": "geometric",
  "startUtc": "2026-11-15T00:00:00Z",
  "endUtc": "2026-11-16T00:00:00Z",
  "stepMinutes": 60,
  "visibilityRule": "any-disc"
}
```

Submit this JSON body to `POST /api/reference/evaluations` with `Content-Type: application/json`, or use [the interactive API documentation](http://localhost:8000/docs). Invalid requests, unavailable dates, and unsupported steps return structured HTTP 422 body errors. Unknown site IDs return HTTP 404. Missing or invalid archive data returns HTTP 503; it is never replaced with synthetic data.

The `ReferenceEvaluation` response declares `schemaVersion: "lunarwindow.reference-evaluation.v1"`, `dataMode: "reference"`, and `horizonMode: "geometric"`. It includes the source site's identity/coordinates, a 360-point zero-degree horizon, augmented Sun/Earth samples, metrics, windows, and calculation details using the existing visibility models. A geometric horizon must have ordered azimuths 0..359 and zero elevation in both the mask and the sample horizon fields.

`provenance.ephemeris` retains the selected dataset's complete P1 provenance, including the original NASA request URLs, response hashes, retrieval times, model headers, and coordinate/time conventions. Its period and step describe the selected samples. `provenance.archive` records the original archive's start/end, end-exclusive convention, native step, and sample count. The response also supplies a model-limitation message explaining the flat horizon and the absence of terrain, eclipse, electrical-power, and radio-link models.

Contract validation reuses the P1 provenance schema and dataset checks, including observer-coordinate consistency and the selected sampling grid. It also checks archive coverage/counts, archive/selection grid alignment, calculation step, countdown reference, and evaluated duration. The loader verifies source checksums before the adapter calls the engine. The models validate contract coherence without fetching data or computing visibility. Their schemas are published in OpenAPI, and can also be obtained with `ReferenceEvaluationRequest.model_json_schema()` and `ReferenceEvaluation.model_json_schema()`.

## Terrain-aware evaluation contract

`POST /api/reference/evaluations` accepts both modes through unions discriminated by `horizonMode`, published in OpenAPI. Geometric requests retain the v1 contract above. Terrain requests use `backend/src/lunarwindow/api/terrain_models.py` and return v2 with full mask/compatibility provenance. The server never substitutes a geometric or synthetic horizon for a failed terrain request.

`TerrainReferenceEvaluationRequest` shares the reference site's UTC, period, sampling, visibility-rule, and countdown options. It adds:

| Field                         | Meaning                                                                                           |
| ----------------------------- | ------------------------------------------------------------------------------------------------- |
| `horizonMode`                 | Required `"terrain"`                                                                              |
| `maskId`                      | Required lowercase slug identifying a server-reviewed mask                                        |
| `allowMeanEarthApproximation` | Boolean, default `false`; the reviewed DE421/Horizons pairing requires explicit `true` acceptance |

Callers select an identifier, rather than a file path, custom profile, checksum, coordinates, or observer-height override. The server resolves it through the reviewed registration in `backend/src/lunarwindow/terrain/registry.py`. Currently the only registered ID is `lola-site01-reference-mast-0m`, for `lola-site01-reference`. Its pinned SHA-256 is `4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d`. The registration uses a fixed filename and validates the artifact's mask/site identity; neither requests nor mutable sidecars select trusted hashes. Adding an artifact requires a reviewed registration change.

```json
{
  "siteId": "lola-site01-reference",
  "horizonMode": "terrain",
  "maskId": "lola-site01-reference-mast-0m",
  "allowMeanEarthApproximation": true,
  "startUtc": "2026-11-15T00:00:00Z",
  "endUtc": "2026-11-16T00:00:00Z",
  "stepMinutes": 60,
  "visibilityRule": "any-disc"
}
```

Submit this JSON to the endpoint, or use the interactive API docs. The provider verifies the complete ephemeris bundle, selects the requested grid, loads and hashes the registered mask, and checks observer/frame compatibility before passing the selected samples and exact mask profile to the existing visibility engine. `visibilityRule` and `asOfUtc` are forwarded unchanged. No terrain is regenerated and no source DEM files or GIS extras are needed to evaluate the precomputed mask.

`TerrainReferenceEvaluation` uses `schemaVersion: "lunarwindow.reference-evaluation.v2"`, `dataMode: "reference"`, and `horizonMode: "terrain"`. It retains the existing identity, horizon, augmented samples, metrics, windows, and calculation fields, and adds required `maskId` and `allowMeanEarthApproximation: true`. The current supported frame policy produces an approximate result only after that explicit acceptance; strict requests return HTTP 422 for this pairing.

The response's `provenance` retains the complete selected `ephemeris` evidence and native `archive` coverage. Its required `terrain` object contains:

| Field            | Meaning                                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `artifactSha256` | SHA-256 of the reviewed mask's exact file bytes, supplied after loader verification                                            |
| `mask`           | Complete `lunarwindow.terrain-mask.v1` artifact: identity, observer, frame, conventions, horizon, and DEM/algorithm provenance |
| `compatibility`  | Assessment with IDs, original frame declarations, dynamical source, radius, policy, status, limitation, and source references  |

`TerrainCompatibilityProvenance` maps the domain assessment to camelCase API fields through `from_assessment()`. It requires `framePolicy: "mean-earth-reference-v1"`, `frameStatus: "approximate"`, and boolean `transformationApplied: false`. The full response reruns compatibility checks against its selected ephemeris data and requires the assessment to match, including the limitation and documentation URLs. It rejects claims of exact compatibility, unperformed transformations, or assessment fields that disagree with the source declarations.

The response horizon must exactly equal the provenance mask's ordered profile, preserving negative values. Each sample's horizon elevations must agree with circular linear interpolation at its Sun/Earth azimuths within `1e-9` degree absolute roundoff. Both response modes share the existing ephemeris, observer, selected-grid, archive-coverage, calculation-step, countdown-reference, and duration checks. Contract validation does not calculate visibility states, metrics, or windows, and performs no source downloads or artifact writes. A syntactically valid checksum in a response does not verify file bytes: that remains the loader's responsibility.

`ReferenceEvaluationRequestContract` and `ReferenceEvaluationContract` are unions discriminated by `horizonMode`. Their geometric members preserve `ReferenceEvaluationRequest` and `ReferenceEvaluation` v1 unchanged. Matching transport types are in `src/domain/terrain-evaluation.ts`; `src/domain/terrain-mask.ts` describes the reviewed mask, separately from the GIS `HorizonProfile` format. No frontend UI behavior changes in this step.

Export the same schemas without a running API:

```python
from pydantic import TypeAdapter

from lunarwindow.api.terrain_models import (
    ReferenceEvaluationRequestContract,
    TerrainReferenceEvaluation,
)

request_schema = TypeAdapter(ReferenceEvaluationRequestContract).json_schema()
response_schema = TerrainReferenceEvaluation.model_json_schema()
```

Errors use the existing structured envelope: HTTP 422 for invalid selections, incompatible site/mask pairings, or a rejected compatibility policy; HTTP 404 for unknown registered site/mask IDs; HTTP 503 for unavailable or invalid server artifacts. Missing, corrupted, or identity-inconsistent registered masks produce no result and do not expose filesystem paths. Geometric requests do not load masks and continue working if the terrain directory is unavailable.

Native startup reads masks from `data/reference/terrain-masks`. `LUNARWINDOW_REFERENCE_DIR` selects the reference root for both `validation-30d` ephemerides and `terrain-masks`. The Docker API image includes the reviewed mask at `/app/data/reference/terrain-masks`; no downloads or bind mounts are required. The current mask is a ground + 0 m reference observer, not a configurable antenna height; preserve the frame and near-field limitations described in its provenance and README.

Contract tests in `backend/tests/test_terrain_evaluation_contract.py` validate schemas, round trips, strict defaults, complete provenance, mask/profile agreement, frame-assessment consistency, and shared archive checks. HTTP integration tests in `backend/tests/test_terrain_evaluation.py` compare returned results with the engine on the exact archived samples and reviewed mask, test selection/options/errors, and verify geometric independence. CI also requests a terrain evaluation from the packaged API image. The geometric v1 regression suite remains active.

Dedicated [terrain regression evidence](validation/terrain-regression.md) adds hand-computed blocking/boundary cases and independently derived, pinned Site01 API expectations for all six mode/rule combinations. These protect metrics, all operating-window boundaries, partial-disc behavior, negative horizons, and original source/compatibility provenance. The expectations verify the software model; validation against terrain observations remains separate.

## Reference evaluation cache-key contract

The cache identity contract is in `backend/src/lunarwindow/api/reference_cache_key.py`. `build_reference_evaluation_cache_key` returns an immutable `ReferenceEvaluationCacheKey` with schema `lunarwindow.reference-cache-key.v1` and a deterministic SHA-256 `digest`. Bounded storage and its evaluation-endpoint integration are described below.

The key includes:

- The site's full archived ephemeris JSON checksum, including its metadata, source provenance, and full archive coverage. Hashes of just the selected samples or raw Horizons responses are insufficient for caching complete API responses.
- Site ID and geometric/terrain horizon mode.
- Inclusive start, exclusive end, sampling interval, visibility rule, and effective countdown reference time.
- Terrain mask ID, its complete artifact checksum, and the request's frame-approximation acceptance flag. The complete mask hash also covers observer height, coordinates, reference frame, DEM sources, and algorithm metadata. Geometric keys require null mask fields and false terrain acceptance.
- `calculationModelVersion`, currently `lunarwindow.visibility.v1`, from `visibility/models.py`, and the cache-key schema namespace.

Equivalent whole-minute UTC forms are normalized to seconds ending in `Z`. Omitted request options use their validated API defaults. A missing/null `asOfUtc` resolves to the range start, so it shares identity with an explicit start-time countdown reference. Different exclusive end times remain distinct, including ends between samples that change the final interval's weight. JSON mapping order and source directory paths do not affect identity.

The digest encodes all key fields, including explicit nulls and defaults, using UTF-8 JSON with sorted keys, compact separators, ASCII escaping, and non-finite values forbidden. Tests pin this encoding. The builder revalidates mutable request models, validates checksum syntax, and rejects missing terrain checksums or terrain inputs on geometric keys. It performs no filesystem/network access, visibility calculation, or cache writes.

Checksums supplied to the builder must come from verified artifacts. Syntactically valid hashes do not prove file integrity, archive availability, or mask compatibility. Cache lookup occurs **after** full bundle verification, range selection, reviewed-mask verification, and compatibility checks. Recording a terrain request with acceptance false creates a distinct identity; it does not authorize the request or bypass the existing HTTP 422 policy. Invalid requests and source failures are never served from a cached success or stored as successful evaluations.

Cache complete response snapshots without exposing mutable cached objects. Bump `VISIBILITY_MODEL_VERSION` when calculation semantics change. Bump the cache-key namespace when identity, response construction/schema, or compatibility-policy semantics change, even if source files and numerical calculations stay the same. Focused tests in `backend/tests/test_reference_cache_key.py` cover canonical/default equivalence, every calculation option, both source hashes, mask identity, policy acceptance, version invalidation, strict inputs, and immutability.

## Bounded reference cache storage

`ReferenceEvaluationCache` in `backend/src/lunarwindow/api/reference_cache.py` provides process-local storage keyed by the validated cache-key digest. Defaults are 32 entries and 16 MiB of retained serialized response payloads, configurable per instance with `max_entries` and `max_bytes`. Both limits apply together. The byte budget counts actual payload bytes, excluding Python object/key/container overhead and temporary serialization buffers; the entry count also bounds bookkeeping. Limits must be non-negative integers, excluding booleans. Either limit being zero disables storage.

`put(key, snapshot)` accepts immutable `bytes`, normally the UTF-8 JSON of a complete, validated successful response. It revalidates the key, rejects mutable payloads, and retains no caller-owned response models or dictionaries. It returns `True` after storing/replacing a snapshot, or `False` for disabled storage or a payload larger than the byte limit. A skipped put leaves existing values, byte counts, and recency unchanged. Replacing an entry updates its byte charge and marks it most recently used. Old entries are evicted from least recently used onward until both limits are satisfied; an entry exactly at the byte limit is allowed.

`get(key)` returns the immutable snapshot bytes or `None` on a miss, promoting hits to most recently used. Consumers can decode a fresh response without sharing mutable cached state. `clear()` atomically removes all entries and resets byte accounting. `info()` returns a frozen snapshot of entry count, retained payload bytes, and configured limits. A lock protects reads, recency updates, replacements, eviction, clearing, and accounting; each operation is atomic across threads. The cache does not coordinate calculations across concurrent misses or share data across processes.

Storage performs no source loading, downloads, filesystem writes, JSON/response validation, or visibility calculation. The provider validates successful responses before serialization and performs source integrity, range, and compatibility checks before lookup. Focused tests in `backend/tests/test_reference_cache.py` cover hits/misses, nested JSON mutation protection, entry/byte limits, replacement and oversized-entry behavior, disabled storage, clearing, invalid inputs, and concurrent reads/writes/eviction.

## Cached reference evaluations

`POST /api/reference/evaluations` uses one `ReferenceEvaluationCache` owned by each FastAPI application instance. `get_reference_cache` exposes it as a dependency; independently created applications and worker processes do not share entries. The default limits are 32 responses and 16 MiB of serialized payloads. The application-owned instance is `app.state.reference_evaluation_cache`; deployments or tests can replace it with an instance using different limits, including `max_entries=0` to disable storage. This cache is process-local. Optional persisted lookup is configured separately below; neither choice is a client request option.

For both geometric and terrain requests, the provider first verifies the entire source bundle and selects the requested range/grid. `load_verified_reference_dataset` returns the dataset and SHA-256 of the exact JSON bytes parsed and validated in the same read; it never rereads a potentially changed file to identify an earlier snapshot. The original `load_reference_dataset` interface still returns the dataset unchanged. Terrain mode also reloads the registered mask, checks its pinned checksum, and checks observer/frame compatibility and explicit approximation acceptance. All these checks run on every request, including cache hits.

Only then does the provider build the complete cache key. If persisted lookup is configured, it first verifies that bundle and uses an exact saved match as described below. With no configured bundle or after a verified persisted miss, it checks memory cache. A memory hit deserializes a fresh model through the existing geometric/terrain response contract and skips `calculate_visibility`. A miss runs the calculation, constructs and validates the full response, and stores its immutable UTF-8 JSON snapshot. An invalid internal memory snapshot is treated as a miss and replaced after successful recalculation. Errors and invalid calculated responses are not stored. Oversized responses and disabled caches still return normal validated results without retention.

The HTTP response schemas and error envelopes are unchanged. Source checksum/metadata changes, reviewed mask revisions, request options, or calculation-model version changes produce different keys. Source failures still return 503 before lookup, even with a warmed cache; invalid selections/policies return 422 and unknown IDs return 404. Geometric evaluation remains independent of mask files. Reusing calculation results does not bypass scientific limitations or accept an approximation for the caller. The catalog, raw ephemeris, and synthetic endpoints do not use this result cache.

Cache hits still perform source I/O and contract validation; the optimization avoids repeated visibility calculation. Simultaneous identical misses may calculate independently, while storage operations remain thread-safe and bounded. This process-local cache does not precompute additional sites or dates. `backend/tests/test_reference_cache_api.py` verifies hits/misses, canonical request equivalence, source/mask/model revisions, validation before lookup, mutable-result isolation, disabled/oversized storage, eviction, application isolation, and recovery from invalid responses/snapshots.

## Serve precomputed reference evaluations

Set `LUNARWINDOW_PRECOMPUTED_DIR` in the FastAPI process environment to opt into one previously generated complete bundle:

```sh
LUNARWINDOW_PRECOMPUTED_DIR=data/processed/site01-cli-example \
  python -m uvicorn lunarwindow.api.app:app --port 8000
```

Unset or blank disables persisted lookup and preserves the existing memory-cache/calculation flow. Paths are resolved in the API process working directory. For containers, the path must exist inside the API container and the bundle should be mounted read-only; deployment bundle packaging/mounting is separate from this integration. Adding a value to a local `.env` file alone does not export it into a native Uvicorn process or add a Docker mount. `get_precomputed_directory` is the server-side dependency boundary, with no additional HTTP request fields or query parameters.

Every evaluation still validates the source bundle, selects the requested range/grid, and checks terrain observer/frame compatibility and explicit approximation acceptance before persisted lookup. The resulting key includes checksums of the exact verified artifacts. The configured bundle is then fully verified on each request, before memory-cache access. An exact saved key match returns a fresh model from the checked byte snapshot and skips calculation. Saved matches return directly without populating memory cache. A valid bundle with no matching key falls through to memory cache and then calculation as needed; returned API schemas and original source/model provenance are unchanged.

There is no slicing of a larger saved range or substitution of another site, rule, sampling interval, countdown time, or mask. Each must match the complete canonical key. Corrupt, missing, incomplete, stale-source, or unsupported configured bundles produce the existing generic HTTP 503 without filesystem paths. A warm memory cache cannot hide those failures. Invalid request ranges/policies and unknown site/mask IDs retain their existing 422/404 responses before bundle lookup. The catalog, raw ephemeris, synthetic, and health endpoints remain independent of this optional result source.

Tests in `backend/tests/test_precomputed_reference_api.py` cover geometric/terrain saved hits, normalized equivalent requests, absent-key calculation and memory reuse, warm-cache failure behavior, validation order, configuration enable/disable, stale source revisions, same-read snapshot delivery, and server-only path selection.

## Offline precompute manifest contract

The [offline evaluation precompute contract, generator, verifier, loader, and CLI](precompute.md) define, produce, audit, and load `lunarwindow.precompute-manifest.v1` bundles for explicit reference evaluation jobs. They reuse cache-key identities to record source/mask checksums, request options, model version, and approximation acceptance. Each completed job records its output filename, SHA-256, and response schema version. Run/job validation rejects duplicates, inconsistent completion claims, unsafe filenames, and output/mode disagreement. The generator verifies inputs against planned identities, validates results, and checkpoints atomic writes in a fresh directory, retaining an incomplete manifest on failure. The read-only `verify_bundle` helper checks saved outputs against their checksums, response contracts, recorded jobs, verified archive samples/provenance, and reviewed masks; unsupported model versions are rejected. `load_precomputed_evaluation` verifies the complete bundle and returns a fresh matching response directly from its checked byte snapshot, or `None` for an absent key; invalid artifacts remain errors. `lunarwindow-precompute generate` accepts an explicit pending-manifest plan; `lunarwindow-precompute verify` audits a saved run. Both commands also work with `python -m lunarwindow.precompute`, require a reference archive path, and report JSON success summaries and nonzero failure codes. Models, helpers, and the packaged JSON Schema are in `backend/src/lunarwindow/precompute`. The API can opt into one bundle through `LUNARWINDOW_PRECOMPUTED_DIR` while deployment data releases remain separate.

## Synthetic scenario evaluation contract

`POST /api/evaluations` accepts the fields already defined in `src/domain/scenario.ts`. Python validates latitude [-90, 90], east-positive longitude [-180, 180], finite altitude in kilometers above the reference surface, a nonblank name up to 80 characters, and integer steps from 1 to 1440 minutes. Times must be whole-minute ISO UTC strings ending in `Z`, from 1962 onward, consistent with the ephemeris package. End must follow start; requests are limited to 31 days and 10,000 samples. Extra JSON fields and numeric strings/booleans are rejected.

Existing frontend `Scenario` request bodies remain valid. The optional `visibilityRule` is `any-disc` (default), `body-center`, or `full-disc`. The optional `asOfUtc` is a whole-minute UTC timestamp within `[startUtc, endUtc)`, defaulting to the start, and affects only countdowns. These calculation options are included in the TypeScript `EvaluationRequest` type.

Responses use `lunarwindow.evaluation.v2`, with matching TypeScript types in `src/domain/evaluation.ts`:

- `siteId`, `site`, `lat`, `lon`, `altitudeKm`, `coordinateSource`: echo the chosen demo point or custom scenario. Custom scenarios use `siteId: "custom"`; no scenario is saved.
- `dataMode: "synthetic"`: always present on evaluation and catalog responses.
- `horizon`: exactly 360 `{ az, el }` entries, ordered from azimuth 0 through 359 degrees, clockwise from north.
- `series`: UTC `t`, the existing Sun/Earth angles and angular radii, interpolated `sunHorizonEl`/`earthHorizonEl`, `hidden`/`partial`/`full` disc states, and flags `sunLit`/`earthVis` following the chosen rule. Start is included, end is excluded. A nonaligned end still includes every on-grid sample before end.
- `metrics`: duration-weighted `pctSun`, `pctEarth`, `pctBoth`, visibility hours, longest darkness/Earth-blackout/combined intervals, selected-time countdowns, and next-setting observation brackets. Durations and percentages are numbers; event-related values are null if no qualifying transition is observed in the range.
- `windows`: merged `sunlit`, `earthVisible`, `both`, `darkness`, and `earthBlackout` intervals, with durations and flags indicating unknown extents outside the requested range.
- `calculation`: the selected visibility rule, circular linear horizon interpolation, local horizontal-disc approximation, sample-and-hold time model, event bracketing, and sampling step.
- `provenance`: the generator name, requested period, UTC/end conventions, synthetic model labels, and an explicit warning.

Values repeat for identical requests, and overlapping date ranges share identical samples. Longitude and latitude vary the demo curves; altitude is echoed but has no effect. Angular radii are illustrative constants in the demo provider; the calculation engine accepts each sample's supplied radius. The engine computes metrics and partial-disc states, while the demo source remains synthetic. It does not read the real ephemeris cache or reference bundles, and it does not represent power availability or a validated radio link. Read [the visibility model](visibility.md) before interpreting sampling precision or partial visibility.

The React workspace now uses the reference endpoints (`src/lib/api-client.ts`). A synthetic-scenario client would look like this:

```ts
import type { EvaluationDataset, EvaluationRequest } from '@/domain/evaluation';

async function evaluate(
  scenario: EvaluationRequest,
): Promise<EvaluationDataset> {
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

The tests cover analytical visibility/metrics cases, the catalog, response contract, time grid, repeatability, calculation options, bounds, malformed inputs, errors, CORS, and OpenAPI. `get_provider` in `lunarwindow.api.app` is the dependency boundary for later real-data integration; the demo generator is never a fallback for failed NASA requests.
