"""On-demand horizons for custom coordinates, cached on disk.

The backend can call `HorizonService.horizon()` for any latitude/longitude. Results are keyed
by coordinates, parameters, the DEM files' SHA-256, and the algorithm version, so a changed
input can never return a stale profile. Calls block for a few seconds on a cache miss; run
them in a worker thread from async code. DEM reads are serialized because GDAL dataset
handles are not thread-safe.
"""

import hashlib
import json
import threading
from contextlib import ExitStack
from pathlib import Path

from ..ephemeris.storage import atomic_write, file_lock
from .catalog import CatalogSite
from .export import horizon_for_site, open_dems
from .horizon import ALGORITHM_VERSION, default_parameters
from .models import HorizonParameters, HorizonProfile


class HorizonService:
    def __init__(
        self,
        dem_dir: Path = Path("data/raw/lola"),
        cache_dir: Path = Path("data/processed/horizon-cache"),
        parameters: HorizonParameters | None = None,
    ):
        self.dem_dir = Path(dem_dir)
        self.cache_dir = Path(cache_dir)
        self.parameters = parameters or default_parameters()
        self._stack = ExitStack()
        self._dems = None
        self._lock = threading.Lock()

    def close(self) -> None:
        self._stack.close()
        self._dems = None

    def _open(self):
        if self._dems is None:
            self._dems = open_dems(self.dem_dir, self._stack)
        return self._dems

    def _key(self, lat: float, lon: float, params: HorizonParameters, terrain: str) -> str:
        near, far = self._open() if terrain == "lola-dem" else (None, None)
        payload = {
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "terrain": terrain,
            "parameters": params.model_dump(),
            "dems": [dem.provenance for dem in (near, far) if dem is not None],
            "algorithm": ALGORITHM_VERSION,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]

    def horizon(
        self,
        lat: float,
        lon: float,
        *,
        site_id: str = "custom",
        name: str = "Custom location",
        coordinate_source: str = "User-supplied coordinates",
        mast_height_m: float | None = None,
        allow_bare_sphere: bool = False,
    ) -> HorizonProfile:
        """Terrain horizon at (lat, lon). Outside DEM coverage this raises ValueError unless
        `allow_bare_sphere`, which returns an explicit `terrainModel: "none"` profile."""
        params = self.parameters
        if mast_height_m is not None:
            params = default_parameters(**(params.model_dump() | {"mastHeightM": mast_height_m}))
        site = CatalogSite(site_id, name, "landing-target", lat, lon, "lola-dem", coordinate_source)
        with self._lock:
            key = self._key(lat, lon, params, "lola-dem")
            path = self.cache_dir / f"{key}.json"
            with file_lock(self.cache_dir / ".locks" / f"{key}.lock"):
                if path.exists():
                    cached = HorizonProfile.model_validate_json(path.read_text("utf-8"))
                    return cached.model_copy(
                        update={
                            "siteId": site_id,
                            "name": name,
                            "coordinateSource": coordinate_source,
                        }
                    )
                near, far = self._open()
                try:
                    profile = horizon_for_site(site, near, far, params)
                except ValueError:
                    if not allow_bare_sphere:
                        raise
                    bare = CatalogSite(
                        site_id, name, "landing-target", lat, lon, "none", coordinate_source
                    )
                    return horizon_for_site(bare, None, None, params)
                atomic_write(path, profile.model_dump_json() + "\n")
                return profile
