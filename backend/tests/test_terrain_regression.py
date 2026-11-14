"""Hand-computed terrain cases and pinned API baselines; model checks, not observations."""

import hashlib
import json
import os
import unittest
from collections import Counter
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lunarwindow.api.app import create_app, get_reference_directory, get_terrain_directory
from lunarwindow.ephemeris.models import TimeRange, iso_utc, parse_utc
from lunarwindow.visibility import calculate_visibility

START = "2026-11-14T00:00:00Z"
REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
BASELINE = Path(__file__).parent / "fixtures/site01-terrain-regression.json"


def horizon(elevation):
    return [{"az": az, "el": float(elevation)} for az in range(360)]


def observation(hour, *, sun_az, earth_az, sun_el=1.0, earth_el=1.0):
    return {
        "t": iso_utc(parse_utc(START) + timedelta(hours=hour)),
        "sunAz": float(sun_az),
        "earthAz": float(earth_az),
        "sunEl": float(sun_el),
        "earthEl": float(earth_el),
        "sunAngularRadiusDeg": 0.25,
        "earthAngularRadiusDeg": 0.5,
    }


class AnalyticalTerrainRegressionTests(unittest.TestCase):
    def sector_case(self, *, as_of=None):
        # Both bodies stay one degree above local horizontal. Only their azimuths
        # change: north is blocked at +2 degrees; east is open at -1 degree.
        profile = horizon(-1)
        profile[0]["el"] = 2.0
        rows = [
            observation(hour, sun_az=sun, earth_az=earth)
            for hour, (sun, earth) in enumerate(zip([90, 0, 0, 90, 90, 0], [0, 90, 0, 90, 0, 90]))
        ]
        period = TimeRange(START, "2026-11-14T05:30:00Z", 60)
        return calculate_visibility(rows, profile, period, as_of_utc=as_of), rows, period

    def test_terrain_alone_blocks_bodies_and_changes_weighted_windows(self):
        result, rows, period = self.sector_case()
        self.assertEqual(
            [row.sunLit for row in result.series], [True, False, False, True, True, False]
        )
        self.assertEqual(
            [row.earthVis for row in result.series], [False, True, False, True, False, True]
        )
        # Hand totals: Sun 1+2 h; Earth 1+1+0.5 h; overlap only [03:00,04:00).
        self.assertEqual(result.metrics.evaluatedHrs, 5.5)
        self.assertEqual(result.metrics.sunlitHrs, 3)
        self.assertEqual(result.metrics.earthVisibleHrs, 2.5)
        self.assertEqual(result.metrics.bothHrs, 1)
        self.assertAlmostEqual(result.metrics.pctSun, 600 / 11)
        self.assertAlmostEqual(result.metrics.pctEarth, 500 / 11)
        self.assertAlmostEqual(result.metrics.pctBoth, 200 / 11)
        self.assertEqual(result.metrics.longestDarkHrs, 2)
        self.assertEqual(result.metrics.longestEarthBlackoutHrs, 1)
        self.assertEqual(result.metrics.longestBothHrs, 1)

        def window(start, end, duration, start_truncated=False, end_truncated=False):
            return {
                "startUtc": f"2026-11-14T{start}:00Z",
                "endUtc": f"2026-11-14T{end}:00Z",
                "durationHrs": duration,
                "startTruncated": start_truncated,
                "endTruncated": end_truncated,
            }

        self.assertEqual(
            result.windows.model_dump(),
            {
                "sunlit": [window("00:00", "01:00", 1, True), window("03:00", "05:00", 2)],
                "earthVisible": [
                    window("01:00", "02:00", 1),
                    window("03:00", "04:00", 1),
                    window("05:00", "05:30", 0.5, end_truncated=True),
                ],
                "both": [window("03:00", "04:00", 1)],
                "darkness": [
                    window("01:00", "03:00", 2),
                    window("05:00", "05:30", 0.5, end_truncated=True),
                ],
                "earthBlackout": [
                    window("00:00", "01:00", 1, True),
                    window("02:00", "03:00", 1),
                    window("04:00", "05:00", 1),
                ],
            },
        )
        geometric = calculate_visibility(rows, horizon(0), period)
        self.assertEqual(geometric.metrics.bothHrs, 5.5)
        self.assertEqual(geometric.metrics.longestDarkHrs, 0)
        self.assertEqual(geometric.metrics.longestEarthBlackoutHrs, 0)

    def test_terrain_setting_brackets_and_cursor_do_not_invent_exact_events(self):
        initial, _, _ = self.sector_case()
        selected, _, _ = self.sector_case(as_of="2026-11-14T01:30:00Z")
        self.assertEqual(
            initial.metrics.nextSunsetBracket.model_dump(),
            {"afterUtc": START, "byUtc": "2026-11-14T01:00:00Z"},
        )
        self.assertEqual(
            initial.metrics.nextEarthsetBracket.model_dump(),
            {"afterUtc": "2026-11-14T01:00:00Z", "byUtc": "2026-11-14T02:00:00Z"},
        )
        self.assertEqual(selected.metrics.nextSunset, "2026-11-14T05:00:00Z")
        self.assertEqual(selected.metrics.hoursToSunset, 3.5)
        self.assertEqual(selected.metrics.hoursToEarthset, 0.5)
        self.assertEqual(selected.metrics.nextSunsetBracket.afterUtc, "2026-11-14T04:00:00Z")
        self.assertEqual(selected.windows, initial.windows)
        self.assertEqual(selected.series, initial.series)

    def test_wraparound_negative_horizon_and_disc_tangencies_for_every_rule(self):
        profile = horizon(0)
        profile[359]["el"], profile[0]["el"], profile[1]["el"] = 4.0, 2.0, -4.0
        # Independent midpoints: h(359.5)=3 and h(0.5)=-1 degrees.
        # Upper-limb touch, center touch, partly clear center, lower-limb touch.
        rows = [
            observation(hour, sun_az=359.5, earth_az=0.5, sun_el=sun, earth_el=earth)
            for hour, (sun, earth) in enumerate(
                zip([2.75, 3, 3.125, 3.25], [-1.5, -1, -0.75, -0.5])
            )
        ]
        period = TimeRange(START, "2026-11-14T04:00:00Z", 60)
        for rule, flags, hours in (
            ("any-disc", [False, True, True, True], 3),
            ("body-center", [False, False, True, True], 2),
            ("full-disc", [False, False, False, True], 1),
        ):
            with self.subTest(rule=rule):
                result = calculate_visibility(rows, profile, period, rule=rule)
                for body, flag in (("sun", "sunLit"), ("earth", "earthVis")):
                    self.assertEqual([getattr(row, flag) for row in result.series], flags)
                    self.assertEqual(
                        [getattr(row, body + "Visibility") for row in result.series],
                        ["hidden", "partial", "partial", "full"],
                    )
                self.assertEqual([row.sunHorizonEl for row in result.series], [3] * 4)
                self.assertEqual([row.earthHorizonEl for row in result.series], [-1] * 4)
                self.assertEqual(result.metrics.bothHrs, hours)
                self.assertEqual(result.metrics.pctBoth, hours * 25)
                self.assertEqual(result.windows.both[0].startUtc, rows[4 - hours]["t"])
                self.assertTrue(result.windows.both[0].endTruncated)
        geometric = calculate_visibility(rows, horizon(0), period)
        self.assertEqual(geometric.metrics.earthVisibleHrs, 0)


