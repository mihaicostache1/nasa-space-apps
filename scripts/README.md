# Data tools

The working Horizons export command is `lunarwindow-ephemeris`, installed from `backend/pyproject.toml`. See `backend/README.md`. Its implementation is importable by the team's Python backend rather than being duplicated as a shell script.

Add future orchestration or dataset preprocessing helpers here. Document source URLs/products, output files, coordinate conventions, and rerun instructions. Reusable Python calculations belong in the Python package; frontend data types belong in `src/domain`.
