# syntax=docker/dockerfile:1

FROM python:3.14-slim-bookworm AS build
WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM build AS analysis-build
RUN python -m pip wheel --no-cache-dir --wheel-dir /analysis-wheels '.[analysis]'

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
COPY --chown=lunarwindow:lunarwindow data/sites.example.json /app/data/sites.example.json
USER lunarwindow
ENTRYPOINT ["lunarwindow-ephemeris"]
CMD ["--help"]

FROM runtime AS test
COPY --chown=lunarwindow:lunarwindow backend/tests /app/tests
COPY --chown=lunarwindow:lunarwindow data/reference /app/data/reference
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

FROM runtime AS ephemeris
