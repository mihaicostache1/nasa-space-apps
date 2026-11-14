"""Contracts for offline reference-evaluation bundles."""

from .generator import PrecomputeGenerationError, generate_bundle
from .loader import load_precomputed_evaluation
from .models import PrecomputeJob, PrecomputeManifest, PrecomputeOutput
from .verifier import PrecomputeVerificationError, verify_bundle

__all__ = [
    "PrecomputeGenerationError",
    "PrecomputeJob",
    "PrecomputeManifest",
    "PrecomputeOutput",
    "PrecomputeVerificationError",
    "generate_bundle",
    "load_precomputed_evaluation",
    "verify_bundle",
]
