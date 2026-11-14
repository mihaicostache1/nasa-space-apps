"""Load a reviewed terrain-mask artifact without downloads or file changes."""

import hashlib
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .models import Sha256, TerrainMask

_CHECKSUM = TypeAdapter(Sha256)


def load_terrain_mask(path: str | Path, *, expected_sha256: str) -> TerrainMask:
    """Verify one byte snapshot against a trusted checksum, then validate its contract.

    The caller supplies the file and its reviewed SHA-256 explicitly. Raise
    ValueError for an invalid checksum, unreadable file, or invalid mask. Return
    the complete model, including provenance; observer/frame compatibility and
    the scientific validation of the producer's DEMs are separate checks.
    """
    try:
        checksum = _CHECKSUM.validate_python(expected_sha256, strict=True)
    except ValidationError as exc:
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters.") from exc

    path = Path(path)
    try:
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError("SHA-256 checksum mismatch.")
        return TerrainMask.model_validate_json(content)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load terrain mask at {path}: {exc}") from exc
