# Data sources and conventions

The Python module queries Horizons and preserves real source responses. The versioned sample fixture and a 30-day, three-point reference bundle are committed. Three NASA regional DEMs were downloaded into ignored storage to derive reference coordinates and surface heights. Terrain horizon masks are now computed from the PGDA 20 m and 120 m south polar DEMs; see [the terrain work package](terrain-gis-lead.md). The React UI does not yet consume these exports.

| Resource                                                                                                 | Intended role                                                                    |
| -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [NASA challenge brief](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/) | Requirements, suggested capabilities, and official Resources tab                 |
| [JPL Horizons API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html)                         | Server-side observer ephemerides                                                 |
| [Horizons manual](https://ssd.jpl.nasa.gov/horizons/manual.html)                                         | Observer coordinates, reference surfaces, time scales, and output interpretation |
| [NASA GSFC polar illumination products](https://pgda.gsfc.nasa.gov/products/69)                          | LOLA elevation, illumination, and Earth visibility products                      |
| [NASA Moon Trek](https://trek.nasa.gov/moon/)                                                            | Lunar imagery, mapping, and contextual exploration                               |
| [NASA NAIF SPICE](https://naif.jpl.nasa.gov/naif/)                                                       | Possible future local/offline geometry engine                                    |

## Internal contracts

- Latitude: decimal degrees, -90 through +90.
- Longitude: east-positive decimal degrees, -180 through +180. Normalize external 0–360° catalogs explicitly when importing them.
- Altitude: kilometers above the provider's declared lunar reference surface. It is not antenna height above the terrain. Default `0` is an illustrative assumption; the adapter must document its actual reference model.
- Time: ISO 8601 UTC strings ending in `Z`. The starter date controls select midnight UTC. Domain types allow times as well.
- Azimuth: degrees clockwise from local north, 0 through less than 360.
- Elevation: degrees above the local horizontal plane, -90 through +90.
- Terrain model: `lola-dem` for DEM-derived horizon profiles, explicitly `none` for bare-sphere sites outside the polar DEMs (Apollo 11, Chang'e-6). The ephemeris export itself always reports `none`; terrain enters through the horizon join.
- Observer altitude for terrain-aware sites: LOLA ground height + mast height (default 2 m) above the 1737.4 km sphere, identical in the horizon profile and the Horizons request.

The TypeScript UI scenario schema limits a comparison to 31 days and 10,000 samples. The separate Python batch exporter allows at most 200,000 samples per site and splits queries into bounded chunks. These are application defaults, not NASA API limits.

## Horizons integration

Use lunar surface observer geometry (`CENTER='coord@301'`), with Sun target `10` and Earth target `399`. Quantity `4` requests azimuth/elevation; `13` requests angular diameter in arcseconds. Contract v2 exports the corresponding equatorial angular radius in degrees (diameter / 7200). Read the manual before selecting geodetic or planetocentric coordinates and transforming elevations from another dataset. Record the actual frame, time scale, surface model, retrieval time, and source request with the result.

Use airless output for the Moon. Match and validate timestamps from both target queries. Detect provider errors and unavailable output explicitly. Do not assume the API returns valid samples just because the HTTP status is 200.

Horizons UT is interpreted as UTC for the modern dates used here. Future leap seconds are unknown; the provider uses its available time-scale conversion assumptions for future predictions. Preserve retrieval epochs/model headers and regenerate future data when those assumptions change. The application samples at whole-minute timestamps and does not represent a `23:59:60` leap-second label.

These checks are implemented in `backend/src/lunarwindow/ephemeris/horizons.py`. Exports use the team's flat names (`t`, `sunAz`, `sunEl`, `earthAz`, `earthEl`) and include start / exclude end. Each row also carries `sunAngularRadiusDeg` and `earthAngularRadiusDeg`. Each query's actual observer frame and radii are preserved in its model header. The short archived 2026 responses report a spherical 1737.4 km center radius. GIS must confirm reference-frame/height compatibility before the terrain join.

## Terrain and accuracy

LOLA products on the linked GSFC page use a 1737.4 km reference sphere and polar stereographic projections. Inspect each product's label and metadata for resolution, units, scaling, coverage, and no-data values. Convert reference conventions explicitly before mixing them with Horizons coordinates.

The terrain pipeline uses `LDEM_80S_20MPP_ADJ`, `LDEM_60S_120MPP_ADJ`, and the `AVGVISIB_75S_120M_201608` Sun/Earth maps ([PGDA products 90](https://pgda.gsfc.nasa.gov/products/90) and [69](https://pgda.gsfc.nasa.gov/products/69)); heights are float metres with NaN gaps, visibility maps are int16 × 4e-5 fractions with −32768 gaps, all in DE421 MOON_ME. Artemis III region polygons come from USGS ([doi:10.5066/P1MEQ6UK](https://doi.org/10.5066/P1MEQ6UK)).

Long-term average illumination or Earth visibility maps cannot replace predictions for a particular mission date. Terrain obstructions and body-disc visibility rules must be specified when deriving a horizon model. Ground-station visibility and electrical power output need additional models.

## Provenance checklist for imported data

Record the source URL, product ID/version, retrieval time, coordinate frame, projection, units, reference surface, resolution, time coverage, checksum, and attribution terms. Preset landing sites must cite their coordinates; do not turn an approximate geographic feature center into a purported landing target.
