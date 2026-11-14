"""Guard against misleading load-test success and mixed latency populations."""

import copy
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "load_test_api", Path(__file__).resolve().parents[1] / "load_test_api.py"
)
load_test = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(load_test)


class LoadTestReportTests(unittest.TestCase):
    def phase(self):
        return {
            "http": {"errors": [], "statusCounts": {"200": 2}},
            "server": {
                "counters": {"savedHits": 2},
                "cache": {
                    "entry_count": 0,
                    "max_entries": 32,
                    "stored_bytes": 0,
                    "max_bytes": 16_777_216,
                },
                "memory": {
                    "cacheBoundViolations": 0,
                    "baseline": {"memoryEvents": {"oom": 0, "oom_kill": 0}},
                    "after": {"memoryEvents": {"oom": 0, "oom_kill": 0}},
                },
            },
        }

    def test_rejections_do_not_make_successful_latency_appear_faster(self):
        report = load_test.summarize(
            [
                {"status": 200, "latencyMs": 200, "bytes": 100},
                {"status": 200, "latencyMs": 100, "bytes": 100},
                *[{"status": 503, "latencyMs": 1, "bytes": 10}] * 10,
            ],
            2,
        )
        self.assertEqual(report["latencyMsByStatus"]["200"]["p95"], 200)
        self.assertEqual(report["successfulRequestsPerSecond"], 1)
        self.assertEqual(report["statusCounts"], {"200": 2, "503": 10})

    def test_calculation_or_miss_cannot_be_reported_as_saved_or_memory_hit(self):
        phase = self.phase()
        load_test.validate_phase(phase, "saved")
        phase["server"]["counters"] = {"savedMisses": 2, "memoryHits": 2}
        load_test.validate_phase(phase, "memory")
        with self.assertRaisesRegex(RuntimeError, "Execution path"):
            load_test.validate_phase(phase, "saved")
        phase["server"]["counters"]["calculations"] = 1
        with self.assertRaisesRegex(RuntimeError, "Execution path"):
            load_test.validate_phase(phase, "memory")

    def test_unexpected_status_timeout_cache_breach_and_oom_fail_measurement(self):
        changes = [
            ("http", "statusCounts", {"503": 2}),
            ("http", "errors", ["timed out"]),
            (
                "server",
                "cache",
                {
                    "entry_count": 33,
                    "max_entries": 32,
                    "stored_bytes": 0,
                    "max_bytes": 16_777_216,
                },
            ),
            (
                "server",
                "cache",
                {
                    "entry_count": 1,
                    "max_entries": 32,
                    "stored_bytes": 17_000_000,
                    "max_bytes": 16_777_216,
                },
            ),
        ]
        for section, key, value in changes:
            with self.subTest(key=key, value=value):
                phase = self.phase()
                phase[section][key] = value
                with self.assertRaises(RuntimeError):
                    load_test.validate_phase(phase, "saved")
        for event in ("oom", "oom_kill"):
            phase = self.phase()
            phase["server"]["memory"]["after"]["memoryEvents"][event] = 1
            with self.assertRaisesRegex(RuntimeError, "OOM"):
                load_test.validate_phase(phase, "saved")

    def test_rejections_are_allowed_only_in_explicit_overload_phase(self):
        phase = self.phase()
        phase["http"]["statusCounts"]["503"] = 30
        load_test.validate_phase(phase, "saved", overload=True)
        with self.assertRaisesRegex(RuntimeError, "Unexpected HTTP"):
            load_test.validate_phase(phase, "saved")
        rejected = copy.deepcopy(phase)
        rejected["http"]["statusCounts"] = {"503": 32}
        rejected["server"]["counters"] = {}
        load_test.validate_phase(rejected, "saved", overload=True)


if __name__ == "__main__":
    unittest.main()
