"""Join a complete ephemeris grid to a horizon without estimating sub-step event times."""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime

from lunarwindow.ephemeris.models import TimeRange, iso_utc, parse_utc

from .models import (
    CalculationInfo,
    DiscVisibility,
    EphemerisSample,
    EventBracket,
    HorizonPoint,
    VisibilityMetrics,
    VisibilityResult,
    VisibilityRule,
    VisibilitySample,
    VisibilityWindow,
    VisibilityWindows,
)


def _horizon_at(profile: list[HorizonPoint], azimuth: float) -> float:
    """Linear interpolation includes the 359-to-0 degree seam."""
    lower = math.floor(azimuth)
    fraction = azimuth - lower
    return profile[lower].el * (1 - fraction) + profile[(lower + 1) % 360].el * fraction


def _disc(clearance: float, radius: float, rule: VisibilityRule) -> tuple[DiscVisibility, bool]:
    # Tangent upper limb exposes no disc area. Tangent lower limb hides no area.
    state: DiscVisibility = (
        "hidden" if clearance + radius <= 0 else "full" if clearance - radius >= 0 else "partial"
    )
    visible = {
        "any-disc": state != "hidden",
        "body-center": clearance > 0,
        "full-disc": state == "full",
    }[rule]
    return state, visible


def _windows(flags: list[bool], times: list[datetime], end: datetime) -> list[VisibilityWindow]:
    result = []
    run_start = None
    for index in range(len(flags) + 1):
        active = index < len(flags) and flags[index]
        if active and run_start is None:
            run_start = index
        elif not active and run_start is not None:
            start_time = times[run_start]
            end_time = times[index] if index < len(times) else end
            result.append(
                VisibilityWindow(
                    startUtc=iso_utc(start_time),
                    endUtc=iso_utc(end_time),
                    durationHrs=(end_time - start_time).total_seconds() / 3600,
                    startTruncated=run_start == 0,
                    endTruncated=index == len(flags),
                )
            )
            run_start = None
    return result


def _next_set(
    flags: list[bool], times: list[datetime], as_of: datetime
) -> tuple[str | None, float | None, EventBracket | None]:
    for index in range(1, len(flags)):
        if flags[index - 1] and not flags[index] and times[index] >= as_of:
            return (
                iso_utc(times[index]),
                (times[index] - as_of).total_seconds() / 3600,
                EventBracket(afterUtc=iso_utc(times[index - 1]), byUtc=iso_utc(times[index])),
            )
    # The range ending is never evidence that a visible body actually set.
    return None, None, None


def calculate_visibility(
    series: Sequence[EphemerisSample | Mapping],
    horizon: Sequence[HorizonPoint | Mapping],
    period: TimeRange,
    *,
    rule: VisibilityRule = "any-disc",
    as_of_utc: str | None = None,
) -> VisibilityResult:
    """Use each observed state on [t, next t), clipping the last bin at period.end.

    Inputs must cover the exact TimeRange grid. The horizon is one elevation per
    integer degree, ordered 0..359. No gaps, fabricated crossings, or mutation of
    source samples are allowed. A local horizontal horizon across each disc is
    an approximation; neighboring terrain across its angular width is not traced.
    """
    if rule not in ("any-disc", "body-center", "full-disc"):
        raise ValueError("Unsupported visibility rule.")
    start, end = period.start, period.end
    as_of = parse_utc(as_of_utc) if as_of_utc is not None else start
    if not start <= as_of < end:
        raise ValueError("asOfUtc must be within [startUtc, endUtc).")
    if len(horizon) != 360:
        raise ValueError("A horizon requires exactly 360 points ordered by azimuth 0..359.")
    profile = [HorizonPoint.model_validate(point) for point in horizon]
    if any(point.az != index for index, point in enumerate(profile)):
        raise ValueError("Horizon azimuths must be unique and ordered 0..359.")
    if len(series) != period.sample_count:
        raise ValueError("Series length does not match the declared sampling grid.")

    samples, times = [], []
    for index, source in enumerate(series):
        row = EphemerisSample.model_validate(source)
        instant = parse_utc(row.t)
        if instant != start + period.step * index:
            raise ValueError(f"Missing, duplicate, or off-grid sample at index {index}.")
        times.append(instant)
        sun_horizon = _horizon_at(profile, row.sunAz)
        earth_horizon = _horizon_at(profile, row.earthAz)
        sun_state, sun_lit = _disc(row.sunEl - sun_horizon, row.sunAngularRadiusDeg, rule)
        earth_state, earth_vis = _disc(row.earthEl - earth_horizon, row.earthAngularRadiusDeg, rule)
        samples.append(
            VisibilitySample(
                **(row.model_dump() | {"t": iso_utc(instant)}),
                sunHorizonEl=sun_horizon,
                earthHorizonEl=earth_horizon,
                sunVisibility=sun_state,
                earthVisibility=earth_state,
                sunLit=sun_lit,
                earthVis=earth_vis,
            )
        )

    sun_flags = [row.sunLit for row in samples]
    earth_flags = [row.earthVis for row in samples]
    both_flags = [sun and earth for sun, earth in zip(sun_flags, earth_flags)]
    windows = VisibilityWindows(
        sunlit=_windows(sun_flags, times, end),
        earthVisible=_windows(earth_flags, times, end),
        both=_windows(both_flags, times, end),
        darkness=_windows([not flag for flag in sun_flags], times, end),
        earthBlackout=_windows([not flag for flag in earth_flags], times, end),
    )

    weights = [
        ((times[index + 1] if index + 1 < len(times) else end) - instant).total_seconds()
        for index, instant in enumerate(times)
    ]

    def seconds(flags: list[bool]) -> float:
        return math.fsum(weight for weight, visible in zip(weights, flags) if visible)

    def longest(items: list[VisibilityWindow]) -> float:
        return max((item.durationHrs for item in items), default=0)

    total_seconds = (end - start).total_seconds()
    sun_seconds = seconds(sun_flags)
    earth_seconds = seconds(earth_flags)
    both_seconds = seconds(both_flags)
    sunset, hours_to_sunset, sunset_bracket = _next_set(sun_flags, times, as_of)
    earthset, hours_to_earthset, earthset_bracket = _next_set(earth_flags, times, as_of)
    metrics = VisibilityMetrics(
        evaluatedHrs=total_seconds / 3600,
        sunlitHrs=sun_seconds / 3600,
        earthVisibleHrs=earth_seconds / 3600,
        bothHrs=both_seconds / 3600,
        pctSun=100 * sun_seconds / total_seconds,
        pctEarth=100 * earth_seconds / total_seconds,
        pctBoth=100 * both_seconds / total_seconds,
        longestDarkHrs=longest(windows.darkness),
        longestEarthBlackoutHrs=longest(windows.earthBlackout),
        longestBothHrs=longest(windows.both),
        asOfUtc=iso_utc(as_of),
        nextSunset=sunset,
        nextEarthset=earthset,
        hoursToSunset=hours_to_sunset,
        hoursToEarthset=hours_to_earthset,
        nextSunsetBracket=sunset_bracket,
        nextEarthsetBracket=earthset_bracket,
    )
    return VisibilityResult(
        series=samples,
        metrics=metrics,
        windows=windows,
        calculation=CalculationInfo(visibilityRule=rule, stepMinutes=period.step_minutes),
    )
