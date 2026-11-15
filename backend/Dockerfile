# syntax=docker/dockerfile:1

FROM python:3.14-slim-bookworm AS build
WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM build AS analysis-build
RUN python -m pip wheel --no-cache-dir --wheel-dir /analysis-wheels '.[analysis]'

FROM build AS terrain-build
RUN python -m pip wheel --no-cache-dir --wheel-dir /terrain-wheels '.[analysis,gis]'

FROM build AS test-build
RUN python -m pip wheel --no-cache-dir --wheel-dir /test-wheels 'httpx>=0.28,<1'

FROM python:3.14-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /app
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index /wheels/*.whl \
    && rm -rf /wheels \
    && groupadd --gid 1000 lunarwindow \
    && useradd --uid 1000 --gid lunarwindow --no-create-home lunarwindow \
    && mkdir -p /app/data/raw /app/data/processed \
    && chown -R lunarwindow:lunarwindow /app
COPY --chown=lunarwindow:lunarwindow data/sites.example.json data/sites.curated.json /app/data/
USER lunarwindow
ENTRYPOINT ["lunarwindow-ephemeris"]
CMD ["--help"]

FROM runtime AS test
USER root
COPY --from=test-build /test-wheels /test-wheels
RUN python -m pip install --no-cache-dir --no-index /test-wheels/*.whl && rm -rf /test-wheels
USER lunarwindow
COPY --chown=lunarwindow:lunarwindow backend/tests /app/tests
COPY --chown=lunarwindow:lunarwindow data/reference /app/data/reference
COPY --chown=lunarwindow:lunarwindow data/releases /app/data/releases
ENV LUNARWINDOW_REFERENCE_DIR=/app/data/reference
ENTRYPOINT ["python", "-m", "unittest", "discover", "-s", "/app/tests", "-v"]
CMD []

FROM runtime AS analysis
USER root
COPY --from=analysis-build /analysis-wheels /analysis-wheels
RUN python -m pip install --no-cache-dir --no-index /analysis-wheels/*.whl && rm -rf /analysis-wheels
USER lunarwindow
ENTRYPOINT ["lunarwindow-report"]
CMD ["--help"]

FROM runtime AS terrain
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=terrain-build /terrain-wheels /terrain-wheels
RUN python -m pip install --no-cache-dir --no-index /terrain-wheels/*.whl \
    && rm -rf /terrain-wheels && python -c "import rasterio"
USER lunarwindow
ENTRYPOINT ["lunarwindow-terrain"]
CMD ["--help"]

FROM test AS custom-test
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=terrain-build /terrain-wheels /terrain-wheels
RUN python -m pip install --no-cache-dir --no-index /terrain-wheels/*.whl \
    && rm -rf /terrain-wheels && python -c "import rasterio"
USER lunarwindow

FROM runtime AS ephemeris

FROM runtime AS api-base
COPY --chown=lunarwindow:lunarwindow data/reference/validation-30d /app/data/reference/validation-30d
COPY --chown=lunarwindow:lunarwindow data/reference/terrain-masks /app/data/reference/terrain-masks
COPY --chown=root:root data/releases/lunarwindow-demo-v1 /app/data/releases/lunarwindow-demo-v1
USER root
RUN chmod -R a=rX /app/data/releases/lunarwindow-demo-v1
USER lunarwindow
ENV LUNARWINDOW_REFERENCE_DIR=/app/data/reference \
    LUNARWINDOW_PRECOMPUTED_DIR=/app/data/releases/lunarwindow-demo-v1/bundle \
    UVICORN_LIMIT_CONCURRENCY=16 \
    UVICORN_TIMEOUT_KEEP_ALIVE=5
RUN lunarwindow-terrain-handoff registered \
    --reference-dir /app/data/reference/validation-30d \
    --terrain-dir /app/data/reference/terrain-masks --allow-mean-earth-approximation
RUN lunarwindow-data-release verify /app/data/releases/lunarwindow-demo-v1 \
    --reference-dir /app/data/reference/validation-30d
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=15s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=14)"]
ENTRYPOINT ["python", "-m", "uvicorn", "lunarwindow.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
CMD []

# Optional GIS-capable service; the archived reference API remains the default image.
FROM api-base AS custom-api
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=terrain-build /terrain-wheels /terrain-wheels
RUN python -m pip install --no-cache-dir --no-index /terrain-wheels/*.whl \
    && rm -rf /terrain-wheels && python -c "import rasterio"
USER lunarwindow

# Last stage on purpose: hosts that cannot select a target (e.g. Render) build the API.
FROM api-base AS api
