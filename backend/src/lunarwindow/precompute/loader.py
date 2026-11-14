"""Look up one evaluation from the exact response snapshots verified during this call."""

from pathlib import Path

from lunarwindow.api.reference_cache_key import ReferenceEvaluationCacheKey
from lunarwindow.api.terrain_models import ReferenceEvaluationContract
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION

from .verifier import PrecomputeVerificationError, _verify_bundle


def load_precomputed_evaluation(
    directory: Path,
    key: ReferenceEvaluationCacheKey,
    *,
    reference_directory: Path,
    terrain_directory: Path | None = None,
) -> ReferenceEvaluationContract | None:
    """Return a fresh verified response, or None for an absent key in a valid bundle.

    Verify the entire complete bundle and its current sources before returning a
    hit or miss. Invalid bundles/sources are errors, never misses. No artifact is
    reread after verification, and no response object is shared between calls.
    """
    key = ReferenceEvaluationCacheKey.model_validate(key)
    if key.calculationModelVersion != VISIBILITY_MODEL_VERSION:
        raise PrecomputeVerificationError("Unsupported calculation-model version in lookup key.")
    _, response = _verify_bundle(
        directory,
        reference_directory=reference_directory,
        terrain_directory=terrain_directory,
        lookup_key=key,
    )
    return response
