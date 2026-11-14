"""Evaluate verified ephemerides against geometric or reviewed terrain horizons."""

from pathlib import Path

from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.registry import load_reviewed_mask
from lunarwindow.visibility import calculate_visibility
from lunarwindow.visibility.models import HorizonPoint

from .models import ReferenceAvailability
from .reference_models import (
    ReferenceEvaluation,
    ReferenceEvaluationProvenance,
)
from .terrain_models import (
    ReferenceEvaluationContract,
    ReferenceEvaluationRequestContract,
    TerrainCompatibilityProvenance,
    TerrainMaskProvenance,
    TerrainReferenceEvaluation,
    TerrainReferenceEvaluationProvenance,
    TerrainReferenceEvaluationRequest,
)


def evaluate_reference(
    request: ReferenceEvaluationRequestContract,
    directory: Path,
    terrain_directory: Path | None = None,
) -> ReferenceEvaluationContract:
    archive = load_reference_dataset(directory, request.siteId)
    selected = select_reference_dataset(
        archive,
        start_utc=request.startUtc,
        end_utc=request.endUtc,
        step_minutes=request.stepMinutes,
    )
    terrain = None
    if isinstance(request, TerrainReferenceEvaluationRequest):
        reviewed = load_reviewed_mask(
            directory.parent / "terrain-masks" if terrain_directory is None else terrain_directory,
            request.maskId,
        )
        assessment = check_terrain_compatibility(
            reviewed.mask,
            selected,
            allow_mean_earth_approximation=request.allowMeanEarthApproximation,
        )
        horizon = reviewed.mask.horizon
        terrain = TerrainMaskProvenance(
            artifactSha256=reviewed.artifact_sha256,
            mask=reviewed.mask,
            compatibility=TerrainCompatibilityProvenance.from_assessment(assessment),
        )
    else:
        horizon = [HorizonPoint(az=az, el=0.0) for az in range(360)]
    visibility = calculate_visibility(
        selected["series"],
        horizon,
        request.to_time_range(),
        rule=request.visibilityRule,
        as_of_utc=request.asOfUtc,
    )
    source = archive["provenance"]
    common = {
        **{
            key: selected[key]
            for key in ("siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource")
        },
        "horizonMode": request.horizonMode,
        "horizon": horizon,
        "series": visibility.series,
        "metrics": visibility.metrics,
        "windows": visibility.windows,
        "calculation": visibility.calculation,
    }
    provenance = {
        "ephemeris": selected["provenance"],
        "archive": ReferenceAvailability(
            startUtc=source["startUtc"],
            endUtc=source["endUtc"],
            stepMinutes=source["stepMinutes"],
            sampleCount=len(archive["series"]),
        ),
    }
    if terrain is not None:
        return TerrainReferenceEvaluation(
            **common,
            maskId=terrain.mask.maskId,
            allowMeanEarthApproximation=request.allowMeanEarthApproximation,
            provenance=TerrainReferenceEvaluationProvenance(**provenance, terrain=terrain),
        )
    return ReferenceEvaluation(**common, provenance=ReferenceEvaluationProvenance(**provenance))
