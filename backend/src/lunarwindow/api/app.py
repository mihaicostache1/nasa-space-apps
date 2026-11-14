"""Synthetic demos and geometric/terrain evaluations of verified reference ephemerides."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from lunarwindow.ephemeris.contract import dataset_schema
from lunarwindow.reference import (
    ReferenceSelectionError,
    load_reference_dataset,
    select_reference_dataset,
)
from lunarwindow.terrain.compatibility import TerrainCompatibilityError
from lunarwindow.terrain.registry import UnknownTerrainMaskError
from lunarwindow.visibility.models import VisibilityRule

from .demo import DemoProvider
from .models import (
    ApiError,
    ErrorDetail,
    ErrorResponse,
    Evaluation,
    EvaluationOptions,
    EvaluationRequest,
    Health,
    Location,
    ReferenceSiteCatalog,
    SiteCatalog,
)
from .reference_cache import ReferenceEvaluationCache
from .reference_catalog import build_reference_catalog
from .reference_provider import evaluate_reference
from .terrain_models import ReferenceEvaluationContract, ReferenceEvaluationRequestContract


def get_provider() -> DemoProvider:
    return DemoProvider()


def get_reference_directory() -> Path:
    return Path(os.environ.get("LUNARWINDOW_REFERENCE_DIR", "data/reference")) / "validation-30d"


def get_terrain_directory() -> Path:
    return Path(os.environ.get("LUNARWINDOW_REFERENCE_DIR", "data/reference")) / "terrain-masks"


def get_reference_cache(request: Request) -> ReferenceEvaluationCache:
    return request.app.state.reference_evaluation_cache


def query_period(
    startUtc: str = "2026-11-14T00:00:00Z",
    endUtc: str = "2026-12-14T00:00:00Z",
    stepMinutes: Annotated[int, Query(ge=1, le=1440)] = 60,
    visibilityRule: VisibilityRule = "any-disc",
    asOfUtc: str | None = None,
) -> EvaluationOptions:
    try:
        return EvaluationOptions(
            startUtc=startUtc,
            endUtc=endUtc,
            stepMinutes=stepMinutes,
            visibilityRule=visibilityRule,
            asOfUtc=asOfUtc,
        )
    except ValidationError as exc:
        errors = [dict(error, loc=("query", *error["loc"])) for error in exc.errors()]
        raise RequestValidationError(errors) from exc


def create_app() -> FastAPI:
    app = FastAPI(
        title="LunarWindow backend",
        version="0.2.0",
        description=(
            "Synthetic demos and geometric or reviewed-terrain evaluations of NASA ephemerides. "
            "Choose any-disc (default), body-center, or full-disc visibility. "
            "Durations use sample-and-hold; setting times include observation brackets. "
            "Times are whole-minute UTC; ranges include start and exclude end. "
            "Reference evaluations require an explicit geometric or terrain horizon mode. "
            "Terrain requests select a reviewed mask and explicitly accept its frame approximation."
        ),
        responses={422: {"model": ErrorResponse}},
    )
    app.state.reference_evaluation_cache = ReferenceEvaluationCache()
    origins = os.environ.get(
        "LUNARWINDOW_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in origins.split(",") if origin.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        response = ErrorResponse(
            error=ApiError(
                code="validation_error",
                message="Invalid request. Check the listed fields.",
                details=[
                    ErrorDetail(
                        location=list(error["loc"]),
                        message=error["msg"],
                        type=error["type"],
                    )
                    for error in exc.errors()
                ],
            )
        )
        return JSONResponse(status_code=422, content=response.model_dump())

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        response = ErrorResponse(
            error=ApiError(
                code="not_found" if exc.status_code == 404 else "http_error",
                message=str(exc.detail),
            )
        )
        return JSONResponse(
            status_code=exc.status_code, content=response.model_dump(), headers=exc.headers
        )

    @app.get("/api/health", response_model=Health, tags=["health"])
    def health() -> Health:
        return Health()

    @app.get("/api/sites", response_model=SiteCatalog, tags=["sites"])
    def sites(provider: Annotated[DemoProvider, Depends(get_provider)]) -> SiteCatalog:
        return SiteCatalog(sites=provider.list_sites())

    @app.get(
        "/api/reference/sites",
        response_model=ReferenceSiteCatalog,
        responses={503: {"model": ErrorResponse}},
        tags=["reference"],
        summary="List verified reference points, archive coverage, and terrain availability",
        description=(
            "Sourced reference points with UTC dates, sampling intervals, supported horizon "
            "modes, and verified mask IDs, checksums, observer heights, DEM sources, and "
            "frame-approximation requirements. Invalid registered artifacts return HTTP 503."
        ),
    )
    def reference_sites(
        directory: Annotated[Path, Depends(get_reference_directory)],
        terrain_directory: Annotated[Path, Depends(get_terrain_directory)],
    ) -> ReferenceSiteCatalog:
        try:
            return build_reference_catalog(directory, terrain_directory)
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="Reference data is unavailable or failed validation."
            ) from exc

    @app.post(
        "/api/reference/evaluations",
        response_model=ReferenceEvaluationContract,
        responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
        tags=["reference"],
        summary="Calculate geometric or terrain visibility for a verified reference site",
        description=(
            "Uses verified archived samples and either a flat 0-degree horizon or a "
            "checksummed, server-reviewed terrain mask. Terrain mode requires maskId and "
            "explicit acceptance of the documented Mean Earth reference approximation. "
            "Returns visibility, metrics, windows, and setting brackets with original "
            "NASA evidence, archive coverage, and terrain/compatibility provenance when selected."
            " Successful results are cached after source, selection, and compatibility checks."
        ),
    )
    def reference_evaluation(
        scenario: ReferenceEvaluationRequestContract,
        directory: Annotated[Path, Depends(get_reference_directory)],
        terrain_directory: Annotated[Path, Depends(get_terrain_directory)],
        cache: Annotated[ReferenceEvaluationCache, Depends(get_reference_cache)],
    ) -> ReferenceEvaluationContract:
        try:
            return evaluate_reference(scenario, directory, terrain_directory, cache=cache)
        except (ReferenceSelectionError, TerrainCompatibilityError) as exc:
            raise RequestValidationError(
                [{"loc": ("body",), "msg": str(exc), "type": "value_error"}]
            ) from exc
        except UnknownTerrainMaskError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail=f"Unknown reference site: {scenario.siteId}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="Reference data is unavailable or failed validation."
            ) from exc

    @app.get(
        "/api/reference/sites/{site_id}/ephemeris",
        response_model=None,
        responses={
            200: {
                "description": "Verified full or selected ephemeris with original source evidence",
                "content": {"application/json": {"schema": dataset_schema()}},
            },
            404: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
        tags=["reference"],
        summary="Read one verified site's archived Sun/Earth ephemeris",
        description=(
            "Optional UTC bounds and a sampling step select existing archive samples. "
            "Start must align with the archive grid; step must be a whole-number multiple "
            "of the archive interval. Omitted values use archive defaults. "
            "Range metadata describes the selection; original request evidence is retained."
        ),
    )
    def reference_ephemeris(
        site_id: str,
        directory: Annotated[Path, Depends(get_reference_directory)],
        startUtc: Annotated[
            str | None, Query(description="Inclusive UTC start; on archive grid")
        ] = None,
        endUtc: Annotated[
            str | None, Query(description="Exclusive UTC end; within archive")
        ] = None,
        stepMinutes: Annotated[
            int | None,
            Query(ge=1, le=1440, description="Whole-number multiple of archive interval"),
        ] = None,
    ) -> dict:
        try:
            dataset = load_reference_dataset(directory, site_id)
            if startUtc is None and endUtc is None and stepMinutes is None:
                return dataset
            return select_reference_dataset(
                dataset, start_utc=startUtc, end_utc=endUtc, step_minutes=stepMinutes
            )
        except ReferenceSelectionError as exc:
            raise RequestValidationError(
                [{"loc": ("query",), "msg": str(exc), "type": "value_error"}]
            ) from exc
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail=f"Unknown reference site: {site_id}"
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="Reference data is unavailable or failed validation."
            ) from exc

    @app.get(
        "/api/sites/{site_id}",
        response_model=Evaluation,
        responses={404: {"model": ErrorResponse}},
        tags=["sites"],
        summary="Get a demo site's synthetic horizon and series",
    )
    def site_data(
        site_id: str,
        period: Annotated[EvaluationOptions, Depends(query_period)],
        provider: Annotated[DemoProvider, Depends(get_provider)],
    ) -> Evaluation:
        site = next((site for site in provider.list_sites() if site.id == site_id), None)
        if site is None:
            raise HTTPException(status_code=404, detail=f"Unknown demo site: {site_id}")
        scenario = EvaluationRequest(
            name=site.name,
            location=Location(
                latitudeDeg=site.lat, longitudeDeg=site.lon, altitudeKm=site.altitudeKm
            ),
            **period.model_dump(),
        )
        return provider.evaluate(scenario, site.id)

    @app.post("/api/evaluations", response_model=Evaluation, tags=["evaluations"])
    def evaluate(
        scenario: EvaluationRequest,
        provider: Annotated[DemoProvider, Depends(get_provider)],
    ) -> Evaluation:
        return provider.evaluate(scenario)

    return app


app = create_app()
