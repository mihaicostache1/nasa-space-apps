# Terrain-mask contract v1

`lunarwindow.terrain-mask.v1` defines the GIS-to-backend handoff for a static lunar terrain horizon. The Python contract is `TerrainMask` in `backend/src/lunarwindow/terrain/models.py`. It records one observer, one reference frame, a complete azimuth/elevation profile, and the evidence needed to trace its DEM sources and generation method.

The contract and offline loader are implemented. The first reviewed artifact is `data/reference/terrain-masks/lola-site01-reference-mast-0m.json` (see the README beside it). Checking compatibility with ephemerides, extending the HTTP API, and evaluating terrain visibility are subsequent steps. Reference evaluations currently support only `horizonMode: "geometric"`.

## Required fields

All fields below are required. Extra fields, numeric strings, booleans used as numbers, and nonfinite numbers are rejected. Human-readable text must be nonblank. There are no implicit heights, frames, or angular conventions.

| Field                | Required value or meaning                                                   |
| -------------------- | --------------------------------------------------------------------------- |
| `schemaVersion`      | `"lunarwindow.terrain-mask.v1"`                                             |
| `maskId`             | Lowercase alphanumeric slug, with optional single hyphens between segments  |
| `siteId`             | Site identifier using the same slug format                                  |
| `site`               | Human-readable site name                                                    |
| `terrainModel`       | `"dem-horizon"`                                                             |
| `observer`           | Coordinates and explicit surface/observer heights, described below          |
| `referenceFrame`     | Body, frame realization, coordinate conventions, and reference sphere       |
| `angularUnits`       | `"degrees"`                                                                 |
| `azimuthConvention`  | `"clockwise-from-local-north"`                                              |
| `elevationReference` | `"local-horizontal"`                                                        |
| `refractionModel`    | `"none"`                                                                    |
| `horizon`            | Exactly 360 ordered `{ "az": integer, "el": number }` entries               |
| `provenance`         | Creation timestamp, original DEM source evidence, and generation parameters |

## Observer and reference frame

`observer` contains:

| Field               | Meaning                                                                   |
| ------------------- | ------------------------------------------------------------------------- |
| `lat`               | Latitude in degrees, within [-90, 90]                                     |
| `lon`               | East-positive longitude in degrees, within [-180, 180]                    |
| `coordinateSource`  | Citation identifying how this observer location was obtained              |
| `surfaceElevationM` | Surface elevation in metres above the declared reference sphere           |
| `mastHeightM`       | Nonnegative observer height in metres above that surface                  |
| `altitudeKm`        | Total observer altitude in kilometres above the declared reference sphere |

`altitudeKm` must equal `(surfaceElevationM + mastHeightM) / 1000`, with an absolute rounding tolerance of `0.000001` km (1 mm). Negative surface elevations and total altitudes are allowed; the surface must remain outside the sphere's center. This tolerance checks internal height arithmetic; it does not define a tolerance for matching ephemerides. Changing the location or observer height requires a profile generated for that observer.

`referenceFrame` contains `body: "Moon"`, nonblank `name` and `realization`, `coordinateType: "GEODETIC"`, `longitudeConvention: "east-positive"`, and `referenceSurface: { "shape": "sphere", "radiusKm": <positive number> }`. The name identifies the body-fixed frame; the realization identifies its model/kernel realization. The reference radius must be supplied explicitly. The contract does not transform coordinates, interpret CRS definitions, or establish that two frame labels are equivalent.

## Horizon samples

`horizon` must contain exactly one sample at each integer azimuth, in order from 0 through 359. Do not append a duplicate 360-degree endpoint. Each `el` must be finite and within [-90, 90] degrees. Missing, null, duplicate, and unordered entries are rejected.

Azimuth increases clockwise from local geographic north: 0 is north, 90 east, 180 south, and 270 west. Raster/grid north must be converted to this convention by the producer. Elevation is relative to the observer's local horizontal plane, positive upward. Preserve negative terrain-horizon elevations; do not clamp them to zero. Refraction is excluded.

The one-degree grid matches the existing visibility engine's input shape. Future integration will use its circular linear interpolation between adjacent horizon samples, including the 359-to-0 seam. Contract validation itself does not interpolate or calculate visibility.

## Source and algorithm evidence

`provenance.createdAtUtc` records when the mask artifact was generated. `provenance.sources` must contain at least one source entry, each with:

| Field            | Meaning                                                                   |
| ---------------- | ------------------------------------------------------------------------- |
| `provider`       | Source organization                                                       |
| `productId`      | DEM product/tile identifier                                               |
| `productVersion` | Published product version or identifiable source release/revision         |
| `sourceUrl`      | Absolute HTTP(S) URL of the original DEM, without whitespace              |
| `sourceSha256`   | SHA-256 of the original DEM bytes, as 64 lowercase hexadecimal characters |
| `retrievedAtUtc` | Actual source retrieval timestamp                                         |
| `resolutionM`    | Positive native DEM pixel spacing in metres                               |
| `crs`            | Source coordinate reference system definition, such as WKT                |

