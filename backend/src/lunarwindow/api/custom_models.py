"""Strict custom-observer contracts, sharing the reference visibility calculation model."""

import hashlib
import json
import math
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.ephemeris.models import TimeRange, iso_utc, parse_utc
from lunarwindow.observer import canonical_model_sha256, custom_observer_id
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.models import (
    HorizonProfile,
    MaskObserver,
    NonBlank,
    Sha256,
    Slug,
    TerrainMask,
)
from lunarwindow.visibility.models import (
    CalculationInfo,
    EphemerisSample,
    HorizonPoint,
    VisibilityMetrics,
    VisibilitySample,
    VisibilityWindows,
)

from .models import ApiModel, EvaluationOptions
from .reference_models import EPHEMERIS_PROVENANCE_SCHEMA, ReferenceEvaluationProvenance
from .terrain_models import TerrainCompatibilityProvenance


class CustomLocation(ApiModel):
    latitudeDeg: float = Field(ge=-90, le=90)
    longitudeDeg: float = Field(ge=-180, le=180, description="East-positive lunar longitude")
    observerHeightM: float = Field(
        ge=0, le=1000, description="Observer height in metres above the local ground"
    )
    surfaceElevationM: float | None = Field(
        default=None,
        ge=-20_000,
        le=20_000,
        description=(
            "Ground elevation in metres above the 1737.4 km lunar sphere. Required for "
            "geometric mode; terrain mode derives it from the DEM and checks any supplied value."
        ),
    )

    @field_validator("latitudeDeg", "longitudeDeg", "observerHeightM", "surfaceElevationM")
    @classmethod
    def normalize_zero(cls, value: float | None) -> float | None:
        return 0.0 if value == 0 else value

    @field_validator("longitudeDeg")
    @classmethod
    def canonical_longitude(cls, value: float) -> float:
        return -180.0 if value == 180 else value


class CustomEvaluationRequest(EvaluationOptions):
    location: CustomLocation
    horizonMode: Literal["geometric", "terrain"]
    allowMeanEarthApproximation: bool = Field(
        default=False,
        description="Explicit acceptance of the documented terrain Mean Earth approximation",
    )

    @field_validator("startUtc", "endUtc", "asOfUtc")
    @classmethod
    def canonical_utc(cls, value: str | None) -> str | None:
        return None if value is None else iso_utc(parse_utc(value))

    @model_validator(mode="after")
    def validate_custom_observer(self) -> Self:
        period = self.to_time_range()
        if period.start < parse_utc("2000-01-01T00:00:00Z") or period.end > parse_utc(
            "2040-01-01T00:00:00Z"
        ):
            raise ValueError("Custom evaluations require dates in 2000–2039.")
        if self.horizonMode == "geometric":
            if self.location.surfaceElevationM is None:
                raise ValueError("Geometric mode requires explicit location.surfaceElevationM.")
            if self.allowMeanEarthApproximation:
                raise ValueError("Frame-approximation acceptance applies only to terrain mode.")
        return self


def observer_site_id(location: CustomLocation, altitude_km: float) -> str:
    """Stable observer identity; retain exact coordinates rather than rounding locations."""
    return custom_observer_id(location.latitudeDeg, location.longitudeDeg, altitude_km)


class CustomTerrainProvenance(ApiModel):
    profile: HorizonProfile
    profileSha256: Sha256
    mask: TerrainMask
    maskSha256: Sha256
    compatibility: TerrainCompatibilityProvenance
    reviewStatus: Literal["preliminary"] = "preliminary"


class CustomEvaluationProvenance(ApiModel):
    ephemeris: dict = Field(json_schema_extra=EPHEMERIS_PROVENANCE_SCHEMA)
    ephemerisSha256: Sha256
    terrain: CustomTerrainProvenance | None = None
    warning: NonBlank

    _validate_ephemeris = field_validator("ephemeris")(
        ReferenceEvaluationProvenance.validate_source_evidence.__func__
    )


