"""Terrain-aware reference API contracts and complete source/compatibility provenance."""

import math
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from lunarwindow.terrain.compatibility import TerrainCompatibility, check_terrain_compatibility
from lunarwindow.terrain.models import NonBlank, Sha256, Slug, TerrainMask

from .models import ApiModel
from .reference_models import (
    ReferenceEvaluation,
    ReferenceEvaluationData,
    ReferenceEvaluationProvenance,
    ReferenceEvaluationRequest,
    ReferenceSiteEvaluationRequest,
)


class TerrainReferenceEvaluationRequest(ReferenceSiteEvaluationRequest):
    horizonMode: Literal["terrain"]
    maskId: Slug = Field(description="Identifier of a server-reviewed mask; never a file path")
    allowMeanEarthApproximation: bool = Field(
        default=False,
        description="Explicitly allow the documented Mean Earth reference-demo approximation",
    )


class TerrainCompatibilityProvenance(ApiModel):
    maskId: Slug
    siteId: Slug
    framePolicy: Literal["mean-earth-reference-v1"]
    frameStatus: Literal["approximate"]
    maskFrameName: NonBlank
    maskFrameRealization: NonBlank
    ephemerisFrame: NonBlank
    ephemerisDynamicalSource: Literal["DE440", "DE441"]
    referenceRadiusKm: float = Field(gt=0)
    transformationApplied: Literal[False]
    limitation: NonBlank
    references: list[str] = Field(min_length=2, max_length=2)

    @field_validator("transformationApplied", mode="before")
    @classmethod
    def require_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("transformationApplied must be the boolean false.")
        return value

    @classmethod
    def from_assessment(cls, assessment: TerrainCompatibility) -> Self:
        return cls(
            maskId=assessment.mask_id,
            siteId=assessment.site_id,
            framePolicy=assessment.frame_policy,
            frameStatus=assessment.frame_status,
            maskFrameName=assessment.mask_frame_name,
            maskFrameRealization=assessment.mask_frame_realization,
            ephemerisFrame=assessment.ephemeris_frame,
            ephemerisDynamicalSource=assessment.ephemeris_dynamical_source,
            referenceRadiusKm=assessment.reference_radius_km,
            transformationApplied=assessment.transformation_applied,
            limitation=assessment.limitation,
            references=list(assessment.references),
        )


class TerrainMaskProvenance(ApiModel):
    artifactSha256: Sha256 = Field(description="Checksum of the exact reviewed mask file bytes")
    mask: TerrainMask
    compatibility: TerrainCompatibilityProvenance


class TerrainReferenceEvaluationProvenance(ReferenceEvaluationProvenance):
    terrain: TerrainMaskProvenance
    warning: NonBlank = (
        "Terrain visibility uses the reviewed DEM horizon for its recorded observer and an "
        "explicitly accepted frame approximation. Near-field exclusions, DEM resolution, "
        "the local horizontal-disc approximation, and sampling affect results. Eclipses, "
        "power generation, and radio-link performance are not modeled."
    )


class TerrainReferenceEvaluation(ReferenceEvaluationData):
    schemaVersion: Literal["lunarwindow.reference-evaluation.v2"] = (
        "lunarwindow.reference-evaluation.v2"
    )
    horizonMode: Literal["terrain"]
    maskId: Slug
    allowMeanEarthApproximation: Literal[True] = Field(
        description="The supported terrain frame pairing requires explicit reference-demo acceptance"
    )
    provenance: TerrainReferenceEvaluationProvenance

    @field_validator("allowMeanEarthApproximation", mode="before")
    @classmethod
    def require_explicit_acceptance(cls, value: object) -> object:
        if value is not True:
            raise ValueError(
                "A terrain reference response requires explicit boolean true acceptance."
            )
        return value

    @model_validator(mode="after")
    def validate_terrain_model(self) -> Self:
        terrain = self.provenance.terrain
        if self.maskId != terrain.mask.maskId:
            raise ValueError("Evaluation maskId must match the provenance mask.")
        if self.horizon != terrain.mask.horizon:
            raise ValueError("Evaluation horizon must exactly match the provenance mask.")
        assessment = check_terrain_compatibility(
            terrain.mask,
            self.to_ephemeris_dataset(),
            allow_mean_earth_approximation=self.allowMeanEarthApproximation,
        )
        expected = TerrainCompatibilityProvenance.from_assessment(assessment)
        if terrain.compatibility != expected:
            raise ValueError("Compatibility provenance must match the mask/ephemeris assessment.")

        # Cross-field consistency only: visibility states, metrics and windows are
        # calculated by the engine, never regenerated during contract validation.
        for row in self.series:
            for azimuth, elevation in (
                (row.sunAz, row.sunHorizonEl),
                (row.earthAz, row.earthHorizonEl),
            ):
                lower = math.floor(azimuth)
                fraction = azimuth - lower
                expected_elevation = (
                    self.horizon[lower].el * (1 - fraction)
                    + self.horizon[(lower + 1) % 360].el * fraction
                )
                if not math.isclose(elevation, expected_elevation, rel_tol=0, abs_tol=1e-9):
                    raise ValueError("Sample horizon elevation must match the terrain profile.")
        return self


ReferenceEvaluationRequestContract = Annotated[
    ReferenceEvaluationRequest | TerrainReferenceEvaluationRequest,
    Field(discriminator="horizonMode"),
]
ReferenceEvaluationContract = Annotated[
    ReferenceEvaluation | TerrainReferenceEvaluation,
    Field(discriminator="horizonMode"),
]
