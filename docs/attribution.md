# Data sources and attribution

LunarWindow's code is MIT-licensed (see `LICENSE`). The data it uses comes from the sources below, which keep their own terms. Data produced by NASA and USGS is generally not subject to copyright in the United States. Each source is credited as its provider requests, and nothing here implies endorsement by NASA, USGS, or any mission team.

## Used by the app

| What                                           | Source                                                                                                                                                      | Where in the repo                                                       |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Sun and Earth azimuth/elevation, angular sizes | NASA/JPL [Horizons System](https://ssd.jpl.nasa.gov/horizons/) API (DE441), retrieved November 2026 and archived with request URLs and response hashes      | `data/reference/horizons/`, `data/reference/validation-30d/`            |
| Reference-site coordinates and heights         | NASA GSFC PGDA, LOLA 5 m/px site DEMs, [product 78](https://pgda.gsfc.nasa.gov/products/78) (Site01, Site04, Site23)                                        | `data/reference/sites.nasa.json`, `data/reference/site-provenance.json` |
| Site01 terrain mask                            | NASA GSFC PGDA LOLA DEMs: [product 78](https://pgda.gsfc.nasa.gov/products/78) (5 m) and [product 90](https://pgda.gsfc.nasa.gov/products/90) (20 m, 120 m) | `data/reference/terrain-masks/`                                         |

## Used for the curated site catalog and validation

| What                                       | Source                                                                                                                                                                                                            |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Artemis III candidate-region polygons      | USGS data release, McClernan (2024), _Down Selected Artemis III Candidate Landing Site Navigational Grids_, [doi:10.5066/P1MEQ6UK](https://doi.org/10.5066/P1MEQ6UK), CC0 1.0; regions sourced from LROC QuickMap |
| Long-term Sun/Earth visibility maps        | NASA GSFC PGDA, LOLA polar illumination, [product 69](https://pgda.gsfc.nasa.gov/products/69) (`AVGVISIB_75S_120M_201608`, Mazarico et al. 2011 method)                                                           |
| Shackleton crater centre and diameter      | IAU/USGS [Gazetteer of Planetary Nomenclature](https://planetarynames.wr.usgs.gov/Feature/5450)                                                                                                                   |
| IM-2, Chandrayaan-3, Chang'e-6 coordinates | LROC (NASA/GSFC/Arizona State University) image releases [1401](https://lroc.im-ldi.com/images/1401), [1314](https://lroc.im-ldi.com/images/1314), [1374](https://lroc.im-ldi.com/images/1374)                    |
| Apollo 11 Lunar Module coordinates         | NASA NSSDC [Apollo landing site coordinates](https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_sites.html) (Wagner et al., _Icarus_ 283, 92–103, 2017)                                                            |
| Cross-check views                          | [LROC QuickMap](https://quickmap.lroc.asu.edu/) (NASA/GSFC/Arizona State University), see `docs/validation/`                                                                                                      |

## How to cite the challenge

NASA Space Apps Challenge 2026, [Lunar Landing Site Navigator](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/).

## What the data does and does not support

- The app's results are geometric: a flat 0° horizon, with no terrain, eclipses, power or radio-link modelling.
- The reference points are DEM grid cells, not landing recommendations. The Artemis III points are representative points chosen by a documented rule, not landing targets.
- The QuickMap comparisons validate displayed Sun/Earth angles for observers about 100–144 km above the surface, not terrain shadows seen from the ground.
