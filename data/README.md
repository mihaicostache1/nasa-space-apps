# Data workspace

- `raw/`: original source downloads, unchanged.
- `processed/`: reproducible derived outputs such as horizon profiles.

Both directories are ignored except for their placeholders. The Python CLI caches original Horizons envelopes in `raw/horizons/` and writes per-site JSON/CSV into `processed/ephemeris/`. A small real response pair is committed in `backend/tests/fixtures/` with its original request URLs, timestamps, and checksums. Keep large DEMs, textures, and SPICE kernels out of Git.

`sites.example.json` is an illustrative input format, not a verified site catalog. Replace it with sourced GIS inputs for real-site runs. See [data sources and conventions](../docs/data-sources.md) for required metadata. No LOLA terrain data has been downloaded into this project.
