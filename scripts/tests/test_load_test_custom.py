"""Prevent custom load reports from hiding work, failures, or exceeded limits."""

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(DIRECTORY), *sys.path]):
    SPEC = importlib.util.spec_from_file_location(
        "load_test_custom", DIRECTORY / "load_test_custom.py"
    )
    load_test = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(load_test)


class CustomLoadReportTests(unittest.TestCase):
    def test_http_validation_keeps_transport_and_malformed_response_failures(self):
        client = load_test.CustomClient("http://127.0.0.1:1", "test", 1)
        with patch.object(
            client,
            "request",
            return_value={"status": "transport_error", "error": "timed out"},
        ):
            self.assertEqual(
                client.evaluation(load_test.request_for(2))["error"], "timed out"
            )
        for result in (
            {
                "status": "transport_error",
                "latencyMs": 10,
                "bytes": 0,
                "error": "timed out",
            },
            {"status": 200, "latencyMs": 10, "bytes": 2, "body": b"{}"},
            {
                "status": 503,
                "latencyMs": 1,
                "bytes": 19,
                "body": b"Service Unavailable",
            },
        ):
            with (
                self.subTest(status=result["status"]),
                patch.object(client, "request", return_value=dict(result)),
            ):
                self.assertIn("error", client.evaluation(load_test.request_for(2)))
        raw = json.dumps({"error": {"code": "custom_busy"}}).encode()
        with patch.object(
            client,
            "request",
            return_value={
                "status": 503,
                "latencyMs": 1,
                "bytes": len(raw),
                "body": raw,
            },
        ):
            result = client.evaluation(load_test.request_for(2))
        self.assertEqual(result["code"], "custom_busy")
        self.assertNotIn("error", result)

    def phase(self, counters):
        return {
            "http": {"requests": 2, "errors": [], "statusCounts": {"200": 2}},
            "server": {
                "counters": counters,
                "active": 0,
                "peakActive": 1,
                "cache": {
                    "entry_count": 2,
                    "max_entries": 2,
                    "stored_bytes": 512,
                    "max_bytes": 1024,
                },
                "archive": {"entries": 4, "bytes": 1024},
                "terrainCache": {"entries": 4, "bytes": 1024},
                "memory": {
                    "samples": 2,
                    "monitorErrors": [],
                    "cacheBoundViolations": 0,
                    "baseline": {"memoryEvents": {"oom": 0, "oom_kill": 0}},
                    "after": {"memoryEvents": {"oom": 0, "oom_kill": 0}},
                },
            },
        }

    def test_distinct_acquisition_generation_and_reuse_paths(self):
        cases = {
            "horizons-acquisition": {
                "acquisitions": 2,
                "upstreamCalls": 4,
                "calculations": 2,
                "memoryMisses": 2,
                "cachePuts": 2,
            },
            "archive-reuse": {"acquisitions": 2, "memoryHits": 2},
            "terrain-generation": {
                "acquisitions": 2,
                "terrainPreparations": 2,
                "sourceHashes": 4,
                "raycasts": 2,
                "calculations": 2,
                "memoryMisses": 2,
                "cachePuts": 2,
            },
            "terrain-reuse": {
                "acquisitions": 2,
                "terrainPreparations": 2,
                "sourceHashes": 4,
                "memoryHits": 2,
            },
        }
        for path, counters in cases.items():
            phase = self.phase(counters)
            load_test.validate_phase(phase, path, 1)
            # Reuse still verifies sources, but must not acquire new network data
            # or ray-cast. Nor may generation silently use saved terrain.
            wrong = copy.deepcopy(phase)
            wrong["server"]["counters"]["upstreamCalls"] = 99
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(RuntimeError, "Execution path"),
            ):
                load_test.validate_phase(wrong, path, 1)
        broken = self.phase(cases["terrain-reuse"])
        broken["server"]["counters"].pop("sourceHashes")
        with self.assertRaisesRegex(RuntimeError, "Execution path"):
            load_test.validate_phase(broken, "terrain-reuse", 1)

    def test_busy_and_timeout_responses_cannot_pass_as_normal_measurements(self):
        for statuses in ({"200": 1, "503": 1}, {"504": 2}, {"200": 1}):
            with self.subTest(statuses=statuses):
                phase = self.phase({"acquisitions": 2, "memoryHits": 2})
                phase["http"]["statusCounts"] = statuses
                with self.assertRaises(RuntimeError):
                    load_test.validate_phase(phase, "archive-reuse", 1)
        phase = self.phase({"acquisitions": 2, "memoryHits": 2})
        phase["http"]["errors"] = ["timed out"]
        with self.assertRaises(RuntimeError):
            load_test.validate_phase(phase, "archive-reuse", 1)

    def test_disk_memory_concurrency_and_monitor_failures_are_visible(self):
        base = self.phase({})["server"]
        changes = [
            ("peakActive", None, 2),
            ("active", None, 1),
            ("archive", "entries", 5),
            ("terrainCache", "bytes", 16 * 1024 * 1024 + 1),
            ("cache", "entry_count", 3),
            ("cache", "stored_bytes", 1025),
            ("memory", "cacheBoundViolations", 1),
            ("memory", "samples", 0),
            ("memory", "monitorErrors", ["missing cgroup"]),
        ]
        for section, key, value in changes:
            state = copy.deepcopy(base)
            if key is None:
                state[section] = value
            else:
                state[section][key] = value
            with (
                self.subTest(section=section, key=key),
                self.assertRaises(RuntimeError),
            ):
                load_test.validate_bounds(state, 1)
        for event in ("oom", "oom_kill"):
            state = copy.deepcopy(base)
            state["memory"]["after"]["memoryEvents"][event] = 1
            with self.assertRaisesRegex(RuntimeError, "OOM"):
                load_test.validate_bounds(state, 1)

    def test_requests_preserve_terrain_consent_and_derive_ground(self):
        geometric = load_test.request_for(2.5)
        terrain = load_test.request_for(2.5, "terrain")
        self.assertEqual(geometric["location"]["surfaceElevationM"], 100)
        self.assertNotIn("surfaceElevationM", terrain["location"])
        self.assertTrue(terrain["allowMeanEarthApproximation"])
        self.assertEqual(terrain["location"]["observerHeightM"], 2.5)
        geometric["location"]["latitudeDeg"] = 0
        self.assertEqual(load_test.REQUEST["location"]["latitudeDeg"], -89)

    def test_invalid_normal_concurrency_and_nonfinite_limits_are_rejected(self):
        for args in (
            ["--requests", "0"],
            ["--requests", "5"],
            ["--slots", "1", "--concurrency", "2"],
            ["--budget", "nan"],
            ["--cpus", "inf"],
        ):
            with (
                self.subTest(args=args),
                patch("sys.stderr"),
                self.assertRaises(SystemExit) as raised,
            ):
                load_test.main([*args, "--output", "unused.json"])
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
