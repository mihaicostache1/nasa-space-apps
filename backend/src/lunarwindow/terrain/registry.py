"""Server-reviewed terrain artifacts; requests select IDs rather than filesystem paths."""

from dataclasses import dataclass
from pathlib import Path

from .loader import load_terrain_mask
from .models import TerrainMask


class UnknownTerrainMaskError(LookupError):
    """No reviewed artifact is registered for the requested mask ID."""


@dataclass(frozen=True)
class ReviewedTerrainMask:
    mask: TerrainMask
    artifact_sha256: str


# Reviewed GIS handoff. Never derive trust from a request or a mutable sidecar.
_MASKS = {
    "lola-site01-reference-mast-0m": (
        "lola-site01-reference",
        "lola-site01-reference-mast-0m.json",
        "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d",
    ),
}


def load_reviewed_mask(directory: str | Path, mask_id: str) -> ReviewedTerrainMask:
    try:
        site_id, filename, checksum = _MASKS[mask_id]
    except KeyError as exc:
        raise UnknownTerrainMaskError(f"Unknown reviewed terrain mask: {mask_id}") from exc
    mask = load_terrain_mask(Path(directory) / filename, expected_sha256=checksum)
    if mask.maskId != mask_id or mask.siteId != site_id:
        raise ValueError("Reviewed terrain mask identity differs from its registration.")
    return ReviewedTerrainMask(mask=mask, artifact_sha256=checksum)
