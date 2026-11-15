# Surface pointing and terrain validation

**Status: partial — surface cross-tool comparisons pass; independent terrain evidence is pending.**
No reviewed same-observer, same-time external terrain measurements are available.
The report deliberately sets `independentTerrainValidationComplete: false`. Passing
CI means the recorded comparisons replay correctly; it does not mark the scientific
validation milestone complete.

## What was calculated independently

A separate program, [build_surface_spice_reference.py](../../scripts/build_surface_spice_reference.py),
uses NAIF CSPICE through SpiceyPy 8.0.0. It imports no LunarWindow runtime modules,
does not call Horizons and does not read its archived angles as expected values.
Only observer coordinates, altitude and UTC sample times come from the source archives.

The oracle covers all **720 hourly samples at each of three actual surface observers**
from 2026-11-14 00:00 UTC through 2026-12-14 00:00 UTC, end excluded. The reference
observers retain their sourced DEM ground height plus **0 m mast**, including the
Site01 mask's exact observer. These are not the earlier QuickMap camera observers
100–144 km above the surface.

Inputs and hashes are pinned in [surface-science-inputs.json](surface-science-inputs.json).
The reference uses the official NAIF DE440s position SPK, DE440 lunar orientation
binary PCK, lunar frame kernel, body radii PCK and leap-second kernel. For each body
and UTC it calls `azlcpo` with a fixed observer, `CN+S` reception corrections, clockwise
azimuth from north and elevation above local horizontal. The observer is constructed
on the 1737.4 km sphere; there is no atmospheric refraction. Angular radii are
independently calculated as `asin(body radius / observer-to-body range)`, using
695700 km for the Sun and 6378.137 km for Earth's equatorial radius.

The [NAIF azlcpo documentation](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/azlcpo_c.html)
defines this constant-position surface-observer calculation. The
[Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html) describes its apparent
AZ/EL, angular diameter and lunar coordinates. The
[NAIF lunar frame kernel](https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_de440_250416.tf)
maps `MOON_ME` to `MOON_ME_DE440_ME421`, using the DE440 PA orientation with a fixed
rotation closely aligned with DE421 ME. The Horizons manual also describes its lunar
mean-Earth frame in terms of the DE421 standard and DE440 PA orientation. A DE441
body-position header alone does not identify a different lunar ME orientation.
**No production frame-compatibility policy was relaxed:** API callers still explicitly
accept the existing approximation; no unperformed coordinate transformation is claimed.

## Measured results

The [reference evidence](evidence/surface-spice-reference.json) and its
[checksum](evidence/surface-spice-reference.json.sha256) preserve all 2160 independently
calculated samples, six quantities each. The replay verifies the input/generator/
kernel metadata, evidence bytes, source archives, observers and exact UTC grids.
Azimuth differences wrap across 0/360. Non-finite data and mismatched grids fail.

| Surface observer              | Samples | Largest absolute AZ/EL difference (degrees) |
| ----------------------------- | ------: | ------------------------------------------: |
| Site01, Connecting ridge      |     720 |                          0.0000005248653281 |
| Site04, Shackleton inner wall |     720 |                          0.0000005245573220 |
| Site23, Malapert massif       |     720 |                          0.0000005290760328 |

All **12960 angle/radius comparisons** pass the predeclared engineering screening
envelopes: 0.001° for pointing and 0.00001° for angular radius. These are comparison
criteria, not uncertainty estimates, instrument accuracy, or thresholds tuned to
these residuals. The largest angular-radius difference is approximately
0.0000001331°. Exact values and worst-case UTCs are in
[surface-science-results.json](surface-science-results.json).

This is an independent software path, **not independent observational truth**.
Both tools share JPL ephemeris foundations. The SPICE calculation uses DE440s and
CN+S, while the archived Horizons body positions use DE441 and its apparent-angle
model also includes gravitational light deflection. SPICE CN+S does not include that
deflection. Small residuals do not establish absolute ephemeris or terrain accuracy.

## Terrain: what passes and what remains

The replay also joins the SPICE directions/radii with the actual backend engine:
three geometric sites and reviewed Site01 terrain, each under any-disc, body-center
and full-disc rules. A separate 50-digit decimal horizon interpolation and limb
threshold calculation supplies expected flags and duration counts. All **17280
sample/body flags** and the Sun/Earth/joint duration totals agree across the twelve combinations.

The report records proximity to a conservative screening envelope, including the
horizon's change over the azimuth envelope and elevation/radius tolerances. Three
Site01 terrain full-disc sample/body classifications lie within that envelope even
though their exact flags agree. Those results remain sensitive to the model. The
checks use the same mask as the backend, so they establish **model consistency**,
not an independently measured skyline, actual shadows, radio-link availability or
sub-hour event timing. The 0 m mast and documented height sensitivity remain.

The existing [QuickMap evidence](report.md) is elevated-camera pointing evidence.
The existing [PGDA comparison](terrain-results.json) compares one modeled year
at six-hour sampling to long-term map averages with different observer/DEM
assumptions. NASA's [PGDA product description](https://pgda.gsfc.nasa.gov/products/69)
explains the long-period illumination products. These remain contextual checks and
are not substituted for a dated surface observation.

