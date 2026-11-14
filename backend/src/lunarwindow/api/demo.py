"""Repeatable synthetic curves for frontend integration, with no NASA calls."""

import math
from datetime import datetime, timezone

from lunarwindow.ephemeris.models import iso_utc
from lunarwindow.visibility import calculate_visibility
from lunarwindow.visibility.models import EphemerisSample

from .models import (
    DemoProvenance,
    DemoSite,
    Evaluation,
    EvaluationRequest,
    HorizonPoint,
)

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class DemoProvider:
    """Replace this dependency when real-data integration becomes P3's task."""

    def list_sites(self) -> list[DemoSite]:
        return [
            DemoSite(id="demo-polar-a", name="Demo polar point A", lat=-89, lon=0),
            DemoSite(id="demo-polar-b", name="Demo polar point B", lat=-88.5, lon=30),
            DemoSite(id="demo-equatorial", name="Demo equatorial point", lat=0, lon=0),
        ]

    def evaluate(self, request: EvaluationRequest, site_id: str = "custom") -> Evaluation:
        period = request.to_time_range()
        location = request.location
        offset = math.radians(location.longitudeDeg)
        horizon = [
            HorizonPoint(az=az, el=round(1.5 + math.sin(math.radians(az) * 3 + offset), 6))
            for az in range(360)
        ]
        series = []
        for index in range(period.sample_count):
            instant = period.start + period.step * index
            hours = (instant - EPOCH).total_seconds() / 3600
            phase = math.tau * hours / (29.5 * 24) + offset
            sun_az = round(math.degrees(phase) % 360, 6) % 360
            earth_az = round((location.longitudeDeg + 5 * math.sin(phase / 2)) % 360, 6) % 360
            sun_el = round((90 - abs(location.latitudeDeg)) * math.sin(phase) + 1.5, 6)
            sun_el = max(-90, min(90, sun_el))
            earth_el = round(4 * math.cos(phase / 2) + 2, 6)
            series.append(
                EphemerisSample(
                    t=iso_utc(instant),
                    sunAz=sun_az,
                    sunEl=sun_el,
                    earthAz=earth_az,
                    earthEl=earth_el,
                    sunAngularRadiusDeg=0.27,
                    earthAngularRadiusDeg=0.95,
                )
            )
        visibility = calculate_visibility(
            series,
            horizon,
            period,
            rule=request.visibilityRule,
            as_of_utc=request.asOfUtc,
        )
        return Evaluation(
            siteId=site_id,
            site=request.name,
            lat=location.latitudeDeg,
            lon=location.longitudeDeg,
            altitudeKm=location.altitudeKm,
            coordinateSource="Illustrative coordinates for UI development; not a verified site.",
            horizon=horizon,
            series=visibility.series,
            metrics=visibility.metrics,
            windows=visibility.windows,
            calculation=visibility.calculation,
            provenance=DemoProvenance(
                startUtc=iso_utc(period.start),
                endUtc=iso_utc(period.end),
                stepMinutes=period.step_minutes,
            ),
        )
