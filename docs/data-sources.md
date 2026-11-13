# Data sources and conventions

The Python module now queries Horizons and preserves real source responses. A short illustrative run is archived under `backend/tests/fixtures`; the React UI is not connected to those exports yet. Terrain datasets have not been downloaded.

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
- Terrain model: explicitly `none` until a DEM-derived horizon profile is actually applied.

The TypeScript UI scenario schema limits a comparison to 31 days and 10,000 samples. The separate Python batch exporter allows at most 200,000 samples per site and splits queries into bounded chunks. These are application defaults, not NASA API limits.

## Horizons integration

Use lunar surface observer geometry (`CENTER='coord@301'`), with Sun target `10` and Earth target `399`. Quantity `4` requests azimuth/elevation. Read the manual before selecting geodetic or planetocentric coordinates and transforming elevations from another dataset. Record the actual frame, time scale, surface model, retrieval time, and source request with the result.

Use airless output for the Moon. Match and validate timestamps from both target queries. Detect provider errors and unavailable output explicitly. Do not assume the API returns valid samples just because the HTTP status is 200.

These checks are implemented in `backend/src/lunarwindow/ephemeris/horizons.py`. Exports use the team's flat names (`t`, `sunAz`, `sunEl`, `earthAz`, `earthEl`) and include start / exclude end. Each query's actual observer frame and radii are preserved in its model header. The short archived 2026 responses report a spherical 1737.4 km center radius. GIS must confirm reference-frame/height compatibility before the terrain join.

## Terrain and accuracy

LOLA products on the linked GSFC page use a 1737.4 km reference sphere and polar stereographic projections. Inspect each product's label and metadata for resolution, units, scaling, coverage, and no-data values. Convert reference conventions explicitly before mixing them with Horizons coordinates.

Long-term average illumination or Earth visibility maps cannot replace predictions for a particular mission date. Terrain obstructions and body-disc visibility rules must be specified when deriving a horizon model. Ground-station visibility and electrical power output need additional models.

## Provenance checklist for imported data

Record the source URL, product ID/version, retrieval time, coordinate frame, projection, units, reference surface, resolution, time coverage, checksum, and attribution terms. Preset landing sites must cite their coordinates; do not turn an approximate geographic feature center into a purported landing target.
