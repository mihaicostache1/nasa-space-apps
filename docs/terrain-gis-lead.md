# Mihai: Terrain/GIS lead

This work package covers role 2 in the LunarWindow team plan: LOLA elevation download, the horizon-mask algorithm, and sourced site coordinates. It also covers the plan's later P2 slots: custom-coordinate support (hours 24–32) and horizon data for the sky dome (hours 32–40).

Team priority #5 asks for **one correct topographic example rather than many uncertain ones**. The deliverable for integration is therefore a single validated mask for the `lola-site01-reference` point. Horizons for the other curated sites are produced by the same code but remain **preliminary**: useful for exploration, not presented as validated results.

## Deliverables

| Deliverable              | Location                                                                                       | Status                                               |
| ------------------------ | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| LOLA download, checksums | `lunarwindow-terrain download`, `terrain/download.py`                                          | Resumable, segmented, SHA-256 sidecars               |
| Horizon-mask algorithm   | `terrain/horizon.py`, `terrain/geometry.py`                                                    | Exact spherical ray casting, 5 m / 20 m / 120 m DEMs |
| Handoff contract         | `terrain/models.py`, `horizon.schema.json`, `src/domain/horizon.ts`                            | `lunarwindow.horizon.v1`                             |
| Site coordinates         | `data/sites.curated.json`, `data/sites.artemis-regions.json`, `data/sites.shackleton-rim.json` | 17 sourced sites                                     |
| **Validated demo mask**  | `data/reference/terrain-masks/lola-site01-reference-mast-0m.json` + README                     | `lunarwindow.terrain-mask.v1`, Site01 observer       |
| Other curated sites      | `lunarwindow-terrain horizons` (not committed)                                                 | Preliminary                                          |
| Custom coordinates       | `terrain/service.py` (`HorizonService`)                                                        | Cached, ~0.5 s per new point                         |
| Validation               | `scripts/validate_terrain.py`, `docs/validation/terrain-results.json`                          | Preliminary comparison with PGDA long-term maps      |
| Offline tests            | `backend/tests/test_terrain*.py`                                                               | Analytical geometry, synthetic GeoTIFFs, schema sync |

## Data sources

All rasters are NASA PGDA products in south polar stereographic projection on the 1737.4 km sphere, DE421 MOON_ME frame. `DemSource` rejects any file whose projection differs.