class Site01TerrainRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = json.loads(BASELINE.read_text(encoding="utf-8"))
        cls.source_path = REFERENCE / "validation-30d/lola-site01-reference.json"
        cls.mask_path = REFERENCE / "terrain-masks/lola-site01-reference-mast-0m.json"
        cls.source_bytes = cls.source_path.read_bytes()
        cls.mask_bytes = cls.mask_path.read_bytes()
        cls.source = json.loads(cls.source_bytes)
        cls.mask = json.loads(cls.mask_bytes)
        app = create_app()
        app.dependency_overrides[get_reference_directory] = lambda: REFERENCE / "validation-30d"
        app.dependency_overrides[get_terrain_directory] = lambda: REFERENCE / "terrain-masks"
        client = TestClient(app)
        cls.addClassCleanup(client.close)
        cls.responses = {}
        # Block source retrieval without blocking Windows asyncio's socketpair.
        with (
            patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                side_effect=AssertionError("No NASA request"),
            ),
            patch(
                "lunarwindow.terrain.download.urlopen",
                side_effect=AssertionError("No DEM download"),
            ),
        ):
            for mode, cases in cls.expected["modes"].items():
                for rule in cases:
                    request = {
                        key: cls.expected[key]
                        for key in ("siteId", "startUtc", "endUtc", "stepMinutes")
                    } | {"horizonMode": mode, "visibilityRule": rule}
                    if mode == "terrain":
                        request |= {
                            "maskId": cls.expected["maskId"],
                            "allowMeanEarthApproximation": True,
                        }
                    response = client.post("/api/reference/evaluations", json=request)
                    if response.status_code != 200:
                        raise AssertionError(
                            f"{mode}/{rule}: {response.status_code} {response.text}"
                        )
                    cls.responses[mode, rule] = response.json()

    def test_source_identity_is_pinned_and_artifacts_are_unchanged(self):
        self.assertEqual(self.expected["schemaVersion"], "lunarwindow.terrain-regression.v1")
        self.assertEqual(
            self.expected["maskSha256"],
            "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d",
        )
        self.assertEqual(
            self.expected["ephemerisSha256"],
            "519628d7384992cc012039fe9df226a932d6c482de56b0b3277fdff6f30e9b50",
        )
        self.assertEqual(
            hashlib.sha256(self.source_bytes).hexdigest(), self.expected["ephemerisSha256"]
        )
        self.assertEqual(hashlib.sha256(self.mask_bytes).hexdigest(), self.expected["maskSha256"])
        self.assertEqual(self.source_path.read_bytes(), self.source_bytes)
        self.assertEqual(self.mask_path.read_bytes(), self.mask_bytes)

    def test_metrics_and_all_window_boundaries_match_independent_baseline(self):
        for (mode, rule), actual in self.responses.items():
            expected = self.expected["modes"][mode][rule]
            with self.subTest(mode=mode, rule=rule):
                for key, value in expected["metrics"].items():
                    if key.startswith("pct"):
                        self.assertAlmostEqual(actual["metrics"][key], value, places=10)
                    else:
                        self.assertEqual(actual["metrics"][key], value, key)
                self.assertEqual(actual["windows"], expected["windows"])

    def test_every_disc_state_and_visibility_flag_match_expected_intervals(self):
        def active(instant, windows):
            return any(window["startUtc"] <= instant < window["endUtc"] for window in windows)

        for (mode, rule), actual in self.responses.items():
            cases = self.expected["modes"][mode]
            with self.subTest(mode=mode, rule=rule):
                for body, flag, interval in (
                    ("sun", "sunLit", "sunlit"),
                    ("earth", "earthVis", "earthVisible"),
                ):
                    self.assertEqual(
                        dict(Counter(row[body + "Visibility"] for row in actual["series"])),
                        cases[rule]["discStateCounts"][body],
                    )
                    for row in actual["series"]:
                        any_disc = active(row["t"], cases["any-disc"]["windows"][interval])
                        full_disc = active(row["t"], cases["full-disc"]["windows"][interval])
                        state = "hidden" if not any_disc else "full" if full_disc else "partial"
                        self.assertEqual(row[body + "Visibility"], state, row["t"])
                        self.assertEqual(
                            row[flag], active(row["t"], cases[rule]["windows"][interval]), row["t"]
                        )
                by_time = {row["t"]: row for row in actual["series"]}
                for checkpoint in cases[rule]["horizonCheckpoints"]:
                    for field in ("sunHorizonEl", "earthHorizonEl"):
                        self.assertAlmostEqual(
                            by_time[checkpoint["t"]][field], checkpoint[field], places=12
                        )
                self.assertTrue(
                    all(
                        value > 1e-9
                        for value in cases[rule]["minAbsThresholdClearanceDeg"].values()
                    )
                )

    def test_api_preserves_original_evidence_and_frame_limitations_for_all_rules(self):
        for (mode, rule), actual in self.responses.items():
            with self.subTest(mode=mode, rule=rule):
                self.assertEqual(actual["dataMode"], "reference")
                self.assertEqual(actual["horizonMode"], mode)
                self.assertEqual(actual["provenance"]["ephemeris"], self.source["provenance"])
                self.assertEqual(
                    actual["provenance"]["archive"],
                    {
                        "startUtc": self.expected["startUtc"],
                        "endUtc": self.expected["endUtc"],
                        "endExclusive": True,
                        "stepMinutes": 60,
                        "sampleCount": 720,
                    },
                )
                self.assertEqual(
                    actual["calculation"],
                    {
                        "visibilityRule": rule,
                        "horizonInterpolation": "circular-linear",
                        "discModel": "local-horizontal-limb",
                        "timeModel": "sample-and-hold",
                        "eventTiming": "sample-transition-brackets",
                        "stepMinutes": 60,
                    },
                )
                raw_fields = set(self.source["series"][0])
                self.assertEqual(
                    [{key: row[key] for key in raw_fields} for row in actual["series"]],
                    self.source["series"],
                )
                if mode == "geometric":
                    self.assertEqual(actual["schemaVersion"], "lunarwindow.reference-evaluation.v1")
                    self.assertNotIn("terrain", actual["provenance"])
                    self.assertTrue(all(point["el"] == 0 for point in actual["horizon"]))
                    continue
                self.assertEqual(actual["schemaVersion"], "lunarwindow.reference-evaluation.v2")
                self.assertEqual(actual["maskId"], self.expected["maskId"])
                self.assertTrue(actual["allowMeanEarthApproximation"])
                terrain = actual["provenance"]["terrain"]
                self.assertEqual(terrain["artifactSha256"], self.expected["maskSha256"])
                self.assertEqual(terrain["mask"], self.mask)
                self.assertEqual(actual["horizon"], self.mask["horizon"])
                self.assertEqual(self.mask["observer"]["mastHeightM"], 0)
                assessment = terrain["compatibility"]
                self.assertEqual(assessment["maskId"], self.expected["maskId"])
                self.assertEqual(assessment["siteId"], self.expected["siteId"])
                self.assertEqual(assessment["framePolicy"], "mean-earth-reference-v1")
                self.assertEqual(assessment["frameStatus"], "approximate")
                self.assertIs(assessment["transformationApplied"], False)
                self.assertEqual(assessment["maskFrameName"], self.mask["referenceFrame"]["name"])
                self.assertEqual(
                    assessment["maskFrameRealization"], self.mask["referenceFrame"]["realization"]
                )
                self.assertEqual(assessment["ephemerisDynamicalSource"], "DE441")
                self.assertEqual(
                    assessment["ephemerisFrame"],
                    " ".join(
                        self.source["provenance"]["requests"][0]["modelHeader"][
                            "Center pole/equ"
                        ].split()
                    ),
                )
                self.assertEqual(assessment["referenceRadiusKm"], 1737.4)
                self.assertIn("residual", assessment["limitation"])
                self.assertIn("reference-demo approximation", assessment["limitation"])
                self.assertEqual(
                    assessment["references"],
                    [
                        "https://ssd.jpl.nasa.gov/horizons/manual.html",
                        "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/fk/satellites/moon_de440_250416.tf",
                    ],
                )
                self.assertIn("Near-field exclusions", actual["provenance"]["warning"])
