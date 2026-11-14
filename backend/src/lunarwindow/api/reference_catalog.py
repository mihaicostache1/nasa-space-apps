"""Join verified archive coverage with usable, reviewed terrain registrations."""

from pathlib import Path

from lunarwindow.reference import load_reference_catalog, load_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.registry import load_reviewed_mask, reviewed_mask_ids

from .models import ReferenceSiteCatalog, ReferenceTerrainMask


def build_reference_catalog(directory: Path, terrain_directory: Path) -> ReferenceSiteCatalog:
    """Fail closed if a registered mask cannot be verified against its site's archive.

    Only server registrations are considered. Preliminary horizons and unregistered
    JSON files are never advertised. Checking the opt-in policy here describes a
    capability; it does not grant acceptance on behalf of an evaluation caller.
    """
    sites = load_reference_catalog(directory)
    for site in sites:
        masks = []
        ids = reviewed_mask_ids(site["id"])
        if ids:
            dataset = load_reference_dataset(directory, site["id"])
            for mask_id in ids:
                reviewed = load_reviewed_mask(terrain_directory, mask_id)
                mask = reviewed.mask
                assessment = check_terrain_compatibility(
                    mask, dataset, allow_mean_earth_approximation=True
                )
                masks.append(
                    ReferenceTerrainMask(
                        maskId=mask.maskId,
                        artifactSha256=reviewed.artifact_sha256,
                        observer=mask.observer,
                        referenceFrame=mask.referenceFrame,
                        demSources=mask.provenance.sources,
                        requiresMeanEarthApproximation=True,
                        framePolicy=assessment.frame_policy,
                        limitation=assessment.limitation,
                    )
                )
        site["terrainMasks"] = masks
        site["supportedHorizonModes"] = ["geometric", "terrain"] if masks else ["geometric"]
    return ReferenceSiteCatalog(sites=sites)
