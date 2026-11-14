# Reproducible offline data releases

The API Docker image ships `data/releases/lunarwindow-demo-v1`: three geometric reference evaluations and the reviewed Site01 terrain case. All four use the full committed month, hourly samples, and the default `any-disc` rule. See the [release inventory, source pins, and limitations](../data/releases/README.md).

## Build and replay

The existing pending `PrecomputeManifest` is the recipe. It pins each job's site, dates, interval, visibility rule, countdown reference, source checksums, mask identity, approximation acceptance, and calculation-model version. The builder copies that exact plan into a new directory and uses the existing generator to calculate and validate outputs. A source/model identity change fails before calculation.

After bundle/source verification, the builder publishes `SHA256SUMS` containing exactly `plan.json`, `bundle/manifest.json`, and the listed output files. A failed build retains diagnostics without a successful inventory. Verification checks the inventory, plan and bundle contracts, identical ordered plan/bundle identities, verified source evidence, output provenance, and payload checksums.

`check` independently builds a candidate in temporary storage and compares exact output bytes and every manifest field except `createdAtUtc` and `completedAtUtc`. Those fields retain the actual time of each generation run. Input keys, output hashes, payloads, options, source metadata, and job order must reproduce exactly. The published release is unchanged. This verifies software reproducibility and provenance; independent observational validation remains separate.

Install or refresh the backend package to register `lunarwindow-data-release`. The same commands work with `python -m lunarwindow.precompute.release`:

```sh
python -m pip install -e ./backend

lunarwindow-data-release verify data/releases/lunarwindow-demo-v1 \
  --reference-dir data/reference/validation-30d

lunarwindow-data-release check data/releases/lunarwindow-demo-v1 \
  --reference-dir data/reference/validation-30d

lunarwindow-data-release build data/releases/lunarwindow-demo-v1/plan.json \
  --reference-dir data/reference/validation-30d \
  --output data/processed/demo-release-replay
```

`--terrain-dir` defaults to the archive directory's sibling `terrain-masks`. Builds require a fresh path. Success prints JSON and returns 0; operational/validation failures go to stderr and return 1, argument errors return 2, and interruption returns 130. There are no live NASA requests or DEM regeneration.

The shipped jobs match default full-archive requests. Other valid dates, rules, intervals, countdowns, and sites are exact-key misses and use memory cache or calculation normally. The API preserves source/model provenance and never slices another saved case. Invalid configured bundles return 503, including when a previous result is in memory.

## Deploy the packaged release

```sh
docker compose up --build -d --wait
```

The API image includes and verifies `/app/data/releases/lunarwindow-demo-v1` during its build. Its files are root-owned and readable but unwritable by the non-root API user. The image and default Compose configuration enable:

```text
LUNARWINDOW_PRECOMPUTED_DIR=/app/data/releases/lunarwindow-demo-v1/bundle
```

An explicit blank value disables persisted lookup. Compose uses an unset-only default to preserve this choice:

```sh
LUNARWINDOW_PRECOMPUTED_DIR= docker compose up -d api
```

For a custom release, verify it first, mount it read-only, and set the variable to its **container** bundle path through a deployment override. The built-in release needs no host data mount. A changed observer height, source, or model requires a new reviewed plan/release and matching artifacts.

Native startup remains opt-in:

```sh
LUNARWINDOW_PRECOMPUTED_DIR=data/releases/lunarwindow-demo-v1/bundle \
  python -m uvicorn lunarwindow.api.app:app --port 8000
```

The API response shapes, `dataMode: "reference"`, Horizons evidence, terrain provenance, approximation disclosure, and 422/404/503 behavior are preserved. The 0 m mask remains a reference case with the existing model limitations.

## CI and local checks

CI checks the release at three levels:

1. Backend tests exercise pinned coverage, checksum closure, payload replay, non-overwrite behavior, and failed publication.
2. Ubuntu/Windows Python 3.11/3.14 jobs independently rebuild the release and compare bytes, excluding only actual generation timestamps from manifest comparison.
3. Docker verifies the packaged release at build time and starts a real isolated API from that image. With calculation patched to fail, all four saved requests must return exact payloads. A missing one-hour case must calculate once and then use memory cache. The check also confirms read-only release permissions and non-root operation.

Run the packaged HTTP check without publishing ports or restarting services:

```sh
docker compose build api
docker compose run --rm -T --no-deps --entrypoint python api - \
  < scripts/check_packaged_release.py
```

For an isolated image tag, `docker run --rm -i --network none --entrypoint python IMAGE - < scripts/check_packaged_release.py` also disables external networking; localhost HTTP still reaches the temporary Uvicorn server. The script stops that server before exiting. These checks do not publish images.

To update data, create a new versioned pending plan, build a new release directory, run `verify` and `check`, review changed artifacts and scientific limitations, and update Docker/Compose release paths and coverage tests together. Generated JSON under `data/releases` is checksum-sensitive, excluded from Prettier, and marked `-text` in `.gitattributes` to preserve exact bytes across checkouts.
