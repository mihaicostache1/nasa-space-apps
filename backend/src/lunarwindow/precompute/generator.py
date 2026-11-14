"""Generate explicit offline evaluation jobs with checkpointed manifest publication."""

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from lunarwindow.api.reference_provider import evaluate_reference
from lunarwindow.api.terrain_models import ReferenceEvaluationContract
from lunarwindow.ephemeris.storage import atomic_write

from .models import PrecomputeJob, PrecomputeManifest, PrecomputeOutput
from .validation import check_response_identity, request_for_key

_RESPONSE = TypeAdapter(ReferenceEvaluationContract)


class PrecomputeGenerationError(RuntimeError):
    """A job failed; the output directory retains an incomplete diagnostic manifest."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _manifest(run_id: str, created_at: str, jobs: list[PrecomputeJob]) -> PrecomputeManifest:
    complete = all(job.status == "complete" for job in jobs)
    return PrecomputeManifest(
        runId=run_id,
        createdAtUtc=created_at,
        completedAtUtc=_utc_now() if complete else None,
        status="complete" if complete else "incomplete",
        jobs=jobs,
    )


def generate_bundle(
    jobs: Sequence[PrecomputeJob],
    *,
    run_id: str,
    reference_directory: Path,
    output_directory: Path,
    terrain_directory: Path | None = None,
) -> PrecomputeManifest:
    """Generate pending jobs into a new directory; never overwrite or resume a run.

    Validate the entire plan before writes. Each job rechecks current artifacts and
    their exact planned identity through the existing provider, with no result cache.
    Successful writes are checkpointed atomically. A failed job stops the run and
    raises PrecomputeGenerationError, retaining an incomplete manifest. Manifest I/O
    failures may instead raise OSError; the last atomic checkpoint remains authoritative.
    """
    manifest = _manifest(run_id, _utc_now(), list(jobs))
    if any(job.status != "pending" for job in manifest.jobs):
        raise ValueError("Generation requires an explicit list of pending jobs.")
    working = list(manifest.jobs)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = output_directory / "manifest.json"
    atomic_write(manifest_path, manifest.model_dump_json(indent=2) + "\n")

    for index, job in enumerate(working):
        failure_index = index
        try:
            response = evaluate_reference(
                request_for_key(job.evaluation),
                reference_directory,
                terrain_directory,
                expected_key=job.evaluation,
            )
            serialized = response.model_dump_json(indent=2) + "\n"
            validated = _RESPONSE.validate_json(serialized)
            check_response_identity(validated, job.evaluation)
            filename = f"{job.evaluation.digest}.json"
            path = output_directory / filename
            atomic_write(path, serialized)
            saved = path.read_bytes()
            if saved != serialized.encode("utf-8"):
                raise ValueError("Saved evaluation bytes differ from the validated response.")
            working[index] = PrecomputeJob(
                evaluation=job.evaluation,
                status="complete",
                output=PrecomputeOutput(
                    filename=filename,
                    sha256=hashlib.sha256(saved).hexdigest(),
                    responseSchemaVersion=validated.schemaVersion,
                ),
            )
            if index == len(working) - 1:
                # Check all outputs again before the only successful completion
                # marker, including files written while earlier jobs ran.
                for checked_index, completed in enumerate(working):
                    failure_index = checked_index
                    saved = (output_directory / completed.output.filename).read_bytes()
                    if hashlib.sha256(saved).hexdigest() != completed.output.sha256:
                        raise ValueError("Published output checksum changed before run completion.")
                failure_index = index
            manifest = _manifest(run_id, manifest.createdAtUtc, working)
            atomic_write(manifest_path, manifest.model_dump_json(indent=2) + "\n")
        except Exception as exc:
            failed_job = working[failure_index]
            working[failure_index] = PrecomputeJob(
                evaluation=failed_job.evaluation,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            failed = _manifest(run_id, manifest.createdAtUtc, working)
            atomic_write(manifest_path, failed.model_dump_json(indent=2) + "\n")
            raise PrecomputeGenerationError(
                f"Job {failed_job.evaluation.digest} failed; incomplete manifest retained at {manifest_path}."
            ) from exc
    return manifest
