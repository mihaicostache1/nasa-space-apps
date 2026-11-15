"""Reviewed external terrain observations: evidence checks, not automatic authentication."""

from pathlib import Path
from typing import Literal

from build_surface_spice_reference import sha256
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SurfaceObserver(EvidenceModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    surfaceElevationM: float
    mastHeightM: float = Field(ge=0)
    altitudeKm: float


class TerrainObservation(EvidenceModel):
    caseId: str = Field(min_length=1, max_length=100)
    siteId: str
    timestampUtc: str
    body: Literal["sun", "earth"]
    visible: bool
    observerKind: Literal["surface"]
    observer: SurfaceObserver
    quantity: Literal["terrain-visibility-at-observer"]
    visibilityRule: Literal["any-disc"]
    bodyDefinition: Literal["finite-disc-any-part"]
    refractionModel: Literal["none"]
    referenceFrame: Literal["MOON_ME_DE421"]
    referenceRadiusKm: Literal[1737.4]
    sourceType: Literal["dated-terrain-simulation", "surface-observation"]
    sourceUrl: HttpUrl
    sourceVersion: str = Field(min_length=1)
    method: str = Field(min_length=20)
    demDescription: str = Field(min_length=10)
    frameAssessment: str = Field(min_length=20)
    independenceStatement: str = Field(min_length=20)
    independentOfLunarWindow: bool
    evidencePath: str
    evidenceSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=2)
    reviewedAtUtc: str
    reviewNotes: str = Field(min_length=20)


class TerrainEvidence(EvidenceModel):
    schemaVersion: Literal["lunarwindow.terrain-observations.v1"]
    observations: list[TerrainObservation] = Field(min_length=1)


def assess_terrain_evidence(body, datasets, actual_states, evidence_root: Path):
    """Reject camera/average/self-derived cases and preserve the recorded review."""
    from lunarwindow.ephemeris.models import parse_utc

    records = TerrainEvidence.model_validate(body)
    seen = set()
    coverage = set()
    comparisons = []
    for record in records.observations:
        if record.caseId in seen:
            raise ValueError("Duplicate external case ID.")
        seen.add(record.caseId)
        if not record.independentOfLunarWindow:
            raise ValueError(
                "A backend-derived prediction is not independent terrain evidence."
            )
        if not record.timestampUtc.endswith("Z") or not record.reviewedAtUtc.endswith(
            "Z"
        ):
            raise ValueError(
                "External observation and review timestamps must use UTC Z."
            )
        parse_utc(record.reviewedAtUtc)
        parse_utc(record.timestampUtc)
        dataset = datasets.get(record.siteId)
        if dataset is None or record.siteId not in actual_states:
            raise ValueError(
                "External case has no matching reviewed terrain evaluation."
            )
        observer = record.observer
        expected = {key: dataset[key] for key in ("lat", "lon", "altitudeKm")}
        if (
            any(getattr(observer, key) != value for key, value in expected.items())
            or observer.mastHeightM != 0
            or observer.surfaceElevationM != dataset["altitudeKm"] * 1000
        ):
            raise ValueError(
                "External observer differs from the archived ground + 0 m observer."
            )
        actual = actual_states[record.siteId].get(record.timestampUtc)
        if actual is None:
            raise ValueError(
                "External UTC must match an actual archived sample; no interpolation."
            )
        relative = Path(record.evidencePath)
        path = evidence_root / relative
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.parts[0] != "evidence"
            or path.is_symlink()
            or not path.resolve().is_relative_to(evidence_root.resolve())
        ):
            raise ValueError(
                "Evidence must be a local file within validation/evidence."
            )
        if (
            not path.is_file()
            or path.stat().st_size == 0
            or sha256(path) != record.evidenceSha256
        ):
            raise ValueError(
                "External evidence file is missing, empty, or has changed."
            )
        calculated = actual[record.body]
        matched = calculated == record.visible
        coverage.add((record.body, record.visible))
        comparisons.append(
            {
                "caseId": record.caseId,
                "siteId": record.siteId,
                "timestampUtc": record.timestampUtc,
                "body": record.body,
                "referenceVisible": record.visible,
                "calculatedVisible": calculated,
                "status": "pass" if matched else "fail",
                "sourceUrl": str(record.sourceUrl),
                "evidencePath": record.evidencePath,
                "evidenceSha256": record.evidenceSha256,
                "reviewer": record.reviewer,
                "reviewedAtUtc": record.reviewedAtUtc,
                "reviewNotes": record.reviewNotes,
                "independenceStatement": record.independenceStatement,
            }
        )
    complete = coverage == {
        ("sun", True),
        ("sun", False),
        ("earth", True),
        ("earth", False),
    }
    failed = any(item["status"] == "fail" for item in comparisons)
    return {
        "status": "fail"
        if failed
        else "pass-recorded-cases"
        if complete
        else "incomplete-coverage",
        "coverageComplete": complete,
        "scope": "Reviewed recorded samples only; no event-time or mission certification. Reviewer identity and independence are human attestations, not authenticated by this tool.",
        "comparisons": comparisons,
    }
