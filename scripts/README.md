# Data tools

The working Horizons export command is `lunarwindow-ephemeris`, installed from `backend/pyproject.toml`. See `backend/README.md`. Its implementation is importable by the team's Python backend rather than being duplicated as a shell script.

Add future orchestration or dataset preprocessing helpers here. Document source URLs/products, output files, coordinate conventions, and rerun instructions. Reusable Python calculations belong in the Python package; frontend data types belong in `src/domain`.

`build_terrain_regression.py` is a test-fixture utility, deliberately independent of the production visibility code. It derives the fixed Site01 model expectations from pinned mask/ephemeris files using decimal arithmetic, NumPy periodic interpolation, and grouped hourly runs. It performs no downloads or source-artifact writes, and only writes the explicit `--output` path. It is not used by the API or run automatically in CI. See [the regression evidence and regeneration procedure](../docs/validation/terrain-regression.md).