List every DEM used to produce the profile. File modification times are not retrieval evidence. The source CRS describes the input DEM; `referenceFrame` describes the output observer/profile conventions. The producer must resolve any necessary transformations.

`provenance.algorithm` requires:

| Field            | Meaning                                                                      |
| ---------------- | ---------------------------------------------------------------------------- |
| `name`           | Generation algorithm/tool name                                               |
| `version`        | Reproducible release or source revision identifier                           |
| `curvatureModel` | `"spherical"` or `"quadratic-drop"`, using the declared reference sphere     |
| `rayStepM`       | Positive sampling distance along each terrain ray in metres                  |
| `maxDistanceM`   | Positive maximum terrain search distance in metres, at least `rayStepM`      |
| `noDataPolicy`   | `"reject"`: the producer must reject profiles with required missing DEM data |

These fields declare the method used; the backend does not execute or verify that method in this step. The search distance and sampling step describe the profile's limits. Missing DEM coverage must not be represented by fabricated zero elevations.

All artifact timestamps use valid ISO UTC strings with seconds and a trailing `Z`, for example `2026-11-14T12:34:56Z` or `2026-11-14T12:34:56.123Z`. Up to six fractional-second digits are accepted. Timezone offsets are rejected. These timestamps are independent of the whole-minute ephemeris sample grid.

## Load the reviewed Site01 mask offline

`load_terrain_mask(path, *, expected_sha256)` in `backend/src/lunarwindow/terrain/loader.py` loads one explicit file and returns its complete `TerrainMask` model:

```python
from pathlib import Path

from lunarwindow.terrain import load_terrain_mask

mask = load_terrain_mask(
    Path("data/reference/terrain-masks/lola-site01-reference-mast-0m.json"),
    expected_sha256="4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d",
)
```

The expected checksum is required and must be 64 lowercase hexadecimal characters. Supply it from the reviewed handoff or a trusted configuration. The loader does not derive the expected checksum from the file or automatically trust an adjacent sidecar. Changing even JSON whitespace requires reviewing and supplying the new artifact checksum.

The loader reads the file once, checks the SHA-256 of those exact bytes, then validates the same contents with `TerrainMask`. It preserves the observer, all horizon values (including negative elevations), frame declarations, and DEM/algorithm provenance. There are no downloads, writes, cache changes, or synthetic/geometric fallbacks. Relative paths resolve from the caller's current directory; absolute or mounted-data paths work too.

Invalid expected checksums raise `ValueError` before reading. Missing/unreadable files, checksum mismatches, malformed JSON/encoding, unsupported schema versions, and invalid mask contracts also raise `ValueError` with the `Cannot load terrain mask` prefix and the underlying cause. An artifact whose checksum matches must still satisfy the full contract.

This verifies artifact integrity and contract validity. It does not re-hash the original DEMs, recompute terrain rays, authenticate scientific claims, or approve the mask/ephemeris frame relationship. Those source checks remain in the GIS handoff evidence; observer and frame compatibility are a separate backend task. Preserve the declared `MOON_ME` / DE421 metadata when loading this mask.

The reviewed mask is for ground + 0 m mast. Its README records sensitivity to near terrain, exclusion of terrain within 60 m, and a horizon change of up to 1.9 degrees for a 2 m mast. A new observer height requires a separately reviewed mask and matching ephemerides. Loading this reference artifact does not make it a prediction for a real lander antenna.

Run the focused offline tests with:

```sh
python -m unittest discover -s backend/tests -p test_terrain_loader.py -v
```

They load the committed artifact with the pinned handoff checksum, validate the exported JSON Schema, preserve all values and provenance, reject damaged files and invalid contracts even with recomputed checksums, and ensure hashing and validation use the same file snapshot. Docker tests use the existing `LUNARWINDOW_REFERENCE_DIR` configuration to find the committed artifact.

## Validate or export the schema

After installing the backend package, a producer or backend caller can validate an already decoded payload:

```python
from lunarwindow.terrain import TerrainMask

mask = TerrainMask.model_validate(payload)
# For a JSON string or bytes:
mask = TerrainMask.model_validate_json(json_payload)
```

Both methods raise Pydantic `ValidationError` on invalid input. Validation does not mutate the supplied payload or access files/network services.

The same model exports a JSON Schema for other tools:

```python
import json

from lunarwindow.terrain import TerrainMask

print(json.dumps(TerrainMask.model_json_schema(), indent=2))
```

The schema expresses field types, required metadata, ranges, and profile length. Use Python validation for the additional cross-field height arithmetic, physical surface radius, azimuth ordering, URL/calendar checks, and ray-step/search-distance relationship. Structural validity alone does not authenticate a source, verify its checksum, confirm observer compatibility, or establish scientific accuracy. The fixture in `backend/tests/test_terrain_contract.py` is synthetic contract-test data only.
