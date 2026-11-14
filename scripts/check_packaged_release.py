"""Exercise the shipped release through a real isolated API server inside its Docker image."""

import json
import os
import socket
import threading
import time
import urllib.request
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import uvicorn
from lunarwindow.api.app import (
    create_app,
    get_precomputed_directory,
    get_reference_directory,
)
from lunarwindow.ephemeris.models import iso_utc
from lunarwindow.precompute.release import verify_release
from lunarwindow.precompute.validation import request_for_key
from lunarwindow.visibility import calculate_visibility


def main() -> None:
    release = Path("/app/data/releases/lunarwindow-demo-v1")
    manifest = verify_release(release, reference_directory=get_reference_directory())
    configured = get_precomputed_directory()
    assert (
        configured is not None
        and configured.resolve() == (release / "bundle").resolve()
    )
    assert os.geteuid() != 0, "Packaged API must run as a non-root user."
    assert not os.access(release / "SHA256SUMS", os.W_OK), (
        "Release must be read-only to API user."
    )
    assert all(not os.access(path, os.W_OK) for path in release.rglob("*.json"))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(),
            log_config=None,
            log_level="error",
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )

    def post(payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/reference/evaluations",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200
            return json.load(response)

    try:
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "Packaged API failed to start."
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/ready", timeout=30
        ) as response:
            readiness = json.load(response)
            assert readiness["status"] == "ready"
            assert readiness["referenceSiteCount"] == 3
            assert readiness["terrainMaskCount"] == 1
            assert readiness["precomputedJobCount"] == len(manifest.jobs)
        with patch(
            "lunarwindow.api.reference_provider.calculate_visibility",
            side_effect=AssertionError(
                "A packaged demo request must use its saved result."
            ),
        ) as engine:
            for job in manifest.jobs:
                payload = request_for_key(job.evaluation).model_dump()
                expected = json.loads(
                    (release / "bundle" / job.output.filename).read_bytes()
                )
                assert post(payload) == expected
            assert engine.call_count == 0
        first = manifest.jobs[0].evaluation
        fallback = request_for_key(first).model_dump()
        fallback["endUtc"] = iso_utc(first.to_time_range().start + timedelta(hours=1))
        with patch(
            "lunarwindow.api.reference_provider.calculate_visibility",
            wraps=calculate_visibility,
        ) as engine:
            actual = post(fallback)
            assert actual["metrics"]["evaluatedHrs"] == 1
            assert post(fallback) == actual
            assert engine.call_count == 1
        print(
            json.dumps(
                {
                    "release": manifest.runId,
                    "savedHits": len(manifest.jobs),
                    "fallbackAndMemoryCache": "ok",
                }
            )
        )
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), "Packaged smoke-test server did not stop."


if __name__ == "__main__":
    main()
