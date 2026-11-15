# Site04 and Site23 terrain masks: PRELIMINARY

**Status: preliminary, awaiting scientific sign-off. Do not present these as validated.**

Both masks passed every integrity, observer-match, reproducibility and convergence check below. Both also have unresolved disagreements with NASA PGDA long-term visibility maps (Site04 Earth, Site23 Sun), so they stay in this `preliminary/` folder. To promote a mask after review, run `git mv` to `data/reference/terrain-masks/`. The JSON bytes, and therefore the checksums, do not change.

The masks follow the `TerrainMask` contract (`lunarwindow.terrain-mask.v1`, see `docs/terrain-mask.md`). The contract has no status field and forbids extra keys, so the "preliminary" label lives in this folder name and this README, not inside the JSON.

| Mask | Site | Trusted SHA-256 |
| --- | --- | --- |
| `lola-site04-reference-mast-0m.json` | Shackleton inner wall DEM reference point | `5c37c1528ee8160d80aa75bf069100f6216b54d6f95b0e0be474d78d8fe34dfa` |
| `lola-site23-reference-mast-0m.json` | Malapert massif DEM reference point | `d31454a199791a931a4737e911febbb5cc984e9d8124dbae6cf7ea648e174d3a` |

The same values are in the adjacent `.json.sha256` files. Check them with `shasum -a 256 -c *.sha256`. Load a mask only with `load_terrain_mask(path, expected_sha256=…)`, using the checksum from this table, never the sidecar. Neither mask is registered in `backend/src/lunarwindow/terrain/registry.py`.

## Observer

Each mask copies the observer from the archived 30-day ephemeris in `data/reference/validation-30d/<site-id>.json`. Latitude, longitude, total altitude, `coordinateSource` and site name are bit-identical to that file. The archived files still match `manifest.json`.

| | Site04 (`lola-site04-reference`) | Site23 (`lola-site23-reference`) |
| --- | --- | --- |
| Latitude (°) | −89.76674147712977 | −85.99486736492491 |
| East longitude (°) | −171.89280908299654 | −0.23460969154338968 |
| Total altitude above 1737.4 km (km) | 0.7679786376953125 | 4.78362939453125 |
| Ground height = 5 m tile centre pixel (m) | 767.9786376953125 (row 1600, col 1600) | 4783.62939453125 (row 2100, col 2100) |
| Mast | 0 m | 0 m |

The ground height equals the raw centre-pixel value in the 5 m tile, which also matches `data/reference/site-provenance.json`. The exporter re-samples the DEM and refuses to write a mask if the ground differs from the archived altitude minus the mast by more than 1 mm. An independent re-implementation reproduced the ground to within 3 × 10⁻¹² m.

## Reference frame and transformation

- **Declared frame:** `MOON_ME`, realization `DE421 (frame of the PGDA LOLA DEMs; the mask applies no frame transformation)`. Coordinates are geodetic on the 1737.4 km sphere, with east-positive longitude. This is the frame of all four LOLA products used, which are south polar stereographic on the 1737.4 km sphere. The code rejects any other projection.
- **Transformation applied: none.** The archived Horizons responses label the observer frame `MEAN_ME (high precision) {East-longitude positive}`, on the same sphere, with DE441 body positions. They do not show that this frame is DE421 `MOON_ME`.
- **Backend behaviour:** `check_terrain_compatibility` rejects both masks by default ("Frame realizations are not established as identical"). It accepts them only with `allow_mean_earth_approximation=True`. It then returns `frameStatus: "approximate"` and `transformationApplied: false`. Both outcomes were checked for both masks, and that explicit acceptance stays in the backend.

## How they were generated

DEM sources (NASA GSFC PGDA, LOLA team). The tiles were downloaded on 2026-11-15 with `lunarwindow.terrain.download`. The full-file SHA-256 of each tile matches `site-provenance.json`.

| Tier | Product | SHA-256 | Published revision |
| --- | --- | --- | --- |
| Site04, 5 m, ≤ 7.99 km | [`Site04_final_adj_5mpp_surf.tif`](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site04/Site04_final_adj_5mpp_surf.tif) (product 78) | `38ff70dbdf2f066c2cfa94a646c3a59d653ce7f6b4528b15fc1b43ee397ce758` | Last-Modified 2020-06-05T18:40:02Z, ETag `W/"2715146-17285c863d0"` |
| Site23, 5 m, ≤ 8.99 km | [`Site23_final_adj_5mpp_surf.tif`](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site23/Site23_final_adj_5mpp_surf.tif) (product 78) | `12d280a59cd7580415f6bada638d0abe025ce6727541fddf68d5dc371a6c94cf` | Last-Modified 2020-06-12T11:39:15Z, ETag `W/"43511b4-172a853aab8"` |
| 20 m, ≤ 25 km | [`LDEM_80S_20MPP_ADJ.TIF`](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF) (product 90) | `09b7ca80f9e6a146f970225d18af72fc02787669b3ef51b888e347d2b6845649` | Last-Modified 2023-07-07T22:28:19Z |
| 120 m, ≤ 200 km | [`LDEM_60S_120MPP_ADJ.TIF`](https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_60S_120MPP_ADJ.TIF) (product 90) | `894f30e2a57e02a00871d5f6f45b4fef07f6a2efa68f8bfd21a246edf944e094` | Last-Modified 2023-07-07T22:03:50Z |

