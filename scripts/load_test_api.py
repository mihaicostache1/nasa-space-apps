"""Measure the packaged API in an isolated, instrumented Docker container.

The host uses only Python's standard library. The factory runs inside the API
image; its private control routes are never added to the production application.
"""

import argparse
import importlib.metadata
import json
import math
import os
import platform
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path


def memory_snapshot() -> dict:
    """Linux RSS and cgroup v2 counters; fail rather than report invented zeros."""
    fields = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    cgroup = Path("/sys/fs/cgroup")
    return {
        "rssBytes": int(fields["VmRSS"].split()[0]) * 1024,
        "cgroupCurrentBytes": int((cgroup / "memory.current").read_text()),
        "cgroupLifetimePeakBytes": int((cgroup / "memory.peak").read_text()),
        "memoryEvents": {
            key: int(value)
            for key, value in (
                line.split()
                for line in (cgroup / "memory.events").read_text().splitlines()
            )
        },
    }


def create_instrumented_app():
    """Uvicorn test factory. All wrappers call the unchanged real implementation."""
    from fastapi import Header, HTTPException
    from lunarwindow.api import reference_provider
    from lunarwindow.api.app import create_app
    from lunarwindow.api.reference_cache import ReferenceEvaluationCache
    from lunarwindow.precompute import loader

    app = create_app()
    token = os.environ["LUNARWINDOW_LOAD_TEST_TOKEN"]
    lock = threading.RLock()
    counts = Counter()
    baseline = memory_snapshot()
    peak = dict(baseline)
    samples = 0
    violations = 0

    def sample():
        nonlocal samples, violations
        current = memory_snapshot()
        info = app.state.reference_evaluation_cache.info()
        with lock:
            samples += 1
            for key in ("rssBytes", "cgroupCurrentBytes"):
                peak[key] = max(peak[key], current[key])
            if (
                info.entry_count > info.max_entries
                or info.stored_bytes > info.max_bytes
            ):
                violations += 1
        return current

    class MeasuredCache(ReferenceEvaluationCache):
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

    limits = app.state.reference_evaluation_cache.info()
    app.state.reference_evaluation_cache = MeasuredCache(
        max_entries=limits.max_entries, max_bytes=limits.max_bytes
    )
    calculate = reference_provider.calculate_visibility
    load = loader.load_precomputed_evaluation

    def measured_calculate(*args, **kwargs):
        with lock:
            counts["calculations"] += 1
        return calculate(*args, **kwargs)

    def measured_load(*args, **kwargs):
        result = load(*args, **kwargs)
        with lock:
            counts["savedHits" if result is not None else "savedMisses"] += 1
        return result

    reference_provider.calculate_visibility = measured_calculate
    loader.load_precomputed_evaluation = measured_load

    def authorize(value):
        if not secrets.compare_digest(value, token):
            raise HTTPException(status_code=403)

    @app.post("/__loadtest/reset", include_in_schema=False)
    def reset(body: dict, x_loadtest_token: str = Header(default="")):
        nonlocal baseline, peak, samples, violations
        authorize(x_loadtest_token)
        if body.get("clearCache", False):
            app.state.reference_evaluation_cache.clear()
        current = memory_snapshot()
        with lock:
            counts.clear()
            baseline = current
            peak = dict(current)
            samples = violations = 0
        return {"reset": True}

    @app.get("/__loadtest/state", include_in_schema=False)
    def state(x_loadtest_token: str = Header(default="")):
        authorize(x_loadtest_token)
        current = sample()
        with lock:
            return {
                "counters": dict(counts),
                "cache": asdict(app.state.reference_evaluation_cache.info()),
                "memory": {
                    "baseline": dict(baseline),
                    "sampledPeak": {
                        key: peak[key] for key in ("rssBytes", "cgroupCurrentBytes")
                    },
                    "after": current,
                    "samples": samples,
                    "cacheBoundViolations": violations,
                },
                "runtime": {
                    "python": platform.python_version(),
                    "machine": platform.machine(),
                    "packages": {
                        name: importlib.metadata.version(name)
                        for name in (
                            "uvicorn",
                            "fastapi",
                            "pydantic",
                            "numpy",
                            "jsonschema",
                        )
                    },
                },
            }

    stop = threading.Event()

    def monitor():
        while not stop.wait(0.02):
            sample()

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            monitor_thread = threading.Thread(target=monitor, daemon=True)
            monitor_thread.start()
            try:
                yield
            finally:
                stop.set()
                monitor_thread.join(timeout=2)

    app.router.lifespan_context = lifespan

    return app


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; rejected/failed requests are summarized separately."""
    if not values:
        return None
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3)


def summarize(results: list[dict], elapsed: float) -> dict:
    statuses = Counter(str(result["status"]) for result in results)
    timings = {}
    for status in statuses:
        values = [
            result["latencyMs"] for result in results if str(result["status"]) == status
        ]
        timings[status] = {
            "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
            "max": round(max(values), 3),
        }
    return {
        "requests": len(results),
        "elapsedSeconds": round(elapsed, 3),
        "successfulRequestsPerSecond": round(statuses["200"] / elapsed, 3),
        "statusCounts": dict(statuses),
        "latencyMsByStatus": timings,
        "responseBytes": sum(result["bytes"] for result in results),
        "errors": [result["error"] for result in results if result.get("error")],
    }


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def validate_phase(phase: dict, path: str, *, overload: bool = False):
    """Fail measurements that mislabeled an execution path or breached a bound."""
    stats = phase["http"]
    require(not stats["errors"], f"Transport or response errors: {stats['errors']}")
    allowed = {"200", "503"} if overload else {"200"}
    require(set(stats["statusCounts"]) <= allowed, "Unexpected HTTP status under load.")
    accepted = stats["statusCounts"].get("200", 0)
    require(accepted > 0 or overload, "No successful measured requests.")
    counts = phase["server"]["counters"]
    expected = {
        "saved": {"savedHits": accepted},
        "memory": {"savedMisses": accepted, "memoryHits": accepted},
        "fresh": {
            "savedMisses": accepted,
            "memoryMisses": accepted,
            "calculations": accepted,
            "cachePuts": accepted,
        },
    }[path]
    require(
        {key: value for key, value in counts.items() if value}
        == {key: value for key, value in expected.items() if value},
        (f"Execution path differs from {path}: {counts}; expected {expected}."),
    )
    cache = phase["server"]["cache"]
    require(cache["entry_count"] <= cache["max_entries"], "Cache entry cap exceeded.")
    require(cache["stored_bytes"] <= cache["max_bytes"], "Cache byte cap exceeded.")
    memory = phase["server"]["memory"]
    require(memory["cacheBoundViolations"] == 0, "Sampled cache capacity exceeded.")
    before, after = memory["baseline"]["memoryEvents"], memory["after"]["memoryEvents"]
    require(
        after.get("oom", 0) == before.get("oom", 0), "Container reached OOM conditions."
    )
    require(
        after.get("oom_kill", 0) == before.get("oom_kill", 0),
        "Container had an OOM kill.",
    )


def docker(*arguments, timeout=60):
    try:
        return subprocess.check_output(
            ["docker", *arguments], text=True, stderr=subprocess.STDOUT, timeout=timeout
        ).strip()
    except subprocess.CalledProcessError as error:
        # Report Docker's reason, without echoing the token-bearing command line.
        raise RuntimeError(
            f"Docker {arguments[0]} failed: {error.output.strip()}"
        ) from error


class Client:
    def __init__(self, origin, token, timeout):
        self.origin, self.token, self.timeout = origin, token, timeout
        # Never send localhost requests through an inherited HTTP proxy.
        self.local = threading.local()

    def request(self, route, payload=None):
        if not hasattr(self.local, "opener"):
            self.local.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            )
        request = urllib.request.Request(
            self.origin + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Loadtest-Token": self.token,
            },
        )
        start = time.perf_counter()
        try:
            try:
                response = self.local.opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                body = response.read()
                status = response.status
            return {
                "status": status,
                "latencyMs": (time.perf_counter() - start) * 1000,
                "bytes": len(body),
                "body": body,
            }
        except (OSError, urllib.error.URLError) as error:
            return {
                "status": "transport_error",
                "latencyMs": (time.perf_counter() - start) * 1000,
                "bytes": 0,
                "error": str(error),
            }

    def control(self, route, payload=None):
        result = self.request(route, payload)
        require(result["status"] == 200, f"Control request failed: {result}")
        return json.loads(result["body"])

    def evaluation(self, payload):
        result = self.request("/api/reference/evaluations", payload)
        body = result.pop("body", b"")
        try:
            if result["status"] == 200:
                data = json.loads(body)
                require(data["dataMode"] == "reference", "Non-reference response.")
                require(
                    data["horizonMode"] == payload["horizonMode"], "Wrong horizon mode."
                )
                require(len(data["series"]) == 720, "Incomplete sample series.")
                require(
                    data["metrics"]["asOfUtc"] == payload["asOfUtc"],
                    "Wrong request identity.",
                )
                if payload["horizonMode"] == "terrain":
                    require(data["maskId"] == payload["maskId"], "Wrong terrain mask.")
                    require(
                        data["provenance"]["terrain"]["compatibility"]["frameStatus"]
                        == "approximate",
                        "Missing frame limitation.",
                    )
            elif result["status"] == 503:
                require(
                    body.strip() == b"Service Unavailable",
                    "503 was not Uvicorn overload.",
                )
            else:
                result["error"] = body.decode(errors="replace")[:500]
        except (ValueError, KeyError, TypeError, RuntimeError) as error:
            result["error"] = str(error)
        return result


def run_phase(client, mode, path, payloads, concurrency):
    client.control("/__loadtest/reset", {"clearCache": False})
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(client.evaluation, payloads))
    phase = {
        "horizonMode": mode,
        "path": path,
        "concurrency": concurrency,
        "http": summarize(results, time.perf_counter() - start),
        "server": client.control("/__loadtest/state"),
    }
    return phase


def run(args, report):
    name = "lunarwindow-load-test-" + uuid.uuid4().hex[:12]
    token = secrets.token_hex(32)
    script_directory = str(Path(__file__).resolve().parent)
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--cpus",
            str(args.cpus),
            "--memory",
            args.memory,
            "--memory-swap",
            args.memory,
            "--publish",
            "127.0.0.1::8000",
            *([] if args.with_healthcheck else ["--no-healthcheck"]),
            "--mount",
            f"type=bind,source={script_directory},target=/opt/loadtest,readonly",
            "--env",
            "PYTHONPATH=/opt/loadtest",
            "--env",
            f"LUNARWINDOW_LOAD_TEST_TOKEN={token}",
            "--env",
            "LUNARWINDOW_CACHE_MAX_ENTRIES=32",
            "--env",
            "LUNARWINDOW_CACHE_MAX_BYTES=16777216",
            "--entrypoint",
            "python",
            args.image,
            "-m",
            "uvicorn",
            "load_test_api:create_instrumented_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--no-access-log",
        )
        container = json.loads(docker("inspect", name))[0]
        port = int(container["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"])
        client = Client(f"http://127.0.0.1:{port}", token, args.timeout)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = client.request("/api/ready")
            if ready["status"] == 200:
                break
            time.sleep(0.2)
        require(ready["status"] == 200, "API did not become data-ready.")
        report["readiness"] = json.loads(ready["body"])
        environment = dict(value.split("=", 1) for value in container["Config"]["Env"])
        limit = int(environment["UVICORN_LIMIT_CONCURRENCY"])
        require(
            limit >= 4,
            "Image concurrency limit must be at least four for this workload.",
        )
        require(
            max(args.concurrency) < limit - 1,
            "Normal load must stay below the server limit.",
        )
        report["deployment"] = {
            "image": args.image,
            "imageId": container["Image"],
            "memoryLimitBytes": container["HostConfig"]["Memory"],
            "nanoCpus": container["HostConfig"]["NanoCpus"],
            "concurrencyLimit": limit,
            "keepAliveSeconds": int(environment["UVICORN_TIMEOUT_KEEP_ALIVE"]),
            "healthcheckDuringMeasurement": args.with_healthcheck,
            "imageHealthcheck": container["Config"].get("Healthcheck"),
            "clientPlatform": platform.platform(),
            "samplerIntervalMs": 20,
            "releaseChecksums": docker(
                "exec", name, "cat", "/app/data/releases/lunarwindow-demo-v1/SHA256SUMS"
            ),
        }
        start = datetime(2026, 11, 14, tzinfo=UTC)

        def payload(mode, minute):
            value = {
                "siteId": "lola-site01-reference",
                "horizonMode": mode,
                "startUtc": "2026-11-14T00:00:00Z",
                "endUtc": "2026-12-14T00:00:00Z",
                "stepMinutes": 60,
                "visibilityRule": "any-disc",
                "asOfUtc": (start + timedelta(minutes=minute))
                .isoformat()
                .replace("+00:00", "Z"),
            }
            if mode == "terrain":
                value.update(
                    maskId="lola-site01-reference-mast-0m",
                    allowMeanEarthApproximation=True,
                )
            return value

        for mode in args.horizon_modes:
            for path in ("saved", "memory", "fresh"):
                client.control("/__loadtest/reset", {"clearCache": True})
                if path == "memory":
                    warm = client.evaluation(payload(mode, 1))
                    require(
                        warm["status"] == 200 and not warm.get("error"),
                        "Cache warmup failed.",
                    )
                minute = 2
                for concurrency in args.concurrency:
                    if path == "fresh":
                        jobs = [
                            payload(mode, minute + offset)
                            for offset in range(args.requests)
                        ]
                        minute += args.requests
                    else:
                        jobs = [payload(mode, int(path == "memory"))] * args.requests
                    phase = run_phase(client, mode, path, jobs, concurrency)
                    report["phases"].append(phase)
                    if args.with_healthcheck:
                        phase["dockerHealth"] = json.loads(docker("inspect", name))[0][
                            "State"
                        ]["Health"]
                    validate_phase(phase, path)
                    if args.with_healthcheck:
                        require(
                            phase["dockerHealth"]["Status"] != "unhealthy",
                            "Periodic readiness probes became unhealthy during normal load.",
                        )
                    print(
                        f"{mode}/{path} c={concurrency}: {phase['http']['latencyMsByStatus']}",
                        file=sys.stderr,
                        flush=True,
                    )
            report["phases"].append(
                run_phase(
                    client,
                    mode,
                    "saved",
                    [payload(mode, 0)] * (limit * 2),
                    limit * 2,
                )
            )
            validate_phase(report["phases"][-1], "saved", overload=True)

        # Partial headers hold real TCP connections open without altering the engine.
        # This deterministically reaches Uvicorn's connection cap even on fast hosts.
        held = []
        try:
            for _ in range(limit):
                connection = socket.create_connection(("127.0.0.1", port), timeout=5)
                held.append(connection)
                connection.sendall(b"GET /api/health HTTP/1.1\r\nHost: localhost\r\n")
            time.sleep(0.2)
            rejected = client.evaluation(payload(args.horizon_modes[0], 0))
            require(
                rejected["status"] == 503 and not rejected.get("error"),
                "Server failed to reject connections at the configured cap.",
            )
        finally:
            for connection in held:
                connection.close()
        time.sleep(0.2)
        recovery = client.control("/api/ready")
        require(recovery["status"] == "ready", "API did not recover after overload.")
        report["overloadRecovery"] = {
            "heldConnections": limit,
            "rejectedStatus": 503,
            "readinessAfter": recovery["status"],
        }
        if args.with_healthcheck:
            previous_health = json.loads(docker("inspect", name))[0]["State"]["Health"]
            previous_start = (previous_health.get("Log") or [{}])[-1].get("Start")
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                health = json.loads(docker("inspect", name))[0]["State"]["Health"]
                last_probe = (health.get("Log") or [{}])[-1]
                recovered = (
                    health["Status"] == "healthy"
                    and last_probe.get("ExitCode") == 0
                    and last_probe.get("Start") != previous_start
                )
                if recovered:
                    break
                time.sleep(0.5)
            report["overloadRecovery"]["dockerHealthAfter"] = health
            require(
                recovered,
                "Docker did not complete a fresh successful health probe after load.",
            )
        state = json.loads(docker("inspect", name))[0]["State"]
        require(
            state["Running"] and not state["OOMKilled"], "API exited or was OOM-killed."
        )
        report["status"] = "passed"
    finally:
        try:
            report["containerLogs"] = docker("logs", "--tail", "60", name)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        finally:
            cleanup = subprocess.run(
                ["docker", "rm", "--force", name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if cleanup.returncode:
                report["cleanupError"] = cleanup.stderr.strip()
                report["status"] = "failed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="lunarwindow-api:local")
    parser.add_argument(
        "--requests", type=int, default=24, help="Requests per measured phase."
    )
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4, 8])
    parser.add_argument(
        "--horizon-modes",
        nargs="+",
        choices=["geometric", "terrain"],
        default=["geometric", "terrain"],
    )
    parser.add_argument("--memory", default="1g")
    parser.add_argument("--cpus", type=float, default=2.0)
    parser.add_argument(
        "--with-healthcheck",
        action="store_true",
        help="Include periodic image readiness probes and check Docker health.",
    )
    parser.add_argument(
        "--timeout", type=float, default=60, help="Per-request timeout in seconds."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        args.requests < 1
        or min(args.concurrency) < 1
        or args.cpus <= 0
        or args.timeout <= 0
        or args.requests * len(args.concurrency) > 43198
    ):
        parser.error(
            "Use positive limits and at most 43198 fresh request identities per mode."
        )
    report = {
        "schemaVersion": "lunarwindow.api-load-test.v1",
        "startedAtUtc": datetime.now(UTC).isoformat(),
        "status": "failed",
        "settings": {
            key: value for key, value in vars(args).items() if key != "output"
        },
        "phases": [],
    }
    try:
        run(args, report)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print(f"Load test failed: {error}", file=sys.stderr)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
