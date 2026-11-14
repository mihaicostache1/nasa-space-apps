"""Serializable horizon profiles, the P2 → P3 handoff contract (lunarwindow.horizon.v1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..visibility.models import HorizonPoint

SCHEMA_VERSION = "lunarwindow.horizon.v1"
TerrainModel = Literal["lola-dem", "none"]


class TerrainModelBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class HorizonSource(TerrainModelBase):
    productId: str | None
    role: str | None
    sourceUrl: str | None
    sha256: str | None
    resolutionM: float = Field(gt=0)


class HorizonParameters(TerrainModelBase):
    mastHeightM: float = Field(ge=0, le=1000)
    maxRangeKm: float = Field(gt=0, le=1000)
    nearFieldKm: float = Field(ge=0, le=1000)
    minDistanceM: float = Field(gt=0)
    raysPerDegree: int = Field(ge=1, le=100)
    stepGrowth: float = Field(ge=0, le=0.05)
    binning: Literal["max-per-degree"] = "max-per-degree"


class RayProfile(TerrainModelBase):
    """Full-resolution rays for drawing; azimuth of ray i is i × stepDeg."""

    stepDeg: float = Field(gt=0)
    el: list[float]
    horizonDistanceKm: list[float | None]
    """Distance to the terrain that sets the horizon; null where no terrain was sampled."""
    reachKm: list[float]
    """Farthest valid terrain sample. Below maxRangeKm means the ray left DEM coverage."""

    @model_validator(mode="after")
    def _lengths(self):
        count = round(360 / self.stepDeg)
        if not (len(self.el) == len(self.horizonDistanceKm) == len(self.reachKm) == count):
            raise ValueError(f"Ray arrays must each hold {count} entries.")
        return self


class HorizonQuality(TerrainModelBase):
    truncatedAzimuths: list[int]
    """Whole-degree bins containing a ray that left DEM coverage before maxRangeKm."""
    minReachKm: float = Field(ge=0)
    missingSampleFraction: float = Field(ge=0, le=1)
    nearFieldAvailable: bool
    warnings: list[str]


class HorizonProfile(TerrainModelBase):
    schemaVersion: Literal["lunarwindow.horizon.v1"] = SCHEMA_VERSION
    siteId: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    coordinateSource: str
    terrainModel: TerrainModel
    surfaceElevationM: float | None
    """Height of the ground at the site above the reference sphere; null if unknown."""
    mastHeightM: float = Field(ge=0)
    observerAltitudeKm: float
    """Ground + mast above the reference sphere: pass this as the Horizons altitude."""
    referenceRadiusM: float = Field(gt=0)
    horizon: list[HorizonPoint]
    rays: RayProfile | None
    quality: HorizonQuality
    parameters: HorizonParameters
    sources: list[HorizonSource]
    algorithmVersion: str

    @model_validator(mode="after")
    def _horizon(self):
        if [point.az for point in self.horizon] != list(range(360)):
            raise ValueError("A horizon requires exactly 360 points ordered by azimuth 0..359.")
        if self.terrainModel == "lola-dem" and (not self.sources or self.rays is None):
            raise ValueError("DEM-derived horizons must list sources and include rays.")
        return self