| Product                                 | Use                                       | Source                                                    |
| --------------------------------------- | ----------------------------------------- | --------------------------------------------------------- |
| `Site01_final_adj_5mpp_surf` (41 MB)    | Finest tier for the Site01 demo mask      | [PGDA product 78](https://pgda.gsfc.nasa.gov/products/78) |
| `LDEM_80S_20MPP_ADJ` (2.7 GB)           | Near field, within 25 km of the site      | [PGDA product 90](https://pgda.gsfc.nasa.gov/products/90) |
| `LDEM_60S_120MPP_ADJ` (0.8 GB)          | Far field to 200 km; Chandrayaan-3, slope | [PGDA product 90](https://pgda.gsfc.nasa.gov/products/90) |
| `AVGVISIB_75S_120M_201608` (+ `_EARTH`) | Region point selection and validation     | [PGDA product 69](https://pgda.gsfc.nasa.gov/products/69) |

```sh
python -m pip install -e './backend[gis,analysis]'
lunarwindow-terrain download --all    # ~3.7 GB into ignored data/raw/lola/
```

NASA's server throttles each connection to about 0.2 MB/s, so the downloader fetches four byte ranges in parallel and resumes after interruption. Each completed file gets a `.provenance.json` sidecar (URL, size, SHA-256, retrieval time) that every horizon run copies.

## Algorithm

For each site:

1. Ground height comes from the finest DEM available (bilinear): an optional 5 m site tile, then 20 m, then 120 m. The observer stands at **ground + mast** (default 2 m; 0 m for the Site01 mask, matching its archived ephemerides) above the 1737.4 km sphere.
2. 3,600 rays (0.1° apart) follow great circles from the site, so every point on a ray is seen at exactly that azimuth.
3. Each ray samples terrain from 60 m out to 200 km. Steps start at one 20 m pixel and grow by 0.1% of the distance (about 3,300 samples per ray). Within 25 km the 20 m DEM is used, beyond it the 120 m DEM, and also wherever the 20 m DEM has no data.
4. Each sample's apparent elevation is exact on the sphere: `atan2((R+h)·cos δ − (R+h₀), (R+h)·sin δ)` with `δ = d/R`. This replaces the plan's `d²/2R` approximation.
5. A ray's horizon is its maximum. The 360 whole-degree values are the **maximum of the rays within ±0.5°**, so narrow peaks are never lost and visibility errs toward "blocked".
6. Rays that leave DEM coverage before 200 km are listed in `quality.truncatedAzimuths`. Rays with no terrain at all use the bare-sphere dip. Sites outside the polar DEMs (Apollo 11, Chang'e-6) are declared `"terrain": "none"` in the catalog and get an explicit bare-sphere profile; they never fall back silently.

A peak 5 km high is visible from about √(2RH) ≈ 132 km, so 200 km covers the polar massifs. Computing one site takes about 0.5 s; a full run of 17 sites takes about 15 s, including DEM reads.

## Site catalog

`coordinateSource` cites every coordinate. `kind` distinguishes reference points, landing sites, and representative points.

| Sites                              | Coordinates from                                                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 9 Artemis III candidate regions    | Polygons from the USGS data release (McClernan 2024, [doi:10.5066/P1MEQ6UK](https://doi.org/10.5066/P1MEQ6UK)), sourced from LROC QuickMap |
| Shackleton rim                     | Rim band 0.85–1.25 crater radii around the [IAU Gazetteer](https://planetarynames.wr.usgs.gov/Feature/5450) centre                         |
| IM-2 Athena target                 | [LROC 1401](https://lroc.im-ldi.com/images/1401) (intended target; the touchdown point is unpublished)                                     |
| Chandrayaan-3                      | [LROC 1314](https://lroc.im-ldi.com/images/1314)                                                                                           |
| Chang'e-6                          | [LROC 1374](https://lroc.im-ldi.com/images/1374), ±30 m                                                                                    |
| Apollo 11 LM                       | [NSSDC](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_sites.html), Wagner et al. 2017, ME/DE421                                        |
| LOLA Site01/04/23 reference points | Existing `data/reference/sites.nasa.json` (same coordinates as the 30-day ephemeris bundle)                                                |

Regions are 16–67 km wide, not points. The `regions` command picks one **representative point** per polygon: the 120 m pixel with the highest long-term average sunlight among pixels whose LOLA slope is at most 10°, with ties broken by Earth visibility. The polygon areas it computes match the USGS `Area_km2` attribute within 0.5%. Representative points are for comparison, not proposed landing targets.

```sh
lunarwindow-terrain regions --polygons data/raw/artemis-regions/A3_9regions-lonlat-simplified.shp \
  --name-field Region --source "USGS ... doi:10.5066/P1MEQ6UK ..." --output data/sites.artemis-regions.json
python scripts/make_crater_rim.py --name "Shackleton rim" --lat -89.67 --lon 129.78 \
  --diameter-km 20.92 --output data/regions/shackleton-rim.geojson
```

The USGS polygon zip (`A3_9regions-lonlat-simplified.zip`) must be downloaded manually from ScienceBase, which blocks scripted access, and unzipped into ignored `data/raw/artemis-regions/`.

**Correction:** the `lola-site04-reference` point, previously called "Shackleton rim", lies on Shackleton's **inner wall**. It has a 32° slope, a horizon up to 31°, and PGDA long-term sunlight of about 11%. The curated catalog relabels it; use `shackleton-rim` for the rim.

## Validated demo mask (Site01)

```sh
python scripts/export_terrain_mask.py --site-id lola-site01-reference
```

The exporter reads the observer from the archived ephemeris (`data/reference/validation-30d/lola-site01-reference.json`). It checks that the archived altitude equals the 5 m Site01 tile's ground height at that point, within 1 mm, and ray-casts at a constant 5 m step to 200 km through the 5 m, 20 m and 120 m tiers. It **rejects** the profile if any sample lacks DEM data, then writes the `lunarwindow.terrain-mask.v1` JSON and its SHA-256. It refuses to run on uncommitted code, so `provenance.algorithm.version` always names a reproducible git revision. See the README next to the mask for checks, coverage and limits.

## Preliminary horizons for other sites

```sh
lunarwindow-terrain horizons \
  --sites data/sites.curated.json data/sites.shackleton-rim.json data/sites.artemis-regions.json \
  --plots
lunarwindow-terrain verify data/processed/horizons/<run-id>
```

Each run directory holds:

- `<site>.json`: a `lunarwindow.horizon.v1` profile per site
- `sites.json`: a Horizons-ready catalog whose `altitudeKm` equals the horizon's observer altitude
- `overview.png`: sanity plots
- `manifest.json`: parameters, DEM SHA-256s, and file hashes

The run is published only after every site is computed and verified. These runs are not committed; treat them as preliminary.

## Preliminary comparison with NASA PGDA maps

`scripts/validate_terrain.py` joins each site's horizon (20 m + 120 m DEMs, 2 m mast) with one year of JPL Horizons Sun/Earth angles (2026-11-14 to 2027-11-14, 6 h steps) through the backend visibility engine, using the any-disc rule. It compares the resulting percentages with PGDA's 18.6-year `AVGVISIB_75S_120M_201608` maps at the same pixel. The full output is in `docs/validation/terrain-results.json`.

| Site                          | Sun % | No-terrain Sun % | PGDA Sun % | Earth % | PGDA Earth % |
| ----------------------------- | ----: | ---------------: | ---------: | ------: | -----------: |
| Shackleton rim                |  89.1 |             56.2 |       89.6 |    51.9 |         53.8 |
| Haworth                       |  76.2 |             53.4 |       75.2 |    65.1 |         68.3 |
| Malapert Massif               |  78.4 |             53.5 |       84.5 |    77.3 |         71.0 |
| Mons Mouton                   |  77.5 |             53.6 |       80.0 |    66.6 |         64.3 |
| Mons Mouton Plateau           |  76.3 |             53.4 |       78.4 |    67.6 |         67.8 |
| Nobile Rim 1                  |  88.3 |             53.5 |       85.8 |    60.6 |         60.2 |
| Nobile Rim 2                  |  55.0 |             52.9 |       53.9 |    81.6 |         71.8 |
| Peak near Cabeus B            |  70.2 |             50.9 |       68.4 |    66.8 |         65.8 |
| Slater Plain                  |  68.2 |             54.9 |       65.6 |    49.2 |         49.9 |
| de Gerlache Rim 2             |  75.0 |             59.7 |       78.6 |    60.1 |         61.3 |
| IM-2 target                   |  47.5 |             53.2 |       46.4 |    92.1 |         92.1 |
| Site01 reference              |  51.8 |             57.3 |       49.3 |    46.6 |         43.1 |
| Site23 reference              |  25.0 |             53.6 |       34.8 |    52.0 |         52.7 |
| Site04 reference (inner wall) |  12.7 |             56.2 |       11.2 |     0.0 |         11.4 |

- **Sunlight:** 12 of 14 sites agree within 4 percentage points. The two exceptions are both on the Malapert massif: Site23 (−9.8) and the Malapert region (−6.1).
- **Earth visibility:** 11 of 14 sites agree within 3.5 points. The exceptions are Nobile Rim 2 (+9.8), Malapert (+6.3) and the steep Site04 wall (−11.4).
- **Terrain matters:** without terrain, every site would read 51–60% sunlit.

The remaining differences are expected. PGDA's maps come from 2016-era DEMs at 120 m, average 18.6 years rather than one year, and model a surface observer. Earth sits low near the horizon, so small DEM differences have a large effect. **This is a plausibility check of long-term averages, not validation of individual events.** Except for Site01, these horizons are not committed and stay preliminary.

## Handoff

**To Ephemeris (P1):** the Site01 mask uses your archived observer unchanged, so no new Horizons run is needed for it. Frames: the LOLA DEMs are DE421 `MOON_ME`, while the archived Horizons headers report `MEAN_ME (high precision)` from DE441. Both are Mean Earth/polar-axis frames on the same 1737.4 km sphere, but they are different realizations, and the mask applies no transformation; the backend compatibility check must decide whether to accept the pairing. The Site04 point's "Shackleton rim" label in `sites.nasa.json` and the validation report should be corrected to "inner wall".

**To Backend/data (P3):**

```python
# Validated demo mask, using the TerrainMask contract from feat/terrain-aware-visibility:
mask = TerrainMask.model_validate_json(Path("data/reference/terrain-masks/lola-site01-reference-mast-0m.json").read_text())
horizon = [p.model_dump() for p in mask.horizon]   # feed calculate_visibility

# Preliminary horizons and custom coordinates (optional, P1):
from lunarwindow.terrain import HorizonService, load_horizons

service = HorizonService()            # custom coordinates; needs data/raw/lola
profile = service.horizon(-89.5, -140.0)              # raises ValueError outside DEM coverage
profile = service.horizon(0.7, 23.5, allow_bare_sphere=True)  # explicit terrainModel "none"
```

`HorizonService` blocks for about 1 s on a cache miss, so run it in a worker thread from async routes. Cache entries are keyed by coordinates, parameters, DEM SHA-256 and algorithm version. Deploying custom coordinates needs both DEMs (3.5 GB) on the server, or precomputed sites only. Agree this with whoever owns deployment.

**To Frontend/viz (P4):** `rays.el` (3,600 values at 0.1°) is for drawing the sky-dome silhouette. `horizon` (360 values) is what the engine uses. Draw the bins in `quality.truncatedAzimuths` as uncertain. Show `terrainModel: "none"` as "no terrain data". `rays.horizonDistanceKm` gives how far away the blocking terrain is, which supports the "moving 5 km changes everything" story in Learn mode.

## Known limits

- 20 m pixels miss boulders and small craters; 120 m beyond 25 km smooths distant ridges slightly.
- Mast height is one value per run (default 2 m). Rerun with `--mast-m` for a tall lander antenna. The service accepts `mast_height_m` per request.
- Whole-degree max-binning slightly overstates blocking compared with the 0.1° rays.
- Apollo 11 and Chang'e-6 have no terrain model (bare sphere).
- Representative region points come from 2016-era 120 m illumination averages. They are good for comparison, not site certification.
- The three QuickMap comparisons validate displayed Sun/Earth angles for camera observers about 100–144 km above the surface. They do **not** validate terrain shadows seen by a lander on the ground. A ground-level terrain check needs a QuickMap illumination render at a known time, captured manually.
- The PGDA comparison checks long-term averages (18.6-year maps vs one modelled year) at 120 m map resolution. It is a plausibility check, not a validation of individual sunrise or Earthset times.
