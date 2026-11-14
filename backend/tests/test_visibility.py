"""Analytical visibility cases, boundary conditions, and real-contract compatibility."""

import copy
import json
import random
import unittest
from datetime import timedelta
from pathlib import Path

from lunarwindow.ephemeris.models import TimeRange, iso_utc, parse_utc
from lunarwindow.visibility import calculate_visibility

START = "2026-11-14T00:00:00Z"


def flat_horizon(elevation=0.0):
    return [{"az": az, "el": elevation} for az in range(360)]


def sample(t, sun=5.0, earth=5.0, **changes):
    return {
        "t": t,
        "sunAz": 0.0,
        "sunEl": float(sun),
        "earthAz": 0.0,
        "earthEl": float(earth),
        "sunAngularRadiusDeg": 0.25,
        "earthAngularRadiusDeg": 0.5,
    } | changes


def inputs(sun, earth=None, *, end=None, step=60):
    if end is None:
        end = iso_utc(parse_utc(START) + timedelta(minutes=len(sun) * step))
    period = TimeRange(START, end, step)
    if earth is None:
        earth = sun
    rows = [
        sample(iso_utc(period.start + index * period.step), sun_el, earth_el)
        for index, (sun_el, earth_el) in enumerate(zip(sun, earth))
    ]
    return rows, flat_horizon(), period


