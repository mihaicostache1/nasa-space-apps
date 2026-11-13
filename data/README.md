# Data workspace

- `raw/`: original source downloads, unchanged.
- `processed/`: reproducible derived outputs such as horizon profiles.

Both directories are ignored except for their placeholders. The Python CLI caches original Horizons envelopes in `raw/horizons/` and writes immutable per-run directories under `processed/ephemeris/<run-id>/`, with per-site JSON/CSV and a checksum/completion manifest. A small real response pair is committed in `backend/tests/fixtures/` with its original request URLs, timestamps, and checksums. Keep large DEMs, textures, and SPICE kernels out of Git.

`sites.example.json` is an illustrative input format, not a verified site catalog. Replace it with sourced GIS inputs for real-site runs. See [data sources and conventions](../docs/data-sources.md) for required metadata. Regional LOLA DEMs are held in ignored `raw/lola/` for reference-point acquisition. The reviewed `reference/` directory is the exception to ignored generated outputs: it contains the sourced catalog, source manifests, raw Horizons archives, a 30-day run, and a pointing plot. See `docs/validation/report.md`; no terrain horizon model is integrated.