## Reproduce offline

Normal replay needs the existing backend environment, **not SpiceyPy, kernels or
network access**:

```sh
.venv/bin/python scripts/validate_surface_science.py \
  --output data/processed/surface-science-report.json \
  --requests-output data/processed/terrain-observation-request.json
```

Exit codes: 0 means the available recorded comparisons pass, with missing evidence
still explicitly reported; 1 means a comparison or evidence/integrity check failed;
2 means required terrain evidence is absent/incomplete. To enforce completion:

```sh
.venv/bin/python scripts/validate_surface_science.py \
  --require-terrain-evidence \
  --output data/processed/surface-science-required.json
```

The last command currently returns **2**. GitHub's Python matrix runs the ordinary
offline replay and uploads its explicitly partial report. It installs no SPICE
runtime and makes no network requests for this step.

## Regenerate the independent reference explicitly

Use a separate Python 3.12 environment, as used for the recorded reference:

```sh
python3.12 -m venv /tmp/lunarwindow-science-venv
/tmp/lunarwindow-science-venv/bin/python -m pip install spiceypy==8.0.0
mkdir -p data/raw/science-kernels
```

Download the five official URLs listed in `surface-science-inputs.json` into that
kernel directory, preserving their filenames. They total approximately 46 MB.
The generator verifies every file size and SHA-256 before loading it. Kernels stay
outside Git. Source URLs are fixed named releases; no `latest` alias is used.

```sh
/tmp/lunarwindow-science-venv/bin/python scripts/build_surface_spice_reference.py \
  --kernel-dir data/raw/science-kernels \
  --output data/processed/surface-spice-reference.candidate.json
```

The optional generation step uses the separately installed SpiceyPy; production
backend dependencies remain unchanged. Software versions and generator/kernel/source
hashes are preserved in the generated evidence. Compare numeric values/conventions
and review the diff before replacing the committed evidence and checksum. Generation
UTC and environment metadata can differ between otherwise equivalent runs. Do not
update source pins or tolerances merely to hide a failed comparison.

SPICE is provided by NASA/JPL NAIF; SpiceyPy is the Python wrapper described by
[Annex et al., JOSS 02050](https://doi.org/10.21105/joss.02050). See also
[NAIF acknowledgement guidance](https://naif.jpl.nasa.gov/naif/credit.html).

## Obtain the missing independent terrain evidence

[terrain-observation-request.json](terrain-observation-request.json) supplies four
candidate UTCs and the exact Site01 observer, covering Sun visible/blocked and
Earth visible/blocked under the any-disc rule. Candidate states are explicitly
**model predictions**, not measurements; reference fields remain null. Some UTCs
are future dates relative to capture preparation and need an independent dated
terrain simulation, not a claimed photograph of a future event.

Ask the GIS reviewer for an independent render/export at those surface coordinates
and times, preserving observer height, reference sphere/frame, finite-disc definition,
DEM/version, method, original screenshot/export and review notes. The result must
refer to visibility at the surface observer, not to the 3D viewing camera. A body
center above the local horizontal is not a finite-disc terrain visibility measurement.

The [JSON Schema](terrain-observations.schema.json) describes the review handoff:

- Top-level `schemaVersion: "lunarwindow.terrain-observations.v1"` and `observations`.
- Each record identifies the case, body, exact UTC sample, boolean `visible`, and
  exact numeric observer from the request file.
- `observerKind: "surface"`, `quantity: "terrain-visibility-at-observer"`,
  `visibilityRule: "any-disc"`, `bodyDefinition: "finite-disc-any-part"`,
  `refractionModel: "none"`, `referenceFrame: "MOON_ME_DE421"`, and
  `referenceRadiusKm: 1737.4` make the compared quantity explicit.
- `sourceType` is `dated-terrain-simulation` or `surface-observation`. Long-term
  average maps are not accepted as instantaneous visibility.
- Source URL/version, DEM description, method, frame assessment, independence
  statement, reviewer, UTC review time and notes preserve the scientific review.
  `independentOfLunarWindow` must be a strict boolean true.
- `evidencePath` names a nonempty file under `docs/validation/evidence`, with its
  actual SHA-256. Missing, changed or out-of-directory evidence is rejected.

Place the reviewed file and evidence in Git, then run:

```sh
.venv/bin/python scripts/validate_surface_science.py \
  --terrain-evidence docs/validation/terrain-observations.json \
  --require-terrain-evidence \
  --output data/processed/surface-science-reviewed.json
```

Do not create `terrain-observations.json` by copying our predictions. There is
currently no such reviewed file. The validator rejects camera/average/self-derived
records, coordinate/height/frame/time mismatches, duplicate case IDs, and invalid
booleans. A disagreement is reported as a failure, never rewritten as agreement.
Completing the four recorded states gives `pass-recorded-cases`; this is still a
limited case comparison, not certification of all times or a mission site.

The tool checks declared comparability and file integrity. It **cannot authenticate
reviewer identity, interpret an image, or independently prove a declaration of
independence**. Those require scientific review of the source evidence. Photometric
thresholds, time precision, DEM differences and any applicability of the local
horizontal-disc approximation must be addressed in that review.