class CustomEvaluation(ApiModel):
    schemaVersion: Literal["lunarwindow.custom-evaluation.v1"] = "lunarwindow.custom-evaluation.v1"
    dataMode: Literal["custom"] = "custom"
    siteId: Slug
    site: NonBlank
    observer: MaskObserver
    horizonMode: Literal["geometric", "terrain"]
    allowMeanEarthApproximation: bool
    horizon: list[HorizonPoint] = Field(min_length=360, max_length=360)
    series: list[VisibilitySample] = Field(min_length=1, max_length=10_000)
    metrics: VisibilityMetrics
    windows: VisibilityWindows
    calculation: CalculationInfo
    provenance: CustomEvaluationProvenance

    def to_ephemeris_dataset(self) -> dict:
        observer = self.observer
        return {
            "schemaVersion": "lunarwindow.ephemeris.v2",
            "siteId": self.siteId,
            "site": self.site,
            "lat": observer.lat,
            "lon": observer.lon,
            "altitudeKm": observer.altitudeKm,
            "coordinateSource": observer.coordinateSource,
            "series": [
                row.model_dump(include=set(EphemerisSample.model_fields)) for row in self.series
            ],
            "provenance": self.provenance.ephemeris,
        }

    @model_validator(mode="after")
    def validate_custom_result(self) -> Self:
        dataset = validate_dataset(self.to_ephemeris_dataset())
        dataset_bytes = json.dumps(
            dataset, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if hashlib.sha256(dataset_bytes).hexdigest() != self.provenance.ephemerisSha256:
            raise ValueError("Ephemeris provenance checksum must identify the complete dataset.")
        source = self.provenance.ephemeris
        period = TimeRange(source["startUtc"], source["endUtc"], source["stepMinutes"])
        if self.calculation.stepMinutes != period.step_minutes:
            raise ValueError("Calculation and ephemeris sampling intervals differ.")
        if not period.start <= parse_utc(self.metrics.asOfUtc) < period.end:
            raise ValueError("Metrics asOfUtc must be within the evaluated period.")
        if self.metrics.evaluatedHrs != (period.end - period.start).total_seconds() / 3600:
            raise ValueError("Metrics evaluatedHrs must match the ephemeris period.")
        if [point.az for point in self.horizon] != list(range(360)):
            raise ValueError("Horizon azimuths must be ordered 0..359.")
        if self.horizonMode == "geometric":
            if self.provenance.terrain is not None or self.allowMeanEarthApproximation:
                raise ValueError("Geometric results cannot declare terrain or frame acceptance.")
            if any(point.el != 0 for point in self.horizon):
                raise ValueError("Geometric results require a flat zero-degree horizon.")
        else:
            self._validate_terrain()
        for row in self.series:
            for azimuth, elevation in (
                (row.sunAz, row.sunHorizonEl),
                (row.earthAz, row.earthHorizonEl),
            ):
                lower = math.floor(azimuth)
                fraction = azimuth - lower
                expected = (
                    self.horizon[lower].el * (1 - fraction)
                    + self.horizon[(lower + 1) % 360].el * fraction
                )
                if not math.isclose(elevation, expected, rel_tol=0, abs_tol=1e-9):
                    raise ValueError("Sample horizon elevations must match the horizon profile.")
        return self

    def _validate_terrain(self) -> None:
        terrain = self.provenance.terrain
        if terrain is None or self.allowMeanEarthApproximation is not True:
            raise ValueError("Terrain results require provenance and explicit frame acceptance.")
        profile = terrain.profile
        mask = terrain.mask
        observer = self.observer
        if (
            profile.siteId != self.siteId
            or profile.horizon != self.horizon
            or profile.terrainModel != "lola-dem"
            or profile.lat != observer.lat
            or profile.lon != observer.lon
            or profile.mastHeightM != observer.mastHeightM
            or profile.surfaceElevationM is None
            or not math.isclose(
                profile.surfaceElevationM, observer.surfaceElevationM, rel_tol=0, abs_tol=0.001
            )
            or not math.isclose(
                profile.observerAltitudeKm, observer.altitudeKm, rel_tol=0, abs_tol=1e-6
            )
        ):
            raise ValueError("Terrain profile and evaluated observer must match.")
        if (
            profile.quality.missingSampleFraction != 0
            or profile.quality.truncatedAzimuths
            or profile.quality.minReachKm < profile.parameters.maxRangeKm - 0.001
            or not math.isclose(profile.referenceRadiusM, 1_737_400, rel_tol=0, abs_tol=0.001)
        ):
            raise ValueError("Custom terrain requires complete DEM coverage on the lunar sphere.")
        if (
            canonical_model_sha256(profile) != terrain.profileSha256
            or canonical_model_sha256(mask) != terrain.maskSha256
        ):
            raise ValueError("Terrain provenance checksums must identify the complete contracts.")
        if mask.observer != observer or mask.horizon != self.horizon:
            raise ValueError("Terrain mask and evaluated observer/horizon must match.")
        profile_sources = [
            (item.productId, item.sha256, item.sourceUrl, item.resolutionM)
            for item in profile.sources
        ]
        mask_sources = [
            (item.productId, item.sourceSha256, item.sourceUrl, item.resolutionM)
            for item in mask.provenance.sources
        ]
        if profile_sources != mask_sources:
            raise ValueError("Terrain profile and mask must describe the same DEM sources.")
        assessment = check_terrain_compatibility(
            mask, self.to_ephemeris_dataset(), allow_mean_earth_approximation=True
        )
        if terrain.compatibility != TerrainCompatibilityProvenance.from_assessment(assessment):
            raise ValueError("Terrain compatibility must match the mask/ephemeris assessment.")
