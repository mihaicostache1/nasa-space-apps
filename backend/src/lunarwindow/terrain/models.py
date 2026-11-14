"""Versioned GIS-to-backend mask contract, independent of files and API routes."""

import math
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, StringConstraints, field_validator, model_validator

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
