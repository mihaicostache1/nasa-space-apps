"""Evaluate verified ephemerides against geometric or reviewed terrain horizons."""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from lunarwindow.reference import load_verified_reference_dataset, select_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.registry import load_reviewed_mask
from lunarwindow.visibility import calculate_visibility
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION, HorizonPoint

from .models import ReferenceAvailability
from .reference_cache import ReferenceEvaluationCache
from .reference_cache_key import ReferenceEvaluationCacheKey, build_reference_evaluation_cache_key
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

_RESPONSE = TypeAdapter(ReferenceEvaluationContract)


def evaluate_reference(
    request: ReferenceEvaluationRequestContract,
    directory: Path,
    terrain_directory: Path | None = None,
    *,
    cache: ReferenceEvaluationCache | None = None,
    expected_key: ReferenceEvaluationCacheKey | None = None,
    precomputed_directory: Path | None = None,
) -> ReferenceEvaluationContract:
    verified = load_verified_reference_dataset(directory, request.siteId)
    archive = verified.dataset
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

    # A cached success never bypasses source integrity, selection, or policy checks.
    if cache is not None or expected_key is not None or precomputed_directory is not None:
        key = build_reference_evaluation_cache_key(
            request,
            ephemeris_sha256=verified.artifact_sha256,
            terrain_mask_sha256=terrain.artifactSha256 if terrain is not None else None,
            calculation_model_version=VISIBILITY_MODEL_VERSION,
        )
        if expected_key is not None and key != ReferenceEvaluationCacheKey.model_validate(
            expected_key
        ):
            raise ValueError(
                "Verified evaluation inputs differ from the planned precompute identity."
            )
    if precomputed_directory is not None:
        # Load lazily: the offline generator itself imports this provider.
        from lunarwindow.precompute.loader import load_precomputed_evaluation

        saved = load_precomputed_evaluation(
            precomputed_directory,
            key,
            reference_directory=directory,
            terrain_directory=terrain_directory,
        )
        if saved is not None:
            return saved
    if cache is not None:
        snapshot = cache.get(key)
        if snapshot is not None:
            try:
                # Deserialize a fresh validated model; callers never share cached state.
                return _RESPONSE.validate_json(snapshot)
            except ValidationError:
                # An invalid internal snapshot is a miss, never a successful response.
                pass

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
        result = TerrainReferenceEvaluation(
            **common,
            maskId=terrain.mask.maskId,
            allowMeanEarthApproximation=request.allowMeanEarthApproximation,
            provenance=TerrainReferenceEvaluationProvenance(**provenance, terrain=terrain),
        )
    else:
        result = ReferenceEvaluation(
            **common, provenance=ReferenceEvaluationProvenance(**provenance)
        )
    if cache is not None:
        cache.put(key, result.model_dump_json().encode("utf-8"))
    return result
