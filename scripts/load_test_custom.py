"""Isolated custom API load test with local Horizons fixtures and real GIS computation.

Only this test factory installs fixtures and control routes. Production is unchanged.
Host dependencies: Python 3.11+ standard library and Docker.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, build_opener

from load_test_api import Client, docker, memory_snapshot, require, summarize

REQUEST = {
    "location": {
        "latitudeDeg": -89.0,
        "longitudeDeg": 0.0,
        "observerHeightM": 2.0,
        "surfaceElevationM": 100.0,
    },
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
    "stepMinutes": 60,
}


def request_for(height, mode="geometric"):
    body = json.loads(json.dumps(REQUEST))
    body["location"]["observerHeightM"] = height
    body["horizonMode"] = mode
    if mode == "terrain":
        body["location"].pop("surfaceElevationM")
        body["allowMeanEarthApproximation"] = True
    return body


def make_fixture_dems(directory, profile):
    """Write labeled synthetic 20/120 m GeoTIFFs; never masquerade as reviewed data."""
    import numpy as np
    import rasterio
    from lunarwindow.terrain.download import sidecar_path
    from lunarwindow.terrain.geometry import latlon_to_stereographic
    from lunarwindow.terrain.products import FAR_FIELD, NEAR_FIELD, PRODUCTS
    from rasterio.transform import from_origin

    directory.mkdir()
    products = dict(PRODUCTS)
    x, y = (float(v) for v in latlon_to_stereographic(-89, 0))
    hashes = {}
    for pid, width in (
        (NEAR_FIELD, 3200 if profile == "full" else 256),
        (FAR_FIELD, 4000 if profile == "full" else 64),
    ):
        product = products[pid]
        path = directory / product.filename
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=width,
            height=width,
            count=1,
            dtype="float32",
            crs="+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m",
            transform=from_origin(
                x - width * product.resolution_m / 2,
                y + width * product.resolution_m / 2,
                product.resolution_m,
                product.resolution_m,
            ),
        ) as output:
            # Deliberately synthetic flat elevation, with actual bilinear GIS reads.
            output.write(np.full((width, width), 100, dtype="float32"), 1)
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        hashes[pid] = checksum
        products[pid] = replace(product, size_bytes=path.stat().st_size)
        sidecar_path(path).write_text(
            json.dumps(
                {
                    "productId": pid,
                    "role": product.role,
                    "sourceUrl": product.url,
                    "sizeBytes": path.stat().st_size,
                    "mtimeNs": path.stat().st_mtime_ns,
                    "sha256": checksum,
                    "retrievedAtUtc": "2026-11-14T00:00:00Z",
                    "resolutionM": product.resolution_m,
                }
            )
        )
    return products, hashes


def create_instrumented_app():
    """Test-only factory, mounted into a disposable GIS-enabled container."""
    from fastapi import Header, HTTPException
    from lunarwindow.api import custom_provider
    from lunarwindow.api.app import create_app
    from lunarwindow.api.custom_models import CustomEvaluationRequest, observer_site_id
    from lunarwindow.api.custom_runtime import CustomRuntime, CustomSettings
    from lunarwindow.api.snapshot_cache import SnapshotCache
    from lunarwindow.ephemeris import horizons
    from lunarwindow.ephemeris.models import Site
    from lunarwindow.terrain import custom as terrain

    temporary = tempfile.TemporaryDirectory(prefix="lunarwindow-custom-load-")
    root = Path(temporary.name)
    profile = os.environ["LUNARWINDOW_LOAD_PROFILE"]
    products, hashes = make_fixture_dems(root / "dems", profile)
    terrain.PRODUCTS = products
    parameters = terrain.default_parameters
    if profile == "smoke":
        terrain.default_parameters = lambda **changes: parameters(
            **(changes | {"maxRangeKm": 1.0, "nearFieldKm": 0.5, "raysPerDegree": 1})
        )
    app = create_app()
    runtime = CustomRuntime(
        CustomSettings(
            enabled=True,
            terrain_enabled=True,
            archive_directory=root / "ephemeris",
            terrain_cache_directory=root / "terrain",
            dem_directory=root / "dems",
            timeout_seconds=float(os.environ["LUNARWINDOW_LOAD_BUDGET"]),
            max_concurrency=int(os.environ["LUNARWINDOW_LOAD_SLOTS"]),
            max_archive_entries=4,
            max_archive_bytes=16 * 1024 * 1024,
            cache_max_entries=2,
            cache_max_bytes=1024 * 1024,
        )
    )
    app.state.custom_runtime = runtime
    token = os.environ["LUNARWINDOW_LOAD_TEST_TOKEN"]
    lock = threading.RLock()
    counts = Counter()
    durations = defaultdict(list)
    active = peak_active = 0
    gate = threading.Event()
    gate.set()
    upstream_delay = 0.02
    baseline = peak = memory_snapshot()
    samples = violations = 0
    monitor_errors = []
    original_admit = runtime.admit

    @contextmanager
    def admit():
        nonlocal active, peak_active
        with original_admit():
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                require(gate.wait(15), "Load-test admission gate timed out.")
                yield
            finally:
                with lock:
                    active -= 1

    runtime.admit = admit

    def disk_info(directory):
        files = list(directory.glob("*.json"))
        sizes = []
        for path in files:
            try:
                sizes.append(path.stat().st_size)
            except FileNotFoundError:
                pass  # Pruning may remove an older file during sampling.
        return {"entries": len(sizes), "bytes": sum(sizes)}

    def sample():
        nonlocal samples, violations
        current = memory_snapshot()
        info = runtime.cache.info()
        with lock:
            samples += 1
            peak["rssBytes"] = max(peak["rssBytes"], current["rssBytes"])
            peak["cgroupCurrentBytes"] = max(
                peak["cgroupCurrentBytes"], current["cgroupCurrentBytes"]
            )
            violations += int(
                info.entry_count > info.max_entries
                or info.stored_bytes > info.max_bytes
            )
        return current

    def measured(owner, name, label):
        original = getattr(owner, name)

        def call(*args, **kwargs):
            started = time.perf_counter()
            with lock:
                counts[label] += 1
            try:
                return original(*args, **kwargs)
            finally:
                with lock:
                    durations[label].append((time.perf_counter() - started) * 1000)
                sample()

        setattr(owner, name, call)

    measured(custom_provider, "acquire_custom_ephemeris", "acquisitions")
    measured(custom_provider, "calculate_visibility", "calculations")
    measured(terrain, "generate_custom_terrain", "terrainPreparations")
    measured(terrain, "compute_horizon", "raycasts")
    measured(terrain, "_source_record", "sourceHashes")

    class MeasuredCache(SnapshotCache):
        def get(self, key):
            result = super().get(key)
            with lock:
                counts["memoryHits" if result is not None else "memoryMisses"] += 1
            return result

        def put(self, key, snapshot):
            result = super().put(key, snapshot)
            with lock:
                counts["cachePuts" if result else "cacheSkippedPuts"] += 1
            sample()
            return result

    runtime.cache = MeasuredCache(max_entries=2, max_bytes=1024 * 1024)
    fixtures = {
        name: json.loads(
            json.loads((Path("/opt/fixtures") / f"{name}.json").read_text())[
                "rawResponse"
            ]
        )
        for name in ("sun", "earth")
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            name = "sun" if query["COMMAND"] == ["'10'"] else "earth"
            envelope = dict(fixtures[name])
            envelope["result"] = re.sub(
                r"Center geodetic\s*:[^\n]+",
                f"Center geodetic : {query['SITE_COORD'][0].strip(chr(39))} {{E-lon(deg),Lat(deg),Alt(km)}}",
                envelope["result"],
            )
            body = json.dumps(envelope).encode()
            time.sleep(upstream_delay)
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def fixture_open(request, timeout):
        with lock:
            counts["upstreamCalls"] += 1
        # Never open the NASA URL. Only the query is sent to our loopback fixture.
        return build_opener(ProxyHandler({})).open(
            f"http://127.0.0.1:{upstream.server_port}/?{urlsplit(request.full_url).query}",
            timeout=timeout,
        )

    horizons.urlopen = fixture_open

    def authorize(value):
        if not secrets.compare_digest(value, token):
            raise HTTPException(status_code=403)

    @app.post("/__loadtest/prewarm", include_in_schema=False)
    def prewarm(body: dict, x_loadtest_token: str = Header(default="")):
        authorize(x_loadtest_token)
        # Terrain and geometric observers deliberately have different coordinate
        # provenance, which is part of archive identity. Seed the exact terrain
        # identity without generating a horizon during this excluded setup step.
        request = CustomEvaluationRequest.model_validate(body)
        altitude = round((100 + request.location.observerHeightM) / 1000, 6)
        site = Site(
            observer_site_id(request.location, altitude),
            "Custom lunar observer",
            request.location.latitudeDeg,
            request.location.longitudeDeg,
            altitude,
            terrain.COORDINATE_SOURCE,
        )
        with runtime.admit():
            custom_provider.acquire_custom_ephemeris(
                site,
                request.to_time_range(),
                archive_directory=runtime.settings.archive_directory,
                timeout_seconds=runtime.settings.timeout_seconds,
                max_archive_entries=4,
                max_archive_bytes=16 * 1024 * 1024,
            )
        return {"warmed": True}

    @app.post("/__loadtest/reset", include_in_schema=False)
    def reset(body: dict, x_loadtest_token: str = Header(default="")):
        nonlocal baseline, peak, samples, violations, peak_active, upstream_delay
        authorize(x_loadtest_token)
        with lock:
            if active:
                raise HTTPException(status_code=409)
            counts.clear()
            durations.clear()
            peak_active = samples = violations = 0
            baseline = memory_snapshot()
            peak = dict(baseline)
            monitor_errors.clear()
            upstream_delay = body.get("upstreamDelay", 0.02)
            if body.get("clearCache"):
                runtime.cache.clear()
            if body.get("hold"):
                gate.clear()
            else:
                gate.set()
            runtime.settings = replace(
                runtime.settings,
                timeout_seconds=body.get(
                    "budget", float(os.environ["LUNARWINDOW_LOAD_BUDGET"])
                ),
            )
        return {"reset": True}

    @app.post("/__loadtest/release", include_in_schema=False)
    def release(x_loadtest_token: str = Header(default="")):
        authorize(x_loadtest_token)
        gate.set()
        return {"released": True}

    @app.get("/__loadtest/state", include_in_schema=False)
    def state(x_loadtest_token: str = Header(default="")):
        authorize(x_loadtest_token)
        after = sample()
        with lock:
            return {
                "runtime": {
                    "python": platform.python_version(),
                    "machine": platform.machine(),
                    "packages": {
                        name: importlib.metadata.version(name)
                        for name in (
                            "numpy",
                            "rasterio",
                            "fastapi",
                            "pydantic",
                            "uvicorn",
                        )
                    },
                },
                "counters": dict(counts),
                "stageLatencyMs": {
                    name: summarize(
                        [
                            {"status": 200, "latencyMs": value, "bytes": 0}
                            for value in values
                        ],
                        1,
                    )["latencyMsByStatus"]["200"]
                    for name, values in durations.items()
                },
                "cache": asdict(runtime.cache.info()),
                "archive": disk_info(root / "ephemeris"),
                "terrainCache": disk_info(root / "terrain"),
                "active": active,
                "peakActive": peak_active,
                "memory": {
                    "baseline": baseline,
                    "after": after,
                    "sampledPeak": {
                        key: peak[key] for key in ("rssBytes", "cgroupCurrentBytes")
                    },
                    "samples": samples,
                    "cacheBoundViolations": violations,
                    "monitorErrors": list(monitor_errors),
                },
                "fixture": {
                    "profile": profile,
                    "demSha256": hashes,
                    "parameters": terrain.default_parameters().model_dump(),
                    "syntheticObserverHeaders": True,
                    "liveNasaRequests": False,
                },
            }

    stop = threading.Event()

    def monitor():
        while not stop.wait(0.02):
            try:
                sample()
            except (OSError, ValueError, KeyError) as exc:
                with lock:
                    monitor_errors.append(str(exc))
                return

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        watcher = threading.Thread(target=monitor, daemon=True)
        upstream_thread.start()
        watcher.start()
        try:
            async with original_lifespan(application):
                yield
        finally:
            gate.set()
            stop.set()
            watcher.join(timeout=2)
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)
            runtime.close()
            temporary.cleanup()

    app.router.lifespan_context = lifespan
    return app


class CustomClient(Client):
    def evaluation(self, payload):
        result = self.request("/api/custom/evaluations", payload)
        if result.get("error"):
            return result
        raw = result.pop("body", b"")
        try:
            data = json.loads(raw)
            if result["status"] == 200:
                require(
                    data["schemaVersion"] == "lunarwindow.custom-evaluation.v1",
                    "Wrong response contract.",
                )
                require(
                    data["horizonMode"] == payload["horizonMode"]
                    and len(data["series"]) == 3,
                    "Wrong mode or sample count.",
                )
                observer = data["observer"]
                require(
                    observer["mastHeightM"] == payload["location"]["observerHeightM"]
                    and observer["lat"] == payload["location"]["latitudeDeg"]
                    and observer["lon"] == payload["location"]["longitudeDeg"],
                    "Wrong observer.",
                )
                provenance = data["provenance"]["ephemeris"]
                require(
                    data["dataMode"] == "custom"
                    and all(
                        provenance[key] == payload[key]
                        for key in ("startUtc", "endUtc", "stepMinutes")
                    ),
                    "Wrong data mode or selected period.",
                )
                if payload["horizonMode"] == "terrain":
                    terrain = data["provenance"]["terrain"]
                    require(
                        terrain["compatibility"]["frameStatus"] == "approximate",
                        "Lost frame limitation.",
                    )
                    require(
                        data["horizon"] == terrain["mask"]["horizon"],
                        "Wrong mask horizon.",
                    )
            else:
                result["code"] = data["error"]["code"]
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            result["error"] = f"{exc}: {raw[:300]!r}"
        return result


def validate_phase(phase, path, slots):
    stats, state = phase["http"], phase["server"]
    require(not stats["errors"], f"HTTP failures: {stats['errors']}")
    require(
        stats["statusCounts"] == {"200": stats["requests"]},
        "Normal custom requests must succeed.",
    )
    count = stats["requests"]
    require(count > 0, "No successful measured requests.")
    expected = {
        "horizons-acquisition": {
            "acquisitions": count,
            "upstreamCalls": 2 * count,
            "calculations": count,
            "memoryMisses": count,
            "cachePuts": count,
        },
        "archive-reuse": {"acquisitions": count, "memoryHits": count},
        "terrain-generation": {
            "acquisitions": count,
            "terrainPreparations": count,
            "sourceHashes": 2 * count,
            "raycasts": count,
            "calculations": count,
            "memoryMisses": count,
            "cachePuts": count,
        },
        "terrain-reuse": {
            "acquisitions": count,
            "terrainPreparations": count,
            "sourceHashes": 2 * count,
            "memoryHits": count,
        },
    }[path]
    require(
        state["counters"] == expected,
        f"Execution path mismatch: {state['counters']}; expected {expected}",
    )
    validate_bounds(state, slots)


def validate_bounds(state, slots):
    require(
        state["active"] == 0 and state["peakActive"] <= slots,
        "Custom concurrency bound exceeded or work still active.",
    )
    info = state["cache"]
    require(
        info["entry_count"] <= info["max_entries"]
        and info["stored_bytes"] <= info["max_bytes"],
        "Memory cache bound exceeded.",
    )
    for name in ("archive", "terrainCache"):
        require(
            state[name]["entries"] <= 4 and state[name]["bytes"] <= 16 * 1024 * 1024,
            "Disk retention bound exceeded.",
        )
    memory = state["memory"]
    require(
        not memory["monitorErrors"]
        and memory["samples"] > 0
        and memory["cacheBoundViolations"] == 0,
        "Memory monitoring failed or cache bound exceeded.",
    )
    for event in ("oom", "oom_kill"):
        require(
            memory["baseline"]["memoryEvents"].get(event, 0)
            == memory["after"]["memoryEvents"].get(event, 0),
            "Container reached OOM conditions.",
        )


def phase(client, name, payloads, concurrency, slots):
    client.control("/__loadtest/reset", {})
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(client.evaluation, payloads))
    return {
        "path": name,
        "concurrency": concurrency,
        "http": summarize(results, time.perf_counter() - start),
        "server": client.control("/__loadtest/state"),
    }


def run(args, report):
    name = "lunarwindow-custom-load-" + uuid.uuid4().hex[:12]
    token = secrets.token_hex(32)
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--memory",
            args.memory,
            "--memory-swap",
            args.memory,
            "--cpus",
            str(args.cpus),
            "--publish",
            "127.0.0.1::8000",
            "--no-healthcheck",
            "--mount",
            f"type=bind,source={Path(__file__).resolve().parent},target=/opt/loadtest,readonly",
            "--mount",
            f"type=bind,source={Path(__file__).resolve().parents[1] / 'backend/tests/fixtures'},target=/opt/fixtures,readonly",
            "--env",
            "PYTHONPATH=/opt/loadtest",
            "--env",
            f"LUNARWINDOW_LOAD_TEST_TOKEN={token}",
            "--env",
            f"LUNARWINDOW_LOAD_PROFILE={args.profile}",
            "--env",
            f"LUNARWINDOW_LOAD_BUDGET={args.budget}",
            "--env",
            f"LUNARWINDOW_LOAD_SLOTS={args.slots}",
            "--env",
            "UVICORN_LIMIT_CONCURRENCY=32",
            "--entrypoint",
            "python",
            args.image,
            "-m",
            "uvicorn",
            "load_test_custom:create_instrumented_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
        )
        container = json.loads(docker("inspect", name))[0]
        port = container["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
        client = CustomClient(f"http://127.0.0.1:{port}", token, args.budget + 15)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready = client.request("/api/health")
            if ready["status"] == 200:
                break
            time.sleep(0.2)
        require(ready["status"] == 200, "Custom API failed startup.")
        report["imageId"] = container["Image"]
        report["resources"] = {
            key: container["HostConfig"][key]
            for key in ("Memory", "MemorySwap", "NanoCpus")
        }
        identity = 0
        for concurrency in args.concurrency:
            for path in (
                "horizons-acquisition",
                "archive-reuse",
                "terrain-generation",
                "terrain-reuse",
            ):
                mode = "terrain" if path.startswith("terrain") else "geometric"
                if path.endswith("reuse"):
                    identity += 1
                    warm = request_for(2 + identity / 100, mode)
                    require(client.evaluation(warm)["status"] == 200, "Warmup failed.")
                    jobs = [warm] * args.requests
                else:
                    jobs = []
                    for _ in range(args.requests):
                        identity += 1
                        height = 2 + identity / 100
                        if mode == "terrain":
                            # Prewarm the exact DEM-derived observer's ephemeris, so
                            # this phase measures GIS work independently of acquisition.
                            client.control(
                                "/__loadtest/prewarm", request_for(height, "terrain")
                            )
                        jobs.append(request_for(height, mode))
                measured = phase(client, path, jobs, concurrency, args.slots)
                report["phases"].append(measured)
                validate_phase(measured, path, args.slots)
        # Occupy every real admission slot before probing immediate busy responses.
        client.control("/__loadtest/reset", {"hold": True})
        with ThreadPoolExecutor(max_workers=args.slots) as pool:
            held = [
                pool.submit(client.evaluation, request_for(900 + i))
                for i in range(args.slots)
            ]
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if client.control("/__loadtest/state")["active"] == args.slots:
                        break
                    time.sleep(0.01)
                require(
                    client.control("/__loadtest/state")["active"] == args.slots,
                    "Could not occupy custom slots.",
                )
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=4) as burst:
                    rejected = list(
                        burst.map(client.evaluation, [request_for(950)] * 8)
                    )
                require(
                    all(
                        item["status"] == 503
                        and item.get("code") == "custom_busy"
                        and not item.get("error")
                        for item in rejected
                    ),
                    "Busy requests did not reject immediately through custom admission.",
                )
                report["busy"] = summarize(rejected, time.perf_counter() - started)
                require(
                    not client.control("/__loadtest/state")["counters"],
                    "Rejected or held work performed acquisition/calculation.",
                )
            finally:
                client.control("/__loadtest/release", {})
            require(
                all(future.result()["status"] == 200 for future in held),
                "Held work did not recover.",
            )
        validate_bounds(client.control("/__loadtest/state"), args.slots)
        # A slow local HTTP server must exhaust the actual cooperative/socket budget.
        client.control("/__loadtest/reset", {"budget": 1, "upstreamDelay": 1.5})
        timeout = client.evaluation(request_for(999))
        report["deadline"] = timeout
        report["deadlineState"] = client.control("/__loadtest/state")
        validate_bounds(report["deadlineState"], args.slots)
        require(
            report["deadlineState"]["counters"]
            == {"acquisitions": 1, "upstreamCalls": 1},
            "Timed-out acquisition retried or started calculation.",
        )
        require(
            timeout["status"] == 504
            and timeout.get("code") == "custom_upstream_timeout"
            and not timeout.get("error"),
            "Deadline was not enforced.",
        )
        client.control("/__loadtest/reset", {})
        require(
            client.evaluation(request_for(998))["status"] == 200,
            "Failed to recover after timeout.",
        )
        report["finalState"] = client.control("/__loadtest/state")
        validate_bounds(report["finalState"], args.slots)
        state = json.loads(docker("inspect", name))[0]["State"]
        require(
            state["Running"] and not state["OOMKilled"],
            "Custom API exited or was OOM-killed.",
        )
        report["status"] = "passed"
    finally:
        try:
            report["containerLogs"] = docker("logs", "--tail", "40", name)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            report["logsError"] = str(error)
        finally:
            result = subprocess.run(
                ["docker", "rm", "--force", name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                report["cleanupError"] = result.stderr.strip()
                report["status"] = "failed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="lunarwindow-custom-test")
    parser.add_argument("--profile", choices=("smoke", "full"), default="full")
    parser.add_argument("--requests", type=int, default=4)
    parser.add_argument("--slots", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1])
    parser.add_argument("--budget", type=float, default=120)
    parser.add_argument("--memory", default="1g")
    parser.add_argument("--cpus", type=float, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        not 1 <= args.requests <= 4
        or not args.concurrency
        or min(args.concurrency) < 1
        or max(args.concurrency) > args.slots
        or not math.isfinite(args.budget)
        or not 1 <= args.budget <= 120
        or not math.isfinite(args.cpus)
        or args.cpus <= 0
    ):
        parser.error(
            "Use 1–4 requests, normal concurrency within admission slots, budget 1–120 seconds, and positive CPUs."
        )
    report = {
        "schemaVersion": "lunarwindow.custom-load-test.v1",
        "startedAtUtc": datetime.now(UTC).isoformat(),
        "harnessSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "upstreamFixtureSha256": {
            target: hashlib.sha256(
                (
                    Path(__file__).resolve().parents[1]
                    / "backend/tests/fixtures"
                    / f"{target}.json"
                ).read_bytes()
            ).hexdigest()
            for target in ("sun", "earth")
        },
        "status": "failed",
        "settings": {
            key: value for key, value in vars(args).items() if key != "output"
        },
        "limitations": [
            "Local synthetic observer headers and archived angles, not live NASA timing or scientific validation.",
            "Synthetic 20/120 m GeoTIFFs: byte sizes and geographic extent differ from original LOLA products.",
            "Smoke profile reduces ray range and count; full profile uses production ray parameters.",
            "20 ms sampled memory peaks are lower bounds; cgroup lifetime peak is also reported.",
            "Test-only wrappers add overhead; disk/page caches are warm and health probes disabled.",
        ],
        "phases": [],
    }
    try:
        run(args, report)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        print(f"Custom load test failed: {exc}", file=sys.stderr)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
