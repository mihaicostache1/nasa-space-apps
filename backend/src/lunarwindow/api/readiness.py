"""Verify configured reference capabilities without calculating an evaluation."""

from pathlib import Path

from lunarwindow.ephemeris.contract import validation_session

from .models import Readiness
from .reference_cache import ReferenceEvaluationCache
from .reference_catalog import build_reference_catalog


@validation_session()
def check_readiness(
    reference_directory: Path,
    terrain_directory: Path,
    precomputed_directory: Path | None,
    cache: ReferenceEvaluationCache,
) -> Readiness:
    catalog = build_reference_catalog(reference_directory, terrain_directory)
    jobs = 0
    if precomputed_directory is not None:
        from lunarwindow.precompute.verifier import verify_bundle

        manifest = verify_bundle(
            precomputed_directory,
            reference_directory=reference_directory,
            terrain_directory=terrain_directory,
        )
        jobs = len(manifest.jobs)
    limits = cache.info()
    return Readiness(
        referenceSiteCount=len(catalog.sites),
        terrainMaskCount=sum(len(site.terrainMasks) for site in catalog.sites),
        precomputed="verified" if precomputed_directory is not None else "disabled",
        precomputedJobCount=jobs,
        cacheMaxEntries=limits.max_entries,
        cacheMaxBytes=limits.max_bytes,
    )
