# Frontend-side server adapters

The team plan places Horizons retrieval in Python. The working implementation is now under `backend/src/lunarwindow/ephemeris`; the matching export contract is `EphemerisDataset` in `src/domain/ephemeris.ts`. No frontend-side provider is configured.

If Next.js later proxies the team's FastAPI service, keep that adapter here with `import 'server-only'`. Do not duplicate scientific calculations or implement a second Horizons parser in the frontend. See `backend/README.md` for Python usage and handoff boundaries.