class VisibilityTests(unittest.TestCase):
    def test_continuous_visibility_and_clipped_windows(self):
        result = calculate_visibility(*inputs([5, 5, 5]))
        metrics = result.metrics
        self.assertEqual((metrics.pctSun, metrics.pctEarth, metrics.pctBoth), (100, 100, 100))
        self.assertEqual(metrics.sunlitHrs, 3)
        self.assertEqual(metrics.longestDarkHrs, 0)
        self.assertEqual(metrics.longestEarthBlackoutHrs, 0)
        self.assertEqual(metrics.longestBothHrs, 3)
        self.assertEqual(result.windows.darkness, [])
        self.assertIsNone(metrics.nextSunset)
        self.assertIsNone(metrics.nextEarthset)
        self.assertIsNone(metrics.hoursToSunset)
        window = result.windows.both[0]
        self.assertEqual(window.durationHrs, 3)
        self.assertTrue(window.startTruncated)
        self.assertTrue(window.endTruncated)

    def test_continuous_darkness_is_a_real_zero_and_never_a_setting_event(self):
        result = calculate_visibility(*inputs([-5, -5, -5]))
        metrics = result.metrics
        self.assertEqual((metrics.pctSun, metrics.pctEarth, metrics.pctBoth), (0, 0, 0))
        self.assertEqual(metrics.longestDarkHrs, 3)
        self.assertEqual(metrics.longestEarthBlackoutHrs, 3)
        self.assertEqual(metrics.longestBothHrs, 0)
        self.assertEqual(result.windows.sunlit, [])
        self.assertTrue(result.windows.darkness[0].endTruncated)
        self.assertIsNone(metrics.nextSunset)
        self.assertIsNone(metrics.nextSunsetBracket)

    def test_windows_intersections_gaps_and_first_setting_brackets(self):
        result = calculate_visibility(*inputs([5, 5, -5, -5, 5, -5], [-5, 5, 5, -5, 5, 5]))
        metrics = result.metrics
        self.assertEqual(metrics.sunlitHrs, 3)
        self.assertEqual(metrics.earthVisibleHrs, 4)
        self.assertEqual(metrics.bothHrs, 2)
        self.assertEqual(metrics.pctSun, 50)
        self.assertAlmostEqual(metrics.pctEarth, 100 * 4 / 6)
        self.assertAlmostEqual(metrics.pctBoth, 100 * 2 / 6)
        self.assertEqual(metrics.longestDarkHrs, 2)
        self.assertEqual(metrics.longestEarthBlackoutHrs, 1)
        self.assertEqual(metrics.longestBothHrs, 1)
        self.assertEqual([window.durationHrs for window in result.windows.both], [1, 1])
        self.assertEqual(metrics.nextSunset, "2026-11-14T02:00:00Z")
        self.assertEqual(metrics.nextEarthset, "2026-11-14T03:00:00Z")
        self.assertEqual(metrics.hoursToSunset, 2)
        self.assertEqual(metrics.hoursToEarthset, 3)
        self.assertEqual(metrics.nextSunsetBracket.afterUtc, "2026-11-14T01:00:00Z")
        self.assertEqual(metrics.nextSunsetBracket.byUtc, metrics.nextSunset)
        self.assertTrue(result.windows.sunlit[0].startTruncated)
        self.assertFalse(result.windows.sunlit[0].endTruncated)
        self.assertFalse(result.windows.sunlit[1].startTruncated)
        self.assertFalse(result.windows.sunlit[1].endTruncated)
        self.assertTrue(result.windows.darkness[-1].endTruncated)

    def test_percentages_weight_a_short_final_bin_by_its_duration(self):
        result = calculate_visibility(*inputs([5, -5, 5], [-5, 5, 5], end="2026-11-14T02:30:00Z"))
        metrics = result.metrics
        self.assertEqual(metrics.evaluatedHrs, 2.5)
        self.assertEqual(metrics.sunlitHrs, 1.5)
        self.assertEqual(metrics.earthVisibleHrs, 1.5)
        self.assertEqual(metrics.bothHrs, 0.5)
        self.assertEqual((metrics.pctSun, metrics.pctEarth, metrics.pctBoth), (60, 60, 20))
        self.assertEqual(result.windows.both[0].endUtc, "2026-11-14T02:30:00Z")
        self.assertEqual(result.windows.both[0].durationHrs, 0.5)

    def test_single_sample_shorter_than_step_has_no_invented_endpoint_event(self):
        result = calculate_visibility(*inputs([5], end="2026-11-14T00:17:00Z"))
        self.assertAlmostEqual(result.metrics.evaluatedHrs, 17 / 60)
        self.assertEqual(result.metrics.pctBoth, 100)
        self.assertEqual(len(result.windows.both), 1)
        self.assertIsNone(result.metrics.nextSunset)
        self.assertTrue(result.windows.both[0].endTruncated)

    def test_selected_time_only_changes_countdowns(self):
        args = inputs([5, 5, -5, -5, 5, -5])
        initial = calculate_visibility(*args)
        selected = calculate_visibility(*args, as_of_utc="2026-11-14T01:30:00Z")
        self.assertEqual(selected.metrics.hoursToSunset, 0.5)
        self.assertEqual(selected.metrics.nextSunset, initial.metrics.nextSunset)
        self.assertEqual(selected.windows, initial.windows)
        self.assertEqual(selected.series, initial.series)
        self.assertEqual(selected.metrics.pctSun, initial.metrics.pctSun)
        self.assertEqual(selected.metrics.nextSunsetBracket.afterUtc, "2026-11-14T01:00:00Z")
        just_set = calculate_visibility(*args, as_of_utc="2026-11-14T02:00:00Z")
        self.assertEqual(just_set.metrics.hoursToSunset, 0)
        after_set = calculate_visibility(*args, as_of_utc="2026-11-14T02:01:00Z")
        self.assertEqual(after_set.metrics.nextSunset, "2026-11-14T05:00:00Z")
        self.assertAlmostEqual(after_set.metrics.hoursToSunset, 179 / 60)
        after_last = calculate_visibility(*args, as_of_utc="2026-11-14T05:01:00Z")
        self.assertIsNone(after_last.metrics.nextSunset)
        self.assertIsNone(after_last.metrics.hoursToSunset)

    def test_already_dark_can_find_a_later_setting_after_a_rise(self):
        result = calculate_visibility(*inputs([-5, -5, 5, -5]))
        self.assertEqual(result.metrics.nextSunset, "2026-11-14T03:00:00Z")
        self.assertEqual(result.metrics.hoursToSunset, 3)

    def test_partial_disc_and_tangent_boundaries_for_all_rules(self):
        angles = [-0.5, -0.25, -0.1, 0, 0.1, 0.25, 0.5]
        args = inputs(angles, [2 * value for value in angles])
        expected_states = ["hidden", "hidden", "partial", "partial", "partial", "full", "full"]
        for rule, expected_flags in [
            ("any-disc", [False, False, True, True, True, True, True]),
            ("body-center", [False, False, False, False, True, True, True]),
            ("full-disc", [False, False, False, False, False, True, True]),
        ]:
            with self.subTest(rule=rule):
                result = calculate_visibility(*args, rule=rule)
                self.assertEqual([row.sunVisibility for row in result.series], expected_states)
                self.assertEqual([row.earthVisibility for row in result.series], expected_states)
                self.assertEqual([row.sunLit for row in result.series], expected_flags)
                self.assertEqual([row.earthVis for row in result.series], expected_flags)
                self.assertEqual(result.calculation.visibilityRule, rule)

    def test_uses_each_bodys_supplied_angular_radius(self):
        result = calculate_visibility(*inputs([-0.3]))
        self.assertFalse(result.series[0].sunLit)
        self.assertTrue(result.series[0].earthVis)
        self.assertEqual(result.series[0].earthVisibility, "partial")

    def test_horizon_interpolates_fractional_azimuths_and_the_north_seam(self):
        rows, horizon, period = inputs([2.5])
        horizon[359]["el"], horizon[0]["el"], horizon[1]["el"] = 4.0, 2.0, 4.0
        rows[0] |= {"sunAz": 0.25, "earthAz": 359.5, "earthEl": 2.5}
        result = calculate_visibility(rows, horizon, period)
        self.assertEqual(result.series[0].sunHorizonEl, 2.5)
        self.assertEqual(result.series[0].earthHorizonEl, 3)
        self.assertTrue(result.series[0].sunLit)
        self.assertFalse(result.series[0].earthVis)  # Upper limb only touches the mask.

    def test_negative_horizons_are_preserved(self):
        rows, _, period = inputs([-1])
        result = calculate_visibility(rows, flat_horizon(-2.0), period)
        self.assertTrue(result.series[0].sunLit)
        self.assertEqual(result.series[0].sunHorizonEl, -2)

    def test_all_step_sizes_and_tail_lengths_preserve_duration_invariants(self):
        rng = random.Random(42)
        for step in (1, 7, 60, 137, 1440):
            sun = [rng.choice((-5, 5)) for _ in range(20)]
            earth = [rng.choice((-5, 5)) for _ in range(20)]
            end = iso_utc(parse_utc(START) + timedelta(minutes=19 * step + max(1, step // 2)))
            result = calculate_visibility(*inputs(sun, earth, step=step, end=end))
            metrics, windows = result.metrics, result.windows
            self.assertAlmostEqual(
                metrics.sunlitHrs + sum(window.durationHrs for window in windows.darkness),
                metrics.evaluatedHrs,
            )
            self.assertAlmostEqual(
                metrics.earthVisibleHrs
                + sum(window.durationHrs for window in windows.earthBlackout),
                metrics.evaluatedHrs,
            )
            self.assertLessEqual(metrics.bothHrs, min(metrics.sunlitHrs, metrics.earthVisibleHrs))
            self.assertAlmostEqual(metrics.pctBoth, 100 * metrics.bothHrs / metrics.evaluatedHrs)
            for lane in (windows.sunlit, windows.earthVisible, windows.both):
                for window in lane:
                    self.assertLess(parse_utc(window.startUtc), parse_utc(window.endUtc))
                    self.assertLessEqual(parse_utc(window.endUtc), parse_utc(end))
                for previous, following in zip(lane, lane[1:]):
                    self.assertLess(parse_utc(previous.endUtc), parse_utc(following.startUtc))

    def test_inputs_are_not_mutated_and_repeated_calculations_match(self):
        args = inputs([5, -5, 5])
        before = copy.deepcopy(args)
        result = calculate_visibility(*args)
        self.assertEqual(args, before)
        self.assertEqual(result, calculate_visibility(*args))

    def test_rejects_incomplete_duplicate_or_unordered_masks(self):
        rows, horizon, period = inputs([5])
        duplicate = copy.deepcopy(horizon)
        duplicate[-1]["az"] = 0
        nonfinite = copy.deepcopy(horizon)
        nonfinite[10]["el"] = float("nan")
        for invalid in (
            horizon[:-1],
            horizon + [horizon[0]],
            list(reversed(horizon)),
            duplicate,
            nonfinite,
        ):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                calculate_visibility(rows, invalid, period)

    def test_rejects_missing_extra_duplicate_or_off_grid_samples(self):
        rows, horizon, period = inputs([5, -5, 5])
        duplicate = copy.deepcopy(rows)
        duplicate[1]["t"] = rows[0]["t"]
        off_grid = copy.deepcopy(rows)
        off_grid[1]["t"] = "2026-11-14T01:01:00Z"
        for invalid in (
            [],
            rows[:-1],
            rows + [rows[-1]],
            list(reversed(rows)),
            duplicate,
            off_grid,
        ):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                calculate_visibility(invalid, horizon, period)

    def test_rejects_invalid_angles_radii_and_precomputed_flags(self):
        rows, horizon, period = inputs([5])
        for changes in (
            {"sunAz": -1},
            {"earthAz": 360},
            {"sunEl": 91},
            {"earthEl": float("inf")},
            {"sunAngularRadiusDeg": 0},
            {"earthAngularRadiusDeg": 90},
            {"sunAngularRadiusDeg": True},
            {"sunLit": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                calculate_visibility([rows[0] | changes], horizon, period)

    def test_rejects_unknown_rule_or_selected_time_outside_range(self):
        args = inputs([5, -5])
        with self.assertRaises(ValueError):
            calculate_visibility(*args, rule="unknown")
        for timestamp in (
            "2026-11-13T23:59:00Z",
            "2026-11-14T02:00:00Z",
            "2026-11-14T00:00:00+02:00",
            "2026-11-14T00:00:01Z",
        ):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                calculate_visibility(*args, as_of_utc=timestamp)

    def test_accepts_archived_ephemeris_contract_without_changing_provenance(self):
        path = Path(__file__).parent / "fixtures/dataset.json"
        dataset = json.loads(path.read_text(encoding="utf-8"))
        before = copy.deepcopy(dataset)
        provenance = dataset["provenance"]
        period = TimeRange(provenance["startUtc"], provenance["endUtc"], provenance["stepMinutes"])
        result = calculate_visibility(dataset["series"], flat_horizon(), period)
        self.assertEqual(result.metrics.pctSun, 100)
        self.assertEqual(result.metrics.pctEarth, 0)
        self.assertEqual(result.metrics.pctBoth, 0)
        self.assertEqual(result.metrics.longestDarkHrs, 0)
        self.assertEqual(result.metrics.longestEarthBlackoutHrs, result.metrics.evaluatedHrs)
        self.assertEqual(dataset, before)


if __name__ == "__main__":
    unittest.main()
