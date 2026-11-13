# Ephemeris validation report

Reviewed November 13, 2026. Software: `lunarwindow-ephemeris` 0.2.0; contract: `lunarwindow.ephemeris.v2`.

## Reference dataset

The committed bundle at `data/reference/validation-30d` spans **2026-11-14 00:00 UTC through 2026-12-14 00:00 UTC, end excluded**. It contains 720 hourly samples for each of three NASA GSFC LOLA DEM center-pixel reference points: Connecting ridge (Site01), Shackleton rim (Site04), and Malapert massif (Site23).

Coordinates and surface heights were derived from the source products' actual pixel transforms and sampled heights, using the documented DE421 MOON_ME frame, south polar stereographic projection, and 1737.4 km sphere. Mast height is explicitly zero. These points are reproducible geographic references, not nominated landing sites. Original DEMs remain outside Git; `data/reference/site-provenance.json` records file hashes, projection, grid cell, and sampled height. The source products include interpolation and uncertainty; their 5 m pixel spacing is not a claim of 5 m independent measurement accuracy.

Sources: [NASA PGDA product 78](https://pgda.gsfc.nasa.gov/products/78), [product README](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/README), and the per-point product URLs in the catalog.

All six original Horizons responses are archived under `data/reference/horizons`. Dataset provenance retains source requests and response hashes. Offline tests rebuild the normalized series from those responses, verify every sample, validate the JSON contract, and compare the CSV and JSON files against the completed manifest.

## QuickMap numerical comparisons

The **3D Time and Key Geometry Info** panel in [LROC QuickMap](https://quickmap.lroc.im-ldi.com/) was inspected at each reference location with playback paused at **2026-11-14T00:00:00Z**. Crucially, that panel reports angles from the camera, which was 100-144 km above the reference sphere. It does not report angles from our DEM surface pixel.

For each case, the camera's Cartesian coordinates were preserved from the actual QuickMap URL. Latitude, longitude, and observer altitude were derived from those coordinates on the 1737.4 km sphere and supplied to a separate Horizons query. Screenshots and transcribed JSON values preserve the displayed timestamp and angles; a full accessibility snapshot is also retained for case 03. The captured URL alone does not preserve the paused time; set the UTC timestamp from the case record when reopening it. An old user-defined surface marker may remain visible in the shared scene; the **camera position**, not that marker, defines each comparison.

| Case | Nearby reference region | Camera altitude (km) | Largest absolute angle difference (deg) | Result                    |
| ---- | ----------------------- | -------------------- | --------------------------------------- | ------------------------- |
| 01   | Shackleton rim          | 144.364890           | 0.004505486                             | Pass at display precision |
| 02   | Connecting ridge        | 100.000000           | 0.004807782                             | Pass at display precision |
| 03   | Malapert massif         | 100.000000           | 0.003300457                             | Pass at display precision |

The comparison covers Sun/Earth azimuth and elevation: **12 angle comparisons**. Azimuth errors are wrapped across 0/360 degrees. The criterion is half the UI's 0.01-degree display step plus a 0.000001-degree allowance for camera-coordinate rounding: 0.005001 degrees. This is a deterministic display-rounding consistency check, not an instrument accuracy specification or an independently established ephemeris uncertainty bound.

Machine-readable results are in `quickmap-results.json`; individual measurements are in `quickmap-cases.csv`; screenshots, exact camera URLs, the case-03 UI snapshot, and matched Horizons datasets are under `evidence/`. Original matched-query responses are archived in `data/reference/quickmap-horizons`.

## Reproduce

```sh
python -m pip install -e './backend[dev,analysis]'
python -m unittest discover -s backend/tests -v
python scripts/validate_quickmap.py
lunarwindow-validate data/reference/validation-30d
lunarwindow-report data/reference/validation-30d \
  --quickmap-results docs/validation/quickmap-results.json
```

The default QuickMap replay uses committed evidence and does not contact NASA or QuickMap. `--refresh` explicitly retrieves new Horizons responses for the saved camera positions; it does not recapture the QuickMap UI. To recreate geographic reference points, install `backend[gis]` and run `python scripts/prepare_reference_sites.py`; this downloads the larger source DEMs into ignored storage. Do not change a reference observer to a surface height while retaining its camera-observer comparison result.

## Limits and next integration steps

The checks establish reproducible acquisition, contract consistency, and agreement between two tools at displayed pointing precision for three elevated observers at one timestamp. Both tools may share underlying NASA ephemerides; agreement is not wholly independent verification of those ephemerides. It does not validate the complete 30-day series against QuickMap, terrain shadowing, partial-disc visibility, eclipses, electrical power, a radio link budget, or actual mission coordinates.

The shipped plots use local horizontal planes and body centers. Earth azimuth is unwrapped only in the plot; exported values remain [0, 360). Local Earth pointing angles are not libration longitude/latitude. GIS/backend still need to agree mast height, reference-frame compatibility, horizon masks, disc rules, and event-time refinement. Team-approved landing coordinates and the proposed 2026-2030 batch remain later work.
