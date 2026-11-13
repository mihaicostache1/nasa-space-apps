# QuickMap validation protocol

Status: **not performed**. No agreement values or pass claims have been invented. Archived Horizons tests verify ingestion and contracts, not an independent QuickMap comparison.

Reference application: [LROC QuickMap](https://quickmap.lroc.im-ldi.com/) (the older ASU URL redirects here). The precise tools/layers available must be checked in the live interface when performing validation.

## Prepare comparable cases

Use 2-3 GIS-verified coordinates: one near-side reference, one polar point near a visibility boundary, and one contrast case. Record coordinates and observer altitude rather than relying on the center of a named region. The illustrative `polar-example` catalog entry is suitable for smoke testing only.

For each comparison, record UTC time, QuickMap share URL, exact layer/tool, dataset/version/resolution, observer elevation/mast height, lunar frame/reference sphere, and whether the reported value refers to a body center, limb, or illumination fraction. Capture evidence with a screenshot or export and retain the original Horizons response hash.

## Compare like quantities

1. If the selected QuickMap tool exposes Sun/Earth azimuth and elevation for a date/time, compare those angles against the same Horizons sample with terrain disabled or otherwise matched. Use a wrapped azimuth difference: `((a - b + 180) % 360) - 180`. Near zenith/poles, check whether azimuth itself is well-defined.
2. If it provides only a dated terrain illumination result, compare to the backend's terrain-aware visibility result after masks and body-disc rules are integrated. Raw center elevation alone is insufficient.
3. If a layer is an average over a long period, use it only as a contextual sanity check. It cannot verify an hourly sample or event time.
4. If no equivalent quantity is available, record `not-comparable`; do not infer a numerical error from visual shading.

Agree an acceptance tolerance before assessing results, based on the reference's precision, time resolution, frame, DEM, and visibility definition. Do not invent a generic angular threshold that implies more accuracy than the compared products provide. Hourly horizon crossings need time bracketing or finer sampling.

## Record results

Use `quickmap-cases.csv` as the worksheet. Rows start as `pending` with blank measurements. Record expected/reference values, calculated values, differences, an agreed tolerance, evidence location, and reviewer notes. Use `pass`, `fail`, or `not-comparable` only after the evidence is recorded.

Before claiming validation in the pitch, have at least one reproducible case with a concrete quantity, matched assumptions, evidence, measured difference, and agreed tolerance. Describe an illumination-map visual check as a sanity check rather than precise independent ephemeris validation.
