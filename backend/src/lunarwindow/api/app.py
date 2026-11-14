"""P3 API: synthetic source data with calculated visibility, metrics, and windows."""

import os
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

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
    SiteCatalog,
)


def get_provider() -> DemoProvider:
    return DemoProvider()


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
            "Synthetic ephemeris/horizon data with calculated visibility metrics and windows. "
            "Choose any-disc (default), body-center, or full-disc visibility. "
            "Durations use sample-and-hold; setting times include observation brackets. "
            "Times are whole-minute UTC; ranges include start and exclude end. "
            "Real Horizons/LOLA integration remains pending."
        ),
        responses={422: {"model": ErrorResponse}},
    )
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
