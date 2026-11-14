"""Terrain-mask and GIS horizon contracts, independent of files and API routes."""

import math
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lunarwindow.visibility.models import HorizonPoint, VisibilityModel

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Sha256 = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


def _valid_utc(value: str) -> str:
    # Artifact timestamps may have seconds/fractions, unlike ephemeris sample times.
    datetime.fromisoformat(value)
    return value


UtcTimestamp = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$",
        json_schema_extra={"format": "date-time"},
    ),
    AfterValidator(_valid_utc),
]


class MaskObserver(VisibilityModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    coordinateSource: NonBlank
    surfaceElevationM: float
    mastHeightM: float = Field(ge=0)
    altitudeKm: float = Field(description="Total observer altitude above the reference sphere")

    @model_validator(mode="after")
    def validate_total_altitude(self) -> Self:
        expected = (self.surfaceElevationM + self.mastHeightM) / 1000
        if not math.isclose(self.altitudeKm, expected, rel_tol=0, abs_tol=1e-6):
            raise ValueError(
                "altitudeKm must equal (surfaceElevationM + mastHeightM) / 1000 within 1e-6 km."
            )
        return self


class ReferenceSphere(VisibilityModel):
    shape: Literal["sphere"]
    radiusKm: float = Field(gt=0)


class MaskReferenceFrame(VisibilityModel):
    body: Literal["Moon"]
    name: NonBlank
    realization: NonBlank
    coordinateType: Literal["GEODETIC"]
    longitudeConvention: Literal["east-positive"]
    referenceSurface: ReferenceSphere


class DemSource(VisibilityModel):
    provider: NonBlank
    productId: NonBlank
    productVersion: NonBlank
    sourceUrl: str = Field(json_schema_extra={"format": "uri"})
    sourceSha256: Sha256
    retrievedAtUtc: UtcTimestamp
    resolutionM: float = Field(gt=0)
    crs: NonBlank

    @field_validator("sourceUrl")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in ("https", "http")
            or not parts.hostname
            or any(character.isspace() for character in value)
        ):
            raise ValueError("sourceUrl must be an absolute HTTP(S) URL without whitespace.")
        return value


class MaskAlgorithm(VisibilityModel):
    name: NonBlank
    version: NonBlank
    curvatureModel: Literal["spherical", "quadratic-drop"]
    rayStepM: float = Field(gt=0)
    maxDistanceM: float = Field(gt=0)
    noDataPolicy: Literal["reject"]

    @model_validator(mode="after")
    def validate_trace_distance(self) -> Self:
        if self.rayStepM > self.maxDistanceM:
            raise ValueError("rayStepM must not exceed maxDistanceM.")
        return self


class MaskProvenance(VisibilityModel):
    createdAtUtc: UtcTimestamp
    sources: list[DemSource] = Field(min_length=1)
    algorithm: MaskAlgorithm


class TerrainMask(VisibilityModel):
    schemaVersion: Literal["lunarwindow.terrain-mask.v1"]
    maskId: Slug
    siteId: Slug
    site: NonBlank
    terrainModel: Literal["dem-horizon"]
    observer: MaskObserver
    referenceFrame: MaskReferenceFrame
    angularUnits: Literal["degrees"]
    azimuthConvention: Literal["clockwise-from-local-north"]
    elevationReference: Literal["local-horizontal"]
    refractionModel: Literal["none"]
    horizon: list[HorizonPoint] = Field(min_length=360, max_length=360)
    provenance: MaskProvenance

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if any(point.az != index for index, point in enumerate(self.horizon)):
            raise ValueError("Horizon azimuths must be unique and ordered 0..359.")
        radius = self.referenceFrame.referenceSurface.radiusKm
        if radius + self.observer.surfaceElevationM / 1000 <= 0:
            raise ValueError("Surface elevation must lie above the reference sphere's center.")
        return self


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
