"""Validated inputs and serializable results for the sampled visibility model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VisibilityRule = Literal["any-disc", "body-center", "full-disc"]
DiscVisibility = Literal["hidden", "partial", "full"]


class VisibilityModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, frozen=True, revalidate_instances="always"
    )


class HorizonPoint(VisibilityModel):
    az: int = Field(ge=0, lt=360)
    el: float = Field(ge=-90, le=90)


class EphemerisSample(VisibilityModel):
    t: str
    sunAz: float = Field(ge=0, lt=360)
    sunEl: float = Field(ge=-90, le=90)
    earthAz: float = Field(ge=0, lt=360)
    earthEl: float = Field(ge=-90, le=90)
    sunAngularRadiusDeg: float = Field(gt=0, lt=90)
    earthAngularRadiusDeg: float = Field(gt=0, lt=90)


class VisibilitySample(EphemerisSample):
    sunHorizonEl: float
    earthHorizonEl: float
    sunVisibility: DiscVisibility
    earthVisibility: DiscVisibility
    sunLit: bool
    earthVis: bool


class VisibilityWindow(VisibilityModel):
    """A half-open interval; boundary flags mean the actual extent is unknown."""

    startUtc: str
    endUtc: str
    durationHrs: float = Field(gt=0)
    startTruncated: bool
    endTruncated: bool


class VisibilityWindows(VisibilityModel):
    sunlit: list[VisibilityWindow]
    earthVisible: list[VisibilityWindow]
    both: list[VisibilityWindow]
    darkness: list[VisibilityWindow]
    earthBlackout: list[VisibilityWindow]


class EventBracket(VisibilityModel):
    """A falling transition was observed between afterUtc and byUtc, inclusive at byUtc."""

    afterUtc: str
    byUtc: str


class VisibilityMetrics(VisibilityModel):
    evaluatedHrs: float = Field(gt=0)
    sunlitHrs: float = Field(ge=0)
    earthVisibleHrs: float = Field(ge=0)
    bothHrs: float = Field(ge=0)
    pctSun: float = Field(ge=0, le=100)
    pctEarth: float = Field(ge=0, le=100)
    pctBoth: float = Field(ge=0, le=100)
    longestDarkHrs: float = Field(ge=0)
    longestEarthBlackoutHrs: float = Field(ge=0)
    longestBothHrs: float = Field(ge=0)
    asOfUtc: str
    nextSunset: str | None
    nextEarthset: str | None
    hoursToSunset: float | None
    hoursToEarthset: float | None
    nextSunsetBracket: EventBracket | None
    nextEarthsetBracket: EventBracket | None


class CalculationInfo(VisibilityModel):
    visibilityRule: VisibilityRule
    horizonInterpolation: Literal["circular-linear"] = "circular-linear"
    discModel: Literal["local-horizontal-limb"] = "local-horizontal-limb"
    timeModel: Literal["sample-and-hold"] = "sample-and-hold"
    eventTiming: Literal["sample-transition-brackets"] = "sample-transition-brackets"
    stepMinutes: int


class VisibilityResult(VisibilityModel):
    series: list[VisibilitySample]
    metrics: VisibilityMetrics
    windows: VisibilityWindows
    calculation: CalculationInfo
