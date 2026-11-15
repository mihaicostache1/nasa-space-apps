# Reviewed reference artifacts

This small committed bundle is separate from disposable exports under `data/processed`.

- `sites.nasa.json`: three center-pixel geographic reference points from NASA LOLA Site01, Site04, and Site23 DEMs. Their sampled surface heights use a 1737.4 km sphere with zero mast height. These are not approved landing targets.
- `site-provenance.json`: source product URLs, full original DEM checksums, projection/transforms, exact grid cells, and sampled heights. Original DEMs stay in ignored `data/raw/lola`.
- `horizons/`: six original responses used for the 30-day surface-reference dataset, each with URL, retrieval time, exact response text, and hash.
- `validation-30d/`: complete JSON/CSV bundle, manifest hashes, 720 samples per point, PNG/SVG pointing figure, and validation summary. Interval: 2026-11-14 through 2026-12-14 UTC, end excluded.
- `terrain-masks/`: the reviewed Site01 `TerrainMask` (0 m mast) with its checksum and README. `terrain-masks/preliminary/` holds the Site04 and Site23 masks, which have open review findings, together with their review evidence.
- `quickmap-horizons/`: six original responses for the three separate elevated camera-observer comparisons. Their camera heights differ from the surface-reference dataset.

Verify without a network connection:

```sh
lunarwindow-validate data/reference/validation-30d
python scripts/validate_quickmap.py
```

See [the validation report](../../docs/validation/report.md) for measured differences, evidence, and limits. Generated files here are excluded from automatic formatting to preserve manifest/evidence checksums. Review a new bundle and regenerate its manifest whenever updating its JSON/CSV contents; do not edit the data files manually.
