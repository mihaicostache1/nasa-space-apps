# Visibility, metrics, and operating windows

The reusable calculation engine in `backend/src/lunarwindow/visibility` accepts ephemeris samples and an ordered 360-point horizon, then returns visibility states, metrics, windows, and setting-event brackets. FastAPI uses it for synthetic scenarios and for `POST /api/reference/evaluations`, which runs verified archived NASA samples against an explicitly selected flat zero-degree horizon or the reviewed Site01 terrain mask. Terrain mode verifies the mask checksum and observer compatibility, and requires explicit acceptance of the frame approximation before calculation.

## Inputs and horizon interpolation

`calculate_visibility(series, horizon, period, rule="any-disc", as_of_utc=None)` accepts:

- `series`: the P1 fields `t`, `sunAz`, `sunEl`, `earthAz`, `earthEl`, `sunAngularRadiusDeg`, and `earthAngularRadiusDeg`. Numeric values must be finite, azimuths in [0, 360), elevations in [-90, 90], and radii in (0, 90). Precomputed flags are rejected so stale visibility cannot enter a new calculation.
- `horizon`: exactly 360 `{ az, el }` points, ordered from 0 through 359 degrees. Negative elevations are preserved. Missing, duplicate, unordered, and nonfinite entries fail validation.
- `period`: the existing Python `TimeRange`. Samples must cover its complete start-inclusive, end-exclusive grid; missing, extra, duplicate, or off-grid times fail explicitly. No gaps are filled.
- `rule`: `any-disc`, `body-center`, or `full-disc`.
- `as_of_utc`: optional whole-minute UTC timestamp in `[startUtc, endUtc)`, defaulting to the range start. It affects countdowns only.

Azimuth is clockwise from local north. The mask elevation at a fractional azimuth is linearly interpolated between neighboring entries, including from 359 degrees back to 0. The engine uses the mask's existing reference plane and observer height; it does not generate terrain profiles or apply an extra mast correction.

## Disc model and visibility rules

Let `c = body elevation - interpolated horizon elevation` and `r = supplied angular radius`. The model treats the horizon as horizontal across the body's disc at its center azimuth:

| Rule          | Visible when | Interpretation                        |
| ------------- | ------------ | ------------------------------------- |
| `any-disc`    | `c + r > 0`  | Some disc area clears the horizon     |
| `body-center` | `c > 0`      | The center clears the horizon         |
| `full-disc`   | `c - r >= 0` | The entire modeled disc is unobscured |

`any-disc` is the default, so partial sunlight counts as a visible interval. Both `sunLit` and `earthVis` follow the selected rule. Independent `sunVisibility` and `earthVisibility` fields describe the disc as `hidden`, `partial`, or `full`: upper-limb tangency is hidden because it exposes no area; lower-limb tangency is full because it hides no area. Each sample also reports `sunHorizonEl` and `earthHorizonEl` for plotting and inspection.

The angular radii come from the supplied series, rather than a fixed Sun-size assumption in the engine. P1 derives them from Horizons' equatorial angular diameter quantity 13; see the [JPL Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html).

This local horizontal-disc approximation does not trace the terrain across the disc's width, compute a visible-area fraction, or model eclipses. Time counted as partially sunlit is not a prediction of full solar power. Earth-disc visibility is a geometric proxy, not a link budget or proof that a particular ground station is accessible. Demo evaluations use illustrative radii and a synthetic mask with `dataMode: "synthetic"`. Reference evaluations use archived per-sample radii with `dataMode: "reference"`: geometric v1 uses a zero-degree horizon; terrain v2 uses the reviewed mask and includes its complete provenance and approximate frame assessment. The Site01 mask is for a 0 m mast and excludes terrain within 60 m; changing observer height requires new matching source artifacts.

## Time model and percentages

The engine holds each observed state on `[sample time, next sample time)`. The final state is held only until the requested end. It does not interpolate a sub-step crossing time or extrapolate beyond the range. `calculation.timeModel` identifies this as `sample-and-hold`; `stepMinutes` records the resolution. Crossings and short interruptions between observations can be missed, and all durations inherit that sampling limitation.

Percentages use **duration**, not the fraction of samples:

```text
interval seconds = min(sample time + step, requested end) - sample time
pctSun   = 100 × sunlit interval seconds / requested range seconds
pctEarth = 100 × Earth-visible interval seconds / requested range seconds
pctBoth  = 100 × simultaneously visible interval seconds / requested range seconds
```

For a 2.5-hour range at hourly steps with Sun flags `[true, false, true]` and Earth flags `[false, true, true]`, the bins last 1, 1, and 0.5 hours. The results are 60% sunlight, 60% Earth visibility, and 20% overlap. Counting samples instead would overstate the last bin.

Percentages describe visibility under the selected rule. They do not weight partial-disc intervals by illuminated area. No arbitrary combined score is introduced; `pctBoth`, `bothHrs`, and `longestBothHrs` describe the overlap directly.

## Metrics and windows

`metrics` contains:

