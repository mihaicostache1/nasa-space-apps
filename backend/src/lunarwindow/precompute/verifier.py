"""Read-only verification of complete bundles against their recorded jobs and sources."""

import hashlib
import stat
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.api.models import ReferenceAvailability
from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.terrain_models import (
    ReferenceEvaluationContract,
    TerrainCompatibilityProvenance,
    TerrainReferenceEvaluation,
)
from lunarwindow.ephemeris.contract import validation_session
from lunarwindow.reference import load_verified_reference_dataset, select_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.registry import load_reviewed_mask
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION, EphemerisSample

from .models import PrecomputeJob, PrecomputeManifest
from .validation import check_response_identity, request_for_key

_RESPONSE = TypeAdapter(ReferenceEvaluationContract)
_SITE_FIELDS = {"siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource"}


class PrecomputeVerificationError(ValueError):
    """A bundle is incomplete, invalid, unsupported, or inconsistent with verified sources."""


def _read_artifact(directory: Path, filename: str) -> bytes:
    path = directory / filename
    # Manifest/output basenames are fixed or contract-validated. Reject symlinks
    # and special files rather than following artifacts outside the bundle.
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Bundle artifact must be a regular file: {filename}")
    return path.read_bytes()


def _check_sources(
    job: PrecomputeJob,
    response: ReferenceEvaluationContract,
    reference_directory: Path,
    terrain_directory: Path,
) -> None:
    planned = job.evaluation
    request = request_for_key(planned)
    verified = load_verified_reference_dataset(reference_directory, planned.siteId)
    if verified.artifact_sha256 != planned.ephemerisSha256:
        raise ValueError("Verified source archive checksum differs from the recorded job.")
    selected = select_reference_dataset(
        verified.dataset,
        start_utc=request.startUtc,
        end_utc=request.endUtc,
        step_minutes=request.stepMinutes,
    )
    mask_checksum = None
    if isinstance(response, TerrainReferenceEvaluation):
        reviewed = load_reviewed_mask(terrain_directory, response.maskId)
        assessment = check_terrain_compatibility(
            reviewed.mask,
            selected,
            allow_mean_earth_approximation=planned.allowMeanEarthApproximation,
        )
        terrain = response.provenance.terrain
        if terrain.mask != reviewed.mask or terrain.artifactSha256 != reviewed.artifact_sha256:
            raise ValueError("Output terrain provenance differs from the reviewed mask artifact.")
        if terrain.compatibility != TerrainCompatibilityProvenance.from_assessment(assessment):
            raise ValueError("Output compatibility provenance differs from the verified sources.")
        mask_checksum = reviewed.artifact_sha256
    actual = build_reference_evaluation_cache_key(
        request,
        ephemeris_sha256=verified.artifact_sha256,
        terrain_mask_sha256=mask_checksum,
        calculation_model_version=VISIBILITY_MODEL_VERSION,
    )
    if actual != planned:
        raise ValueError("Verified source identity differs from the recorded evaluation job.")
    if response.model_dump(include=_SITE_FIELDS) != {name: selected[name] for name in _SITE_FIELDS}:
        raise ValueError("Output site metadata differs from the verified archive.")
    if response.provenance.ephemeris != selected["provenance"]:
        raise ValueError("Output ephemeris provenance differs from the verified archive.")
    native = verified.dataset["provenance"]
    coverage = ReferenceAvailability(
        startUtc=native["startUtc"],
        endUtc=native["endUtc"],
        stepMinutes=native["stepMinutes"],
        sampleCount=len(verified.dataset["series"]),
    )
    if response.provenance.archive != coverage:
        raise ValueError("Output archive coverage differs from the verified source bundle.")
    samples = [row.model_dump(include=set(EphemerisSample.model_fields)) for row in response.series]
    if samples != selected["series"]:
        raise ValueError("Output ephemeris samples differ from the verified source selection.")


@validation_session()
def _verify_bundle(
    directory: Path,
    *,
    reference_directory: Path,
    terrain_directory: Path | None = None,
    lookup_key: ReferenceEvaluationCacheKey | None = None,
) -> tuple[PrecomputeManifest, ReferenceEvaluationContract | None]:
    """Shared verification pass retaining at most one freshly parsed response."""
    directory, reference_directory = Path(directory), Path(reference_directory)
    terrain_directory = (
        reference_directory.parent / "terrain-masks"
        if terrain_directory is None
        else Path(terrain_directory)
    )
    try:
        manifest = PrecomputeManifest.model_validate_json(
            _read_artifact(directory, "manifest.json")
        )
        if manifest.status != "complete":
            raise ValueError("Only complete precompute bundles can be verified for reuse.")
        matched = None
        for job in manifest.jobs:
            if job.evaluation.calculationModelVersion != VISIBILITY_MODEL_VERSION:
                raise ValueError("Unsupported calculation-model version in precompute job.")
            content = _read_artifact(directory, job.output.filename)
            if hashlib.sha256(content).hexdigest() != job.output.sha256:
                raise ValueError(f"Output checksum mismatch: {job.output.filename}")
            response = _RESPONSE.validate_json(content)
            if response.schemaVersion != job.output.responseSchemaVersion:
                raise ValueError("Output response schema differs from the manifest declaration.")
            check_response_identity(response, job.evaluation)
            _check_sources(job, response, reference_directory, terrain_directory)
            if lookup_key is not None and job.evaluation == lookup_key:
                matched = response
        return manifest, matched
    except (OSError, ValueError, LookupError) as exc:
        raise PrecomputeVerificationError(
            f"Cannot verify precompute bundle at {directory}: {exc}"
        ) from exc


def verify_bundle(
    directory: Path,
    *,
    reference_directory: Path,
    terrain_directory: Path | None = None,
) -> PrecomputeManifest:
    """Verify all listed outputs and source provenance, returning no partial result.

    Each artifact is hashed and parsed from the same byte read. Requires the current
    calculation-model version and verified source files; performs no calculation,
    cache access, downloads, or writes. Returned metadata describes this verification
    snapshot, not file bytes a caller might reread later.
    """
    manifest, _ = _verify_bundle(
        directory, reference_directory=reference_directory, terrain_directory=terrain_directory
    )
    return manifest
