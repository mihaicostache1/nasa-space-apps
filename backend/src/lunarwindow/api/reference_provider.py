"""Evaluate verified archived ephemerides against an explicit geometric horizon."""

from pathlib import Path

from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.visibility import calculate_visibility
from lunarwindow.visibility.models import HorizonPoint

from .models import ReferenceAvailability
from .reference_models import (
    ReferenceEvaluation,
    ReferenceEvaluationProvenance,
    ReferenceEvaluationRequest,
)


def evaluate_reference(request: ReferenceEvaluationRequest, directory: Path) -> ReferenceEvaluation:
    archive = load_reference_dataset(directory, request.siteId)
    selected = select_reference_dataset(
        archive,
        start_utc=request.startUtc,
        end_utc=request.endUtc,
        step_minutes=request.stepMinutes,
    )
    horizon = [HorizonPoint(az=az, el=0.0) for az in range(360)]
    visibility = calculate_visibility(
        selected["series"],
        horizon,
        request.to_time_range(),
        rule=request.visibilityRule,
        as_of_utc=request.asOfUtc,
    )
    source = archive["provenance"]
    return ReferenceEvaluation(
        horizonMode=request.horizonMode,
        siteId=selected["siteId"],
        site=selected["site"],
        lat=selected["lat"],
        lon=selected["lon"],
        altitudeKm=selected["altitudeKm"],
        coordinateSource=selected["coordinateSource"],
        horizon=horizon,
        series=visibility.series,
        metrics=visibility.metrics,
        windows=visibility.windows,
        calculation=visibility.calculation,
        provenance=ReferenceEvaluationProvenance(
            ephemeris=selected["provenance"],
            archive=ReferenceAvailability(
                startUtc=source["startUtc"],
                endUtc=source["endUtc"],
                stepMinutes=source["stepMinutes"],
                sampleCount=len(archive["series"]),
            ),
        ),
    )
