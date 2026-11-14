"""Contracts for offline reference-evaluation bundles."""

from .generator import PrecomputeGenerationError, generate_bundle
from .models import PrecomputeJob, PrecomputeManifest, PrecomputeOutput
from .verifier import PrecomputeVerificationError, verify_bundle

__all__ = [
    "PrecomputeGenerationError",
    "PrecomputeJob",
    "PrecomputeManifest",
    "PrecomputeOutput",
    "PrecomputeVerificationError",
    "generate_bundle",
    "verify_bundle",
]
