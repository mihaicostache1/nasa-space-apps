"""Contracts for the next reference-evaluation endpoint; no retrieval or calculation."""

from typing import Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, field_validator, model_validator

from lunarwindow.ephemeris.contract import dataset_schema, validate_dataset
from lunarwindow.ephemeris.models import TimeRange, parse_utc
from lunarwindow.visibility.models import (
    CalculationInfo,
    EphemerisSample,
    HorizonPoint,
    VisibilityMetrics,
    VisibilitySample,
    VisibilityWindows,
)

from .models import ApiModel, EvaluationOptions, ReferenceAvailability

EPHEMERIS_PROVENANCE_SCHEMA = dataset_schema()["properties"]["provenance"]


class ReferenceEvaluationRequest(EvaluationOptions):
    siteId: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", examples=["lola-site01-reference"])
    horizonMode: Literal["geometric"] = Field(
        description="Explicitly select a flat 0-degree horizon without terrain masking"
    )


class ReferenceEvaluationProvenance(ApiModel):
    ephemeris: dict = Field(
        description="Selected-grid provenance retaining the original NASA request evidence",
        json_schema_extra=EPHEMERIS_PROVENANCE_SCHEMA,
    )
    archive: ReferenceAvailability
    warning: str = Field(
        default=(
            "Geometric visibility uses archived ephemerides and a flat 0-degree horizon. "
            "Local terrain, eclipses, power generation, and radio-link performance are not modeled. "
            "Durations and setting brackets depend on the sampling interval."
        ),
        min_length=1,
    )

    @field_validator("ephemeris")
    @classmethod
    def validate_source_evidence(cls, value: dict) -> dict:
        try:
            Draft202012Validator(
                EPHEMERIS_PROVENANCE_SCHEMA, format_checker=FormatChecker()
            ).validate(value)
        except ValidationError as exc:
            raise ValueError(f"Invalid reference ephemeris provenance: {exc.message}") from exc
        return value


class ReferenceEvaluation(ApiModel):
    schemaVersion: Literal["lunarwindow.reference-evaluation.v1"] = (
        "lunarwindow.reference-evaluation.v1"
    )
    dataMode: Literal["reference"] = "reference"
    horizonMode: Literal["geometric"]
    siteId: str
    site: str
    lat: float
    lon: float
    altitudeKm: float
    coordinateSource: str
    horizon: list[HorizonPoint] = Field(min_length=360, max_length=360)
    series: list[VisibilitySample] = Field(min_length=1, max_length=10_000)
    metrics: VisibilityMetrics
    windows: VisibilityWindows
    calculation: CalculationInfo
    provenance: ReferenceEvaluationProvenance

    @model_validator(mode="after")
    def validate_reference_model(self) -> Self:
        if any(point.az != index or point.el != 0 for index, point in enumerate(self.horizon)):
            raise ValueError(
                "A geometric horizon must contain ordered azimuths 0..359 at 0 degrees."
            )
        if any(row.sunHorizonEl != 0 or row.earthHorizonEl != 0 for row in self.series):
            raise ValueError("Geometric sample horizon elevations must be 0 degrees.")
        source = self.provenance.ephemeris
        # Reuse P1's coordinate, observer, target, and sampling-grid checks.
        validate_dataset(
            {
                "schemaVersion": "lunarwindow.ephemeris.v2",
                **self.model_dump(
                    include={"siteId", "site", "lat", "lon", "altitudeKm", "coordinateSource"}
                ),
                "series": [
                    row.model_dump(include=set(EphemerisSample.model_fields)) for row in self.series
                ],
                "provenance": source,
            }
        )
        period = TimeRange(source["startUtc"], source["endUtc"], source["stepMinutes"])
        coverage = self.provenance.archive
        archive = TimeRange(coverage.startUtc, coverage.endUtc, coverage.stepMinutes)
        if coverage.sampleCount != archive.sample_count:
            raise ValueError("Archive sampleCount must match its native sampling grid.")
        if not archive.start <= period.start < period.end <= archive.end:
            raise ValueError("The selected ephemeris period must be within archive coverage.")
        if (
            period.start - archive.start
        ) % archive.step or period.step_minutes % archive.step_minutes:
            raise ValueError("The selected ephemeris grid must align with the archive grid.")
        if self.calculation.stepMinutes != period.step_minutes:
            raise ValueError("Calculation stepMinutes must match the selected ephemeris grid.")
        if not period.start <= parse_utc(self.metrics.asOfUtc) < period.end:
            raise ValueError("Metrics asOfUtc must be within the selected period.")
        if self.metrics.evaluatedHrs != (period.end - period.start).total_seconds() / 3600:
            raise ValueError("Metrics evaluatedHrs must match the selected period.")
        return self
