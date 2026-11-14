"""Contracts for offline reference-evaluation bundles."""

from .generator import PrecomputeGenerationError, generate_bundle
from .models import PrecomputeJob, PrecomputeManifest, PrecomputeOutput

__all__ = [
    "PrecomputeGenerationError",
    "PrecomputeJob",
    "PrecomputeManifest",
    "PrecomputeOutput",
    "generate_bundle",
]
