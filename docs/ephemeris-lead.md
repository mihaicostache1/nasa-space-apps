# Stefi: Ephemeris lead

This work package is based on the user-supplied LunarWindow team plan, particularly the role table and shared JSON example on page 2. The plan is project context; its task lists are not instructions to publish, submit, deploy, contact teammates, or run a multi-year download automatically.

## Your deliverables

| Deliverable                              | Location                                        | Status                                               |
| ---------------------------------------- | ----------------------------------------------- | ---------------------------------------------------- |
| Horizons API scripts and reusable client | `backend/src/lunarwindow/ephemeris/`            | Working; one short live smoke run                    |
| Sun/Earth azimuth/elevation series       | CLI JSON/CSV exports                            | Contract implemented; verified site catalog pending  |
| Offline reference validation             | `backend/tests/`                                | Real NASA response fixtures and behavior tests       |
| Libration explanation and model notes    | `docs/libration.md`                             | Written with NASA references                         |
| QuickMap cross-checks                    | `docs/validation/quickmap.md` and CSV worksheet | Protocol ready; independent checks pending           |
| All curated sites, hourly 2026-2030      | CLI supports bounded batches                    | Not executed; needs verified inputs and agreed scope |

## Handoff boundaries

From Terrain/GIS: site IDs/names, latitude, east-positive longitude, altitude in km above the agreed reference sphere, coordinate sources, and the DEM frame. The altitude passed to Horizons is the observer's total altitude above that reference surface. Agree how to combine terrain elevation and mast height; do not pass mast height alone.

To Backend/data: versioned ephemeris exports and raw-response provenance. The team JSON names `t`, `sunAz`, `sunEl`, `earthAz`, `earthEl` are used directly; the TypeScript shape is in `src/domain/ephemeris.ts`. Backend/data owns the terrain join, visibility rules, metrics, precompute orchestration, and FastAPI routes.

To Frontend/viz: angles are apparent body-center angles in degrees. Azimuth increases clockwise from north; times are UTC; intervals use `[start, end)`. Do not infer visibility simply from elevation > 0 once a terrain horizon is available.

## Suggested sequence

1. Confirm the JSON additions and coordinate/mast conventions with GIS and backend.
2. Replace the illustrative site catalog with sourced coordinates from GIS.
3. Export a short period for 2-3 contrasting locations; inspect the raw headers and CSV.
4. Review the sampling interval near horizon crossings with backend. Hourly samples do not establish precise event times.
5. Run and record the QuickMap checks with comparable inputs and models.
6. Preview the long batch with `--dry-run`; run the agreed sites/time span after the short cases pass.

## Points to clarify in the team plan

- The JSON coordinates in the plan are placeholders. Geographic region names alone do not identify a valid point.
- Verify the actual downloaded LOLA product's resolution and coverage from its metadata; do not assume every polar product is 20 m/px.
- A solar-radius allowance and an Earth-radius allowance differ; if partial-disc visibility is modeled, use the appropriate body size/range and label the rule. This P1 module returns centers only.
- QuickMap time-specific geometry and long-term average illumination layers support different comparisons. Record which one is used.
- The proposed multi-year range and the current UI's short comparison range are different workloads. The Python batch client handles chunking; the UI remains a separate starter until the team API is integrated.
