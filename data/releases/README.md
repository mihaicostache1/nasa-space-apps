# Reviewed demo data releases

`lunarwindow-demo-v1` contains four default `any-disc` evaluations. These are sourced DEM reference points, not approved landing targets.

| Site                    | Horizon          | Observer                                |
| ----------------------- | ---------------- | --------------------------------------- |
| `lola-site01-reference` | Geometric        | Archived Site01 observer                |
| `lola-site04-reference` | Geometric        | Archived Shackleton inner-wall observer |
| `lola-site23-reference` | Geometric        | Archived Malapert observer              |
| `lola-site01-reference` | Reviewed terrain | Same Site01 ground + 0 m mast observer  |

All jobs cover `[2026-11-14T00:00:00Z, 2026-12-14T00:00:00Z)` at 60-minute intervals: 720 samples, countdown reference at the range start. Exact source/mask checksums, calculation version, options, and terrain approximation acceptance are pinned in `lunarwindow-demo-v1/plan.json`.

- `plan.json`: explicit pending job recipe, retained unchanged for replay.
- `bundle/manifest.json`: actual run timestamps, complete job records, output hashes.
- `bundle/<key-digest>.json`: complete API responses and original source/model provenance.
- `SHA256SUMS`: exact plan, bundle-manifest, and output checksum inventory.

Terrain records the reviewed DE421 `MOON_ME` frame and an explicitly accepted approximation to Horizons' high-precision Mean Earth implementation, with no transformation applied. The mask uses the archived 0 m mast and retains its near-field limitations. A 2 m mast can shift the horizon by up to 1.9° and requires newly matched artifacts. See the [mask README](../reference/terrain-masks/README.md) and [regression evidence](../../docs/validation/terrain-regression.md).

Verify and rebuild into temporary storage without modifying the release:

```sh
python -m lunarwindow.precompute.release check data/releases/lunarwindow-demo-v1 \
  --reference-dir data/reference/validation-30d
```

Output bytes and manifest job semantics must reproduce exactly. Actual run timestamps remain audit metadata and differ on replay; whole-release timestamp bytes are not claimed reproducible. Runtime files in the API image are root-owned and read-only to its non-root user. Generated JSON is excluded from automatic formatting so its checksums remain intact.

Publish changes under a new reviewed release version. Tooling never overwrites existing release directories. See [build, deployment, and CI details](../../docs/data-releases.md).