| Fields                                                        | Meaning                                                |
| ------------------------------------------------------------- | ------------------------------------------------------ |
| `evaluatedHrs`                                                | Duration of the requested range                        |
| `sunlitHrs`, `earthVisibleHrs`, `bothHrs`                     | Visibility duration under the selected rule            |
| `pctSun`, `pctEarth`, `pctBoth`                               | Corresponding percentages in [0, 100]                  |
| `longestDarkHrs`, `longestEarthBlackoutHrs`, `longestBothHrs` | Longest contiguous intervals within the range          |
| `asOfUtc`                                                     | Reference timestamp for countdowns                     |
| `nextSunset`, `nextEarthset`                                  | First subsequent observed setting's upper bracket time |
| `hoursToSunset`, `hoursToEarthset`                            | Hours from `asOfUtc` to that upper bracket endpoint    |
| `nextSunsetBracket`, `nextEarthsetBracket`                    | The previous and current observations around the event |

Durations and percentages are numeric, including real zeros. Setting fields, corresponding countdowns, and brackets are null when there is no qualifying transition in the available range. Null does not mean the body never sets outside that range.

`windows` contains five lists: `sunlit`, `earthVisible`, `both`, `darkness`, and `earthBlackout`. Adjacent active bins are merged. Each window includes:

```json
{
  "startUtc": "2026-11-14T00:00:00Z",
  "endUtc": "2026-11-14T02:00:00Z",
  "durationHrs": 2,
  "startTruncated": true,
  "endTruncated": false
}
```

The interval is half-open. `startTruncated` means it is active at the first observation, so its earlier extent is unknown. `endTruncated` means it reaches the requested end, so its later extent is unknown. A longest gap touching a range boundary is therefore an observed portion; inspect the corresponding windows for truncation. Empty visibility lists mean no intervals qualified in the range.

## Setting times and countdowns

For a visible observation at 01:00 followed by a hidden observation at 02:00, the engine reports:

```json
{
  "nextSunset": "2026-11-14T02:00:00Z",
  "nextSunsetBracket": {
    "afterUtc": "2026-11-14T01:00:00Z",
    "byUtc": "2026-11-14T02:00:00Z"
  }
}
```

This brackets a transition in `(afterUtc, byUtc]`; 02:00 is the first sampled hidden state, not an exact predicted sunset. At `asOfUtc: 01:30`, `hoursToSunset` is 0.5 hours to the upper bound. The event may already have occurred within the bracket. A selection exactly at the upper bound yields a zero countdown; a later selection searches for the next falling transition, including after a subsequent rise. The range end is never synthesized as a sunset or Earthset.

The same rules apply to Earth. For full-disc or body-center mode, a “setting” means loss of visibility under that rule, which can occur before the upper limb disappears.

## API and migration from task 1

Both `POST /api/evaluations` and `GET /api/sites/{site_id}` accept the optional `visibilityRule` and `asOfUtc` fields/parameters. Existing scenario request bodies remain valid. See [API setup and examples](backend-data.md).

Responses now declare **`lunarwindow.evaluation.v2`** because the default visibility rule and horizon interpolation changed. Update consumers of v1 as follows:

1. Use the updated types in `src/domain/evaluation.ts`. Percentage and duration metrics are required numbers; only event-related values can be null.
2. Read the selected rule from `calculation.visibilityRule`. The former `provenance.visibilityRule` string is removed. `calculation` also declares the disc, horizon interpolation, and timing models.
3. Consume `windows`, disc states, and interpolated horizon elevations. Use the bracket fields when displaying event-time precision.
4. Preserve `dataMode` and source provenance. The calculations are implemented, but the demo's source angles, horizon, radii, and coordinates remain synthetic/illustrative. Selecting `body-center` restores center-based policy but still uses the new circular horizon interpolation.

The real ephemeris contract remains `lunarwindow.ephemeris.v2`; no P1 data files or source provenance are changed. The calculation engine never retrieves data or writes files. A later provider can supply validated real samples and GIS masks through the same function.

## Python use and verification

```python
from lunarwindow.ephemeris.models import TimeRange
from lunarwindow.visibility import calculate_visibility

# dataset is a validated P1 export; mask is an ordered GIS profile.
source = dataset["provenance"]
period = TimeRange(source["startUtc"], source["endUtc"], source["stepMinutes"])
result = calculate_visibility(dataset["series"], mask, period, rule="any-disc")
print(result.metrics.pctBoth)
```

The caller retains the dataset and mask provenance. The returned models are independent of FastAPI, so batch/precompute workers can reuse them. The algorithm runs in linear time in the number of samples; it has no network or database dependency.

```sh
python -m unittest discover -s backend/tests -v
python -m ruff check backend scripts
python -m ruff format --check backend scripts
docker compose run --build --rm ephemeris-test
```

Analytical tests cover constant visibility/darkness, partial and tangent disc states, all three policies, fractional and wraparound azimuths, negative horizons, weighted partial bins, contiguous and clipped windows, countdown selections, invalid grids/masks/numbers, repeatability, input preservation, and compatibility with an archived real P1 dataset. HTTP tests verify both routes, options, response contracts, errors, and metric/window consistency.

The [dedicated terrain regression suite](validation/terrain-regression.md) adds hand-calculated sector blocking and a fixed 720-hour Site01 baseline across geometric/terrain modes and every visibility rule. Its expected metrics and windows come from a separate decimal/NumPy derivation, with pinned source hashes and no production-engine imports. The API is checked against those fixed expectations and must preserve the original source evidence and frame limitations. This verifies model implementation, rather than physical terrain accuracy.
