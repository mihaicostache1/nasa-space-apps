"""Versioned HTTP contracts; scenario inputs mirror src/domain/scenario.ts."""

from datetime import timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lunarwindow.ephemeris.models import TimeRange, parse_utc
from lunarwindow.terrain.models import (
    DemSource,
    MaskObserver,
    MaskReferenceFrame,
    NonBlank,
    Sha256,
    Slug,
)
from lunarwindow.visibility.models import (
    CalculationInfo,
    HorizonPoint,
    VisibilityMetrics,
    VisibilityRule,
    VisibilitySample,
    VisibilityWindows,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Location(ApiModel):
    latitudeDeg: float = Field(ge=-90, le=90, examples=[-89])
    longitudeDeg: float = Field(ge=-180, le=180, examples=[0])
    altitudeKm: float = Field(
        description="Kilometers above the lunar reference surface", examples=[0]
    )


class Period(ApiModel):
    startUtc: str = Field(examples=["2026-11-14T00:00:00Z"])
    endUtc: str = Field(examples=["2026-11-15T00:00:00Z"])
    stepMinutes: int = Field(default=60, ge=1, le=1440)

    @field_validator("startUtc", "endUtc")
    @classmethod
    def validate_utc(cls, value: str) -> str:
        parse_utc(value)
        return value

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        period = self.to_time_range()
        if period.end - period.start > timedelta(days=31):
            raise ValueError("Choose at most 31 days.")
        if period.sample_count > 10_000:
            raise ValueError("Choose a larger step (maximum 10,000 samples).")
        return self

    def to_time_range(self) -> TimeRange:
        return TimeRange(self.startUtc, self.endUtc, self.stepMinutes)


class EvaluationOptions(Period):
    visibilityRule: VisibilityRule = "any-disc"
    asOfUtc: str | None = Field(
        default=None, description="Countdown reference time within the range; defaults to startUtc"
    )

    @model_validator(mode="after")
    def validate_as_of(self) -> Self:
        if self.asOfUtc is not None:
            instant = parse_utc(self.asOfUtc)
            period = self.to_time_range()
            if not period.start <= instant < period.end:
                raise ValueError("asOfUtc must be within [startUtc, endUtc).")
        return self


class EvaluationRequest(EvaluationOptions):
    name: str = Field(min_length=1, max_length=80, examples=["Scenario A"])
    location: Location

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DemoSite(ApiModel):
    id: str
    name: str
    lat: float
    lon: float
    altitudeKm: float = 0
    coordinateSource: str = "Illustrative coordinates for UI development; not a verified site."


class SiteCatalog(ApiModel):
    dataMode: Literal["synthetic"] = "synthetic"
    sites: list[DemoSite]


class ReferenceAvailability(ApiModel):
    startUtc: str
    endUtc: str
    endExclusive: Literal[True] = True
    stepMinutes: int = Field(ge=1, le=1440)
    sampleCount: int = Field(ge=1, le=200_000)


class ReferenceTerrainMask(ApiModel):
    """Verified mask selection metadata; excludes the full horizon and ephemeris."""

    maskId: Slug
    artifactSha256: Sha256
    observer: MaskObserver
    referenceFrame: MaskReferenceFrame
    demSources: list[DemSource] = Field(min_length=1)
    requiresMeanEarthApproximation: bool
    framePolicy: Literal["mean-earth-reference-v1"]
    limitation: NonBlank


class ReferenceSite(ApiModel):
    id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    altitudeKm: float
    coordinateSource: str
    availability: ReferenceAvailability
    supportedHorizonModes: list[Literal["geometric", "terrain"]] = Field(min_length=1, max_length=2)
    terrainMasks: list[ReferenceTerrainMask]

    @model_validator(mode="after")
    def validate_horizon_availability(self) -> Self:
        expected = ["geometric", "terrain"] if self.terrainMasks else ["geometric"]
        if self.supportedHorizonModes != expected:
            raise ValueError("Supported horizon modes must match verified terrain availability.")
        ids = [mask.maskId for mask in self.terrainMasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Terrain mask IDs must be unique within a site.")
        return self


class ReferenceSiteCatalog(ApiModel):
    schemaVersion: Literal["lunarwindow.reference-catalog.v1"] = "lunarwindow.reference-catalog.v1"
    provider: Literal["NASA/JPL Horizons"] = "NASA/JPL Horizons"
    timeScale: Literal["UTC"] = "UTC"
    longitudeConvention: Literal["east-positive"] = "east-positive"
    sites: list[ReferenceSite] = Field(min_length=1)


class DemoProvenance(ApiModel):
    provider: Literal["LunarWindow deterministic demo generator"] = (
        "LunarWindow deterministic demo generator"
    )
    startUtc: str
    endUtc: str
    endExclusive: Literal[True] = True
    stepMinutes: int
    timeScale: Literal["UTC"] = "UTC"
    terrainModel: Literal["synthetic"] = "synthetic"
    warning: str = (
        "Calculated visibility metrics use synthetic angles, horizon, and angular radii. "
        "No Horizons or LOLA data is used. Altitude is echoed but not modeled. "
        "Disc states approximate the horizon as horizontal across each body. "
        "Durations use held sample states; event timestamps are bracket upper bounds. "
        "Power generation, radio-link performance, and eclipses are not modeled."
    )


class Evaluation(ApiModel):
    schemaVersion: Literal["lunarwindow.evaluation.v2"] = "lunarwindow.evaluation.v2"
    dataMode: Literal["synthetic"] = "synthetic"
    siteId: str
    site: str
    lat: float
    lon: float
    altitudeKm: float
    coordinateSource: str
    horizon: list[HorizonPoint] = Field(min_length=360, max_length=360)
    series: list[VisibilitySample]
    metrics: VisibilityMetrics
    windows: VisibilityWindows
    calculation: CalculationInfo
    provenance: DemoProvenance


class Health(ApiModel):
    status: Literal["ok"] = "ok"
    service: Literal["lunarwindow-backend"] = "lunarwindow-backend"
    dataMode: Literal["synthetic"] = "synthetic"


class ErrorDetail(ApiModel):
    location: list[str | int]
    message: str
    type: str


class ApiError(ApiModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    error: ApiError
