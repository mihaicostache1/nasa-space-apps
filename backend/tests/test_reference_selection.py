"""Archive range selection preserves exact samples and NASA request evidence."""

import copy
import json
import os
import unittest
from pathlib import Path

from lunarwindow.ephemeris.contract import validate_dataset
from lunarwindow.reference import ReferenceSelectionError, select_reference_dataset

REFERENCE = (
    Path(
        os.environ.get(
            "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
        )
    )
    / "validation-30d/lola-site01-reference.json"
)


class ReferenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(REFERENCE.read_text(encoding="utf-8"))

    def test_selects_exact_half_open_day_and_retains_original_request_evidence(self):
        original = copy.deepcopy(self.dataset)
        selected = select_reference_dataset(
            self.dataset, start_utc="2026-11-15T00:00Z", end_utc="2026-11-16T00:00Z"
        )
        self.assertEqual(selected["series"], self.dataset["series"][24:48])
        self.assertEqual(
            selected["provenance"],
            self.dataset["provenance"]
            | {
                "startUtc": "2026-11-15T00:00:00Z",
                "endUtc": "2026-11-16T00:00:00Z",
            },
        )
        self.assertEqual(validate_dataset(selected), selected)
        self.assertEqual(self.dataset, original)
        selected["series"][0]["sunEl"] = -90
        selected["provenance"]["requests"][0]["sourceUrl"] = "changed"
        self.assertEqual(self.dataset, original)

    def test_defaults_return_the_full_archive(self):
        self.assertEqual(select_reference_dataset(self.dataset), self.dataset)

    def test_step_only_selects_every_second_existing_sample(self):
        selected = select_reference_dataset(self.dataset, step_minutes=120)
        self.assertEqual(selected["series"], self.dataset["series"][::2])
        self.assertEqual(len(selected["series"]), 360)
        self.assertEqual(selected["provenance"]["stepMinutes"], 120)
        self.assertEqual(selected["provenance"]["requests"], self.dataset["provenance"]["requests"])

    def test_requested_start_anchors_the_stride_and_end_can_fall_between_samples(self):
        selected = select_reference_dataset(
            self.dataset,
            start_utc="2026-11-14T01:00:00Z",
            end_utc="2026-11-14T06:01:00Z",
            step_minutes=120,
        )
        self.assertEqual(selected["series"], self.dataset["series"][1:7:2])
        self.assertEqual(selected["provenance"]["endUtc"], "2026-11-14T06:01:00Z")
        self.assertEqual(validate_dataset(selected), selected)

    def test_one_sided_bounds_and_last_archive_interval(self):
        last = select_reference_dataset(self.dataset, start_utc="2026-12-13T23:00:00Z")
        self.assertEqual(last["series"], self.dataset["series"][-1:])
        self.assertEqual(last["provenance"]["endUtc"], "2026-12-14T00:00:00Z")
        first = select_reference_dataset(self.dataset, end_utc="2026-11-14T02:30:00Z")
        self.assertEqual(first["series"], self.dataset["series"][:3])
        short = select_reference_dataset(self.dataset, end_utc="2026-11-14T00:01:00Z")
        self.assertEqual(short["series"], self.dataset["series"][:1])

    def test_rejects_unavailable_dates_off_grid_starts_and_unsupported_steps(self):
        cases = [
            {"start_utc": "2026-11-13T23:00:00Z"},
            {"end_utc": "2026-12-14T00:01:00Z"},
            {"start_utc": "2026-12-14T00:00:00Z"},
            {"end_utc": "2026-11-14T00:00:00Z"},
            {"start_utc": "2026-11-16T00:00:00Z", "end_utc": "2026-11-15T00:00:00Z"},
            {"start_utc": "2026-11-14T00:30:00Z"},
            {"start_utc": "2026-11-14"},
            {"start_utc": "2026-11-14T00:00:01Z"},
            {"start_utc": "2026-11-14T00:00:00+02:00"},
            {"step_minutes": 30},
            {"step_minutes": 90},
            {"step_minutes": 0},
            {"step_minutes": 1441},
            {"step_minutes": True},
            {"step_minutes": 60.5},
        ]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ReferenceSelectionError):
                select_reference_dataset(self.dataset, **options)

    def test_invalid_source_data_is_not_reported_as_a_request_error(self):
        self.dataset["series"][0]["sunEl"] = 91
        with self.assertRaises(ValueError) as caught:
            select_reference_dataset(self.dataset, end_utc="2026-11-15T00:00:00Z")
        self.assertNotIsInstance(caught.exception, ReferenceSelectionError)
