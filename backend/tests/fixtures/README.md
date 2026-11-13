# Archived NASA Horizons response pair

`sun.json` and `earth.json` are cache archives from a real request for an illustrative point at latitude -89 degrees, east longitude 0 degrees, altitude 0 km, from 2026-11-14 00:00 through 03:00 UT at hourly spacing. Horizons includes the stop sample, giving four raw rows; the application exports three rows for the half-open interval.

Each archive retains the exact API response string in `rawResponse`, its SHA-256, the full request URL, and the actual UTC retrieval timestamp. See those fields for precise provenance. The site is a test point, not a verified landing site. No reference angles in these files were generated or manually fabricated.

Source: [NASA/JPL Horizons API](https://ssd-api.jpl.nasa.gov/doc/horizons.html). Tests mutate copies in memory only when checking malformed data. These fixtures do not represent a QuickMap validation.
