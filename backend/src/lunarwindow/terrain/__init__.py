"""P2: LOLA terrain acquisition, horizon masks, and the curated site catalog."""

from .compatibility import (
    TerrainCompatibility,
    TerrainCompatibilityError,
    check_terrain_compatibility,
)
from .export import load_horizons, verify_horizon_run
from .horizon import OutsideCoverage, SiteSpec, compute_horizon, default_parameters, flat_horizon
from .loader import load_terrain_mask
from .models import HorizonProfile, TerrainMask
from .service import HorizonService

__all__ = [
    "HorizonProfile",
    "HorizonService",
    "OutsideCoverage",
    "SiteSpec",
    "TerrainCompatibility",
    "TerrainCompatibilityError",
    "TerrainMask",
    "check_terrain_compatibility",
    "compute_horizon",
    "default_parameters",
    "flat_horizon",
    "load_horizons",
    "load_terrain_mask",
    "verify_horizon_run",
]