The 5 m tier boundary is the edge of the 9 km window the exporter reads, minus two pixels. The Site23 tile is 21 km wide, but its 5 m tier still stops at 8.99 km.

Code: git `9fc9e0f7592d9e248a18fbd0b2337a2517994f4a` (recorded in each mask's `provenance.algorithm.version`), algorithm `lunarwindow.horizon-raycast.1`. Environment: Python 3.12.16, NumPy 2.5.4, rasterio 1.5.2 (GDAL 3.12.2). The algorithm is the same as for Site01 (see `../README.md`):

- 3,600 great-circle rays, 0.1° apart, clockwise from local north.
- Samples every 5 m from 60 m out to 200 km.
- Bilinear heights from the finest tier covering each sample.
- Exact spherical elevation angle, no refraction.
- Each whole-degree value is the maximum of the rays from az −0.5° to az +0.4°.

```sh
# from the repo root at 9fc9e0f; tiles registered in backend/src/lunarwindow/terrain/products.py
lunarwindow-terrain download Site04_final_adj_5mpp_surf Site23_final_adj_5mpp_surf LDEM_80S_20MPP_ADJ LDEM_60S_120MPP_ADJ
python scripts/export_terrain_mask.py --site-id lola-site04-reference --site-tile Site04_final_adj_5mpp_surf
python scripts/export_terrain_mask.py --site-id lola-site23-reference --site-tile Site23_final_adj_5mpp_surf
```

The defaults used were `--mast-m 0 --ray-step-m 5 --max-range-km 200 --near-field-km 25 --min-distance-m 60`, and the ephemeris directory was `data/reference/validation-30d`. The masks were written to `data/reference/terrain-masks/` and then moved here unchanged. A rerun differs only in `provenance.createdAtUtc` (2026-11-15T07:48:56Z here), and therefore in the checksum.

## Coverage and missing data

- `noDataPolicy: "reject"`: the export fails if any sample has no height in any tier.
- For both masks, all 143,960,400 samples (3,600 rays × 39,989 samples) have data. No azimuth is truncated, and every ray reaches 200 km (`minReachKm` 200.0).
- No exporter warnings were raised. The near-field DEM is available at both sites.
- The independent recomputation also found 0 missing samples at both sites.

## Review results

Evidence: `review-evidence/*.json`, produced by `scripts/review_terrain_mask.py`, `scripts/terrain_mask_clearance.py` and `scripts/independent_horizon.py`.

| Check | Site04 | Site23 |
| --- | --- | --- |
| Contract: `TerrainMask.model_validate_json`, exported JSON Schema, `load_terrain_mask` with checksum, round trip | pass | pass |
| Observer bit-identical to the archived ephemeris; archived file matches its manifest | pass | pass |
| Compatibility: rejected without opt-in, `approximate` with it, no transformation | pass | pass |
| Full DEM re-hash (all three tiers) matches the recorded SHA-256 | pass | pass |
| Regeneration with production code is byte-identical in `horizon` | pass | pass |
| Independent re-implementation (own projection, great circles, bilinear; no project code), max \|Δ\| | 0.00005° | 0.00005° |
| Variable instead of constant step, max \|Δ\| | 0.0028° | 0.0000° |
| 100 km instead of 200 km search, max \|Δ\| | 0 | 0 |
| Horizon range | +0.16° (az 240) to +32.74° (az 84) | −3.43° (az 151) to +5.65° (az 59) |
| Distance to the terrain that sets each ray's horizon: median / 90th percentile / max | 4.9 / 18.7 / 19.6 km | 0.135 / 0.70 / 4.8 km |
| Rays whose horizon is set within 200 m | 27% | 57% |

The independent difference is ≤ 0.00005°, which is the four-decimal rounding of the stored values.

### Visibility join (any-disc rule, backend engine)

| | Site04: Sun / Earth / both / longest dark | Site23: Sun / Earth / both / longest dark |
| --- | --- | --- |
| Archived 30 days, hourly, no terrain | 100 / 44.2 / 44.2 % / 0 h | 63.8 / 75.7 / 62.4 % / 241 h |
| Archived 30 days, hourly, **this mask** | **29.9 / 0.0 / 0.0 % / 505 h** | **42.1 / 42.5 / 20.6 % / 253 h** |
| One modelled year (2026-11-14 to 2027-11-14, 6 h), this mask | 12.6 / 0.0 / 0.0 % | 15.1 / 49.9 / 8.2 % |
| NASA PGDA 18.6-year average at the 120 m pixel (`AVGVISIB_75S_120M_201608`, `_EARTH`) | 11.2 / 11.4 % | 34.8 / 52.7 % |
| **Difference from PGDA** | Sun **+1.4**, Earth **−11.4** | Sun **−19.7**, Earth **−2.8** |

The one-year ephemeris uses the observer altitude rounded to 1 km (Site04) or 5 km (Site23). Each kilometre of altitude moves the Sun or Earth by less than 0.00015°. As with Site01, the PGDA comparison checks long-term plausibility. It is not validation of individual events.

### Open findings (why both stay preliminary)

- **Site04, Earth never visible vs PGDA 11.4%.** Over the modelled year, Earth's upper limb gets no closer than 0.63° below the horizon, at az 171° with Earth at 5.6° elevation. Earth stays within az 164°–180°. The result does not depend on the DEM tier or the exact pixel. Earth stays hidden with the 20 m + 120 m model (−0.62°), with the 120 m DEM alone from 120 m (−0.60°), and with the observer moved ±60 m (−0.28° to −0.97°). PGDA's 2016 product used an older DEM and an 18.6-year window, and neither explains a 0.6° gap. **Unresolved.** The Sun result agrees with PGDA (+1.4).
- **Site23, Sun 15.1% vs PGDA 34.8%.** This is a spatial-representativeness effect, not a code error:
  - The 0 m observer stands at a pixel 1.6 m below the mean height of the surrounding 240 m. 60% of that area is higher, and the local slope is 3.4°.
  - Its horizon is set by ground a median of 135 m away.
  - Running the same pipeline with only the 120 m DEM, from 120 m out, reproduces PGDA: Sun 36.3%, Earth 52.3%.
  - Moving the observer 60 m (half a PGDA pixel) changes the yearly Sun share from 0.1% to 32.5%.

  The mask is correct for this exact pixel at ground level, but it does not represent the Malapert massif's illumination.

## Height sensitivity

These are changes to the horizon relative to the 0 m mask, computed with the production code and the same DEMs. Mast rows reuse the 0 m ephemeris, which is accurate to within 0.0001° (10 m of parallax).

| Variant | Site04: max \|Δ\| (mean Δ) | Site23: max \|Δ\| (mean Δ) |
| --- | --- | --- |
| 1 m mast | 0.87° (−0.16°) | 0.95° (−0.44°) |
| 2 m mast | 1.69° (−0.27°) | 1.85° (−0.78°) |
| 5 m mast | 1.99° (−0.43°) | 3.94° (−1.42°) |
| 10 m mast | 2.17° (−0.57°) | 5.61° (−1.96°) |
| Terrain from 20 m instead of 60 m | 2.15° (+0.23°) | 1.94° (+0.53°) |
| Without the 5 m tier (20 m + 120 m only) | 0.48° (−0.04°) | 0.40° (−0.09°) |

Effect on visibility:

| Mast | Site04, 30 days | Site23, 30 days | Site23, one year |
| --- | --- | --- | --- |
| 0 m | Sun 29.9%, Earth 0% | Sun 42.1%, Earth 42.5%, both 20.6% | Sun 15.1% |
| 2 m | unchanged | Sun 54.7%, Earth 44.0%, both 26.1% | Sun 24.0% |
| 5 m | unchanged | Sun 75.1%, Earth 46.2%, both 34.6% | |
| 10 m | unchanged | Sun 78.6%, Earth 52.2%, both 39.6% | |

**Mast recommendation: keep 0 m for these reference masks.** No new ephemerides are provided.

- **Site04 is insensitive to the mast.** Its horizon is set by crater walls kilometres away.
- **Site23's main problem is not the mast.** Even at 2 m it stays 10.8 points below PGDA. The issue is that a single 5 m pixel stands in for a summit with metre-scale relief.
- **A different mast needs a real hardware height.** It should come from an agreed lander antenna or camera height, not from fitting PGDA.

To make a different mast, follow the two-step procedure in `../README.md` (site file, then `lunarwindow-ephemeris`, then the exporter with `--ephemeris-dir`). Use `--site-id`/`--site-tile` for these sites.

## Scientific limitations

- **One observer, at ground level.** Each mask is valid only for its exact centre pixel at 0 m. For Site23, the result changes greatly within 60 m. Treat it as an illustration of local-relief effects, not as the illumination of "Malapert".
- **Not a landing target.** These are reference points from DEM tile centres, not selected landing sites. The Site04 point sits on Shackleton's steep inner wall (about 32° slope), not on the rim.
- **Near terrain.** Terrain within 60 m is excluded, which avoids treating interpolation noise as obstruction. Including terrain from 20 m changes the horizon by up to about 2°. Rocks and boulders smaller than the 5 m pixels are not modelled. Beyond 25 km, the 120 m DEM smooths distant ridges.
- **Simplifications.** The bins take the maximum of the rays within each degree, which errs toward "blocked". The engine treats the Sun and Earth as horizontal discs. There is no refraction (the Moon is airless) and eclipses are not modelled.
- **Frame.** The DE421 `MOON_ME` mask is joined to Horizons `MEAN_ME (high precision)` ephemerides only by explicit approximate acceptance. The masks themselves apply no transformation.
- **Not validated against imagery.** The QuickMap comparisons in `docs/validation/` check Sun/Earth angles for camera observers about 100–144 km above the surface. They do not validate terrain shadows at these ground points. The PGDA comparison is a long-term plausibility check only.
