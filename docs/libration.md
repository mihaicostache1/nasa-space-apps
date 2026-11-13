# Libration notes for P1 and Learn mode

## Explanation

The Moon's rotation keeps roughly the same hemisphere facing Earth, but Earth's direction at a fixed lunar surface point varies over time. Orbital geometry and lunar orientation produce the apparent wobble described as libration. At sites near the edge of Earth visibility, including polar locations, this changing direction matters for Earth rise/set and terrain obstruction.

NASA's [Earth motion in the lunar sky explanation](https://starchild.gsfc.nasa.gov/docs/StarChild/questions/question58.html) describes this changing view. The [2026 NASA SVS visualization](https://svs.gsfc.nasa.gov/5587) supplies an accessible illustration and describes sub-Earth coordinates as a measure of libration.

## Implementation rule

Use time-dependent Earth target `399` observed from the actual lunar surface coordinates. Do not assume Earth has a constant azimuth/elevation, and do not add an extra sinusoidal "libration correction" to a Horizons result. The query already uses the provider's time-dependent ephemeris and lunar orientation model.

The [Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html), under coordinate-center selection, lunar reference frames, and observer quantity 4, defines the local angles and lunar mapping convention. Preserve the model actually reported in each response. The archived 2026 smoke responses report `MEAN_ME (high precision)` and center radii of 1737.4 km; these are reported metadata, not a model hardcoded by our parser.

The CSV's `earthAz` and `earthEl` are local pointing angles. They are not the Moon's libration longitude/latitude and are not exported as those quantities. If the team wants an explicit libration plot, agree on a sub-Earth coordinate definition and obtain an appropriate separate reference series.

## What to show

The committed `data/reference/validation-30d/pointing-reference.png` and SVG now show a real 30-day example for three NASA LOLA reference grid cells. The matching JSON/CSV series, archived Horizons responses, and reproducible source manifests are shipped with it. Regenerate the figure with `lunarwindow-report data/reference/validation-30d --quickmap-results docs/validation/quickmap-results.json`. The figure's Earth azimuth is unwrapped across north for continuity; exported azimuths remain in [0, 360).

For a verified polar point, plot Earth elevation over at least a lunar month and overlay that site's terrain horizon evaluated at Earth azimuth. A flat 0-degree line can explain the geometry first; label it as the local horizontal plane. Use real exports for the animation rather than an assumed wobble period/amplitude.

Solar availability and direct-to-Earth communication require additional checks beyond pointing angles. Body-disc visibility, eclipses, terrain, antenna geometry, specific ground stations, and link budgets are separate integration decisions. Refine event timing around crossings rather than describing hourly samples as exact rise/set predictions.
