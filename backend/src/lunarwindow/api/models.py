"""Versioned HTTP contracts; scenario inputs mirror src/domain/scenario.ts."""

from datetime import timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lunarwindow.ephemeris.models import TimeRange, parse_utc


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


class EvaluationRequest(Period):
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


class HorizonPoint(ApiModel):
    az: int = Field(ge=0, lt=360)
    el: float = Field(ge=-90, le=90)


class EvaluationSample(ApiModel):
    t: str
    sunAz: float = Field(ge=0, lt=360)
    sunEl: float = Field(ge=-90, le=90)
    earthAz: float = Field(ge=0, lt=360)
    earthEl: float = Field(ge=-90, le=90)
    sunAngularRadiusDeg: float
    earthAngularRadiusDeg: float
    sunLit: bool
    earthVis: bool


class Metrics(ApiModel):
    """Reserved for P3's next task; null never implies zero visibility."""

    pctSun: float | None = None
    pctEarth: float | None = None
    pctBoth: float | None = None
    longestDarkHrs: float | None = None
    nextSunset: str | None = None
    nextEarthset: str | None = None


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
    visibilityRule: Literal["body-center-above-synthetic-horizon"] = (
        "body-center-above-synthetic-horizon"
    )
    warning: str = (
        "Synthetic angles, horizon, angular radii, and flags for UI development only. "
        "No Horizons or LOLA data is used. Altitude is echoed but not modeled. "
        "Metrics, partial-disc visibility, and event times are not computed."
    )


class Evaluation(ApiModel):
    schemaVersion: Literal["lunarwindow.evaluation.v1"] = "lunarwindow.evaluation.v1"
    dataMode: Literal["synthetic"] = "synthetic"
    siteId: str
    site: str
    lat: float
    lon: float
    altitudeKm: float
    coordinateSource: str
    horizon: list[HorizonPoint] = Field(min_length=360, max_length=360)
    series: list[EvaluationSample]
    metrics: Metrics = Field(default_factory=Metrics)
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
