"""Versioned bookkeeping contract; validates metadata without reading artifact files."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from lunarwindow.api.reference_cache_key import ReferenceEvaluationCacheKey
from lunarwindow.terrain.models import NonBlank, Sha256, Slug, UtcTimestamp
from lunarwindow.visibility.models import VisibilityModel


class PrecomputeOutput(VisibilityModel):
    """One serialized evaluation beside the manifest, named by its evaluation key."""

    filename: str = Field(pattern=r"^[0-9a-f]{64}\.json$")
    sha256: Sha256
    responseSchemaVersion: Literal[
        "lunarwindow.reference-evaluation.v1", "lunarwindow.reference-evaluation.v2"
    ]


class PrecomputeJob(VisibilityModel):
    evaluation: ReferenceEvaluationCacheKey
    status: Literal["pending", "complete", "failed"]
    output: PrecomputeOutput | None = None
    error: NonBlank | None = None

    @model_validator(mode="after")
    def validate_job_state(self) -> Self:
        if (
            self.evaluation.horizonMode == "terrain"
            and not self.evaluation.allowMeanEarthApproximation
        ):
            raise ValueError(
                "Terrain precompute jobs require explicit frame-approximation acceptance."
            )
        if self.status == "complete":
            if self.output is None or self.error is not None:
                raise ValueError("Complete jobs require an output and cannot declare an error.")
            if self.output.filename != f"{self.evaluation.digest}.json":
                raise ValueError("Output filename must match the evaluation cache-key digest.")
            expected = (
                "lunarwindow.reference-evaluation.v2"
                if self.evaluation.horizonMode == "terrain"
                else "lunarwindow.reference-evaluation.v1"
            )
            if self.output.responseSchemaVersion != expected:
                raise ValueError("Output response schema must match the job's horizon mode.")
        elif self.output is not None:
            raise ValueError("Only complete jobs can declare a published output.")
        elif self.status == "failed" and self.error is None:
            raise ValueError("Failed jobs require an error description.")
        elif self.status == "pending" and self.error is not None:
            raise ValueError("Pending jobs cannot declare an error.")
        return self


class PrecomputeManifest(VisibilityModel):
    schemaVersion: Literal["lunarwindow.precompute-manifest.v1"] = (
        "lunarwindow.precompute-manifest.v1"
    )
    runId: Slug
    createdAtUtc: UtcTimestamp
    completedAtUtc: UtcTimestamp | None = None
    status: Literal["incomplete", "complete"]
    jobs: list[PrecomputeJob] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_run_state(self) -> Self:
        identities = [job.evaluation.digest for job in self.jobs]
        if len(identities) != len(set(identities)):
            raise ValueError("A manifest must contain unique evaluation jobs.")
        all_complete = all(job.status == "complete" for job in self.jobs)
        if self.status == "complete":
            if not all_complete or self.completedAtUtc is None:
                raise ValueError("Complete runs require all jobs complete and completedAtUtc.")
            if datetime.fromisoformat(self.completedAtUtc) < datetime.fromisoformat(
                self.createdAtUtc
            ):
                raise ValueError("completedAtUtc cannot precede createdAtUtc.")
        elif all_complete or self.completedAtUtc is not None:
            raise ValueError(
                "Incomplete runs require unfinished/failed jobs and no completedAtUtc."
            )
        return self
