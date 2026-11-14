"""Shared request/response identity checks; source-file verification is separate."""

from pydantic import TypeAdapter

from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.reference_models import ReferenceSiteEvaluationRequest
from lunarwindow.api.terrain_models import (
    ReferenceEvaluationContract,
    ReferenceEvaluationRequestContract,
    TerrainReferenceEvaluation,
)

_REQUEST = TypeAdapter(ReferenceEvaluationRequestContract)


def request_for_key(key: ReferenceEvaluationCacheKey) -> ReferenceEvaluationRequestContract:
    fields = set(ReferenceSiteEvaluationRequest.model_fields) | {"horizonMode"}
    if key.horizonMode == "terrain":
        fields |= {"maskId", "allowMeanEarthApproximation"}
    return _REQUEST.validate_python(key.model_dump(include=fields))


def check_response_identity(
    response: ReferenceEvaluationContract, planned: ReferenceEvaluationCacheKey
) -> None:
    """Match response options and terrain identity, without claiming source-byte proof."""
    source = response.provenance.ephemeris
    request = {
        "siteId": response.siteId,
        "horizonMode": response.horizonMode,
        "startUtc": source["startUtc"],
        "endUtc": source["endUtc"],
        "stepMinutes": source["stepMinutes"],
        "visibilityRule": response.calculation.visibilityRule,
        "asOfUtc": response.metrics.asOfUtc,
    }
    mask_checksum = None
    if isinstance(response, TerrainReferenceEvaluation):
        request.update(
            maskId=response.maskId, allowMeanEarthApproximation=response.allowMeanEarthApproximation
        )
        mask_checksum = response.provenance.terrain.artifactSha256
    actual = build_reference_evaluation_cache_key(
        _REQUEST.validate_python(request),
        # Full archive hash/model version are not duplicated in the response.
        # The provider guard or standalone verifier must establish these separately.
        ephemeris_sha256=planned.ephemerisSha256,
        terrain_mask_sha256=mask_checksum,
        calculation_model_version=planned.calculationModelVersion,
    )
    if actual != planned:
        raise ValueError("Evaluation response does not match the recorded job identity.")
