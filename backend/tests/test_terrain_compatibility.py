"""Compatibility policy tests using reviewed artifacts and explicitly altered test copies."""

import copy
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.terrain import (
    TerrainCompatibilityError,
    TerrainMask,
    check_terrain_compatibility,
    load_terrain_mask,
)

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK_PATH = REFERENCE / "terrain-masks/lola-site01-reference-mast-0m.json"
MASK_SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"


class TerrainCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mask = load_terrain_mask(MASK_PATH, expected_sha256=MASK_SHA256)
        cls.archive = load_reference_dataset(REFERENCE / "validation-30d", "lola-site01-reference")
        cls.selected = select_reference_dataset(cls.archive, end_utc="2026-11-14T01:00:00Z")

    def setUp(self):
        self.dataset = copy.deepcopy(self.selected)

    def changed_mask(self, *, observer=None, frame=None, **changes):
        payload = self.mask.model_dump()
        payload.update(changes)
        payload["observer"].update(observer or {})
        payload["referenceFrame"].update(frame or {})
        return TerrainMask.model_validate(payload)

    def check(self, mask=None, dataset=None, **options):
        return check_terrain_compatibility(
            self.mask if mask is None else mask,
            self.dataset if dataset is None else dataset,
            allow_mean_earth_approximation=True,
            **options,
        )

    def set_headers(self, **changes):
        for request in self.dataset["provenance"]["requests"]:
            request["modelHeader"].update(changes)

    def test_real_pair_is_rejected_without_explicit_approximation(self):
        with self.assertRaisesRegex(TerrainCompatibilityError, "not established as identical"):
            check_terrain_compatibility(self.mask, self.dataset)

    def test_real_full_and_selected_pairs_return_traceable_reference_approximation(self):
        for dataset in (self.archive, self.selected):
            before = copy.deepcopy(dataset)
            mask_before = self.mask.model_dump()
            with self.subTest(samples=len(dataset["series"])):
                with patch("socket.socket.connect", side_effect=AssertionError("No network")):
                    result = self.check(dataset=dataset)
                self.assertEqual(result.frame_policy, "mean-earth-reference-v1")
                self.assertEqual(result.frame_status, "approximate")
                self.assertEqual(result.mask_id, self.mask.maskId)
                self.assertEqual(result.site_id, dataset["siteId"])
                self.assertEqual(result.mask_frame_name, "MOON_ME")
                self.assertEqual(
                    result.mask_frame_realization, self.mask.referenceFrame.realization
                )
                self.assertEqual(result.ephemeris_dynamical_source, "DE441")
                self.assertIn("MEAN_ME (high precision)", result.ephemeris_frame)
                self.assertFalse(result.transformation_applied)
                self.assertEqual(result.reference_radius_km, 1737.4)
                self.assertIn("residual", result.limitation)
                self.assertEqual(len(result.references), 2)
                self.assertEqual(dataset, before)
                self.assertEqual(self.mask.model_dump(), mask_before)
                self.assertEqual(asdict(self.check(dataset=dataset)), asdict(result))

    def test_site_and_coordinate_mismatches_cannot_be_overridden(self):
        for changes, message in (
            ({"siteId": "another-site"}, "siteId"),
            ({"observer": {"lat": self.mask.observer.lat + 0.0001}}, "latitude"),
            ({"observer": {"lon": self.mask.observer.lon + 0.0001}}, "longitude"),
        ):
            mask = self.changed_mask(**changes)
            for allow in (False, True):
                with self.subTest(changes=changes, allow=allow):
                    with self.assertRaisesRegex(TerrainCompatibilityError, message):
                        check_terrain_compatibility(
                            mask, self.dataset, allow_mean_earth_approximation=allow
                        )

    def test_two_metre_mast_requires_matching_total_observer_altitude(self):
        taller = self.changed_mask(
            observer={"mastHeightM": 2.0, "altitudeKm": self.mask.observer.altitudeKm + 0.002}
        )
        with self.assertRaisesRegex(TerrainCompatibilityError, "total observer altitude"):
            self.check(mask=taller)
        self.dataset["altitudeKm"] = taller.observer.altitudeKm
        for request in self.dataset["provenance"]["requests"]:
            header = request["modelHeader"]
            lon, lat, _ = header["Center geodetic"].split("{")[0].split(",")
            header["Center geodetic"] = f"{lon},{lat},{taller.observer.altitudeKm}"
        self.assertEqual(self.check(mask=taller).frame_status, "approximate")

    def test_reference_sphere_must_match_all_three_axes_with_known_units(self):
        for radii in (
            "1737.4, 1737.4, 1737.5 km {Equator_a, b, pole_c}",
            "1738, 1738, 1738 km",
            "1737400, 1737400, 1737400 m",
            "nan, 1737.4, 1737.4 km",
            "1737.4, 1737.4 km",
            "0, 0, 0 km",
        ):
            self.set_headers(**{"Center radii": radii})
            with self.subTest(radii=radii), self.assertRaises(TerrainCompatibilityError):
                self.check()
        self.dataset = copy.deepcopy(self.selected)
        other_sphere = self.changed_mask(
            frame={"referenceSurface": {"shape": "sphere", "radiusKm": 1738.0}}
        )
        with self.assertRaisesRegex(TerrainCompatibilityError, "sphere radii differ"):
            self.check(mask=other_sphere)

    def test_unknown_mask_frames_and_realizations_are_rejected(self):
        for frame in (
            {"name": "IAU_MOON"},
            {"name": "MOON_PA"},
            {"realization": "DE441"},
            {"realization": "unknown DE421"},
            {"realization": "DE4211"},
        ):
            with self.subTest(frame=frame):
                with self.assertRaisesRegex(TerrainCompatibilityError, "Unsupported mask frame"):
                    self.check(mask=self.changed_mask(frame=frame))
        alias = self.changed_mask(frame={"name": "MOON_ME_DE421", "realization": "DE421"})
        self.assertEqual(self.check(mask=alias).frame_status, "approximate")

    def test_unknown_or_incomplete_ephemeris_frame_evidence_is_rejected(self):
        for key, value in (
            ("Center body name", "Earth (399) {source: DE441}"),
            ("Center body name", "Moon (301) {source: DE430}"),
            ("Center body name", ""),
            ("Center pole/equ", "IAU_MOON {East-longitude positive}"),
            ("Center pole/equ", "MEAN_ME (low precision) {East-longitude positive}"),
            ("Center pole/equ", "MEAN_ME (high precision) {West-longitude positive}"),
            ("Atmos refraction", "YES"),
        ):
            self.dataset = copy.deepcopy(self.selected)
            self.set_headers(**{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(TerrainCompatibilityError):
                self.check()

    def test_dynamical_source_is_separate_from_frame_and_must_be_consistent(self):
        self.set_headers(**{"Center body name": "Moon (301) {source: DE440}"})
        result = self.check()
        self.assertEqual(result.ephemeris_dynamical_source, "DE440")
        self.assertEqual(result.frame_status, "approximate")
        self.dataset["provenance"]["requests"][0]["modelHeader"]["Center body name"] = (
            "Moon (301) {source: DE441}"
        )
        with self.assertRaisesRegex(TerrainCompatibilityError, "inconsistent reference models"):
            self.check()
        self.set_headers(**{"Center body name": "Moon (301) {source: DE441}"})
        self.set_headers(**{"Center pole/equ": "MOON_ME {East-longitude positive}"})
        self.assertEqual(self.check().frame_status, "approximate")

    def test_only_roundoff_is_tolerated_and_longitude_wrap_is_supported(self):
        near = self.changed_mask(
            observer={
                "lat": self.mask.observer.lat + 1e-10,
                "altitudeKm": self.mask.observer.altitudeKm + 0.5e-6,
                "surfaceElevationM": self.mask.observer.surfaceElevationM + 0.0005,
            }
        )
        self.assertEqual(self.check(mask=near).frame_status, "approximate")
        far = self.changed_mask(
            observer={
                "altitudeKm": self.mask.observer.altitudeKm + 2e-6,
                "surfaceElevationM": self.mask.observer.surfaceElevationM + 0.002,
            }
        )
        with self.assertRaisesRegex(TerrainCompatibilityError, "total observer altitude"):
            self.check(mask=far)
        self.dataset["lon"] = -180.0
        self.set_headers(
            **{"Center geodetic": (f"180,{self.mask.observer.lat},{self.mask.observer.altitudeKm}")}
        )
        self.assertEqual(
            self.check(mask=self.changed_mask(observer={"lon": 180.0})).frame_status, "approximate"
        )

    def test_invalid_contracts_and_non_boolean_opt_in_are_rejected(self):
        invalid_mask = self.mask.model_copy(deep=True)
        invalid_mask.horizon.pop()
        with self.assertRaisesRegex(TerrainCompatibilityError, "Invalid compatibility input"):
            self.check(mask=invalid_mask)
        del self.dataset["provenance"]
        with self.assertRaisesRegex(TerrainCompatibilityError, "Invalid compatibility input"):
            self.check()
        with self.assertRaisesRegex(TerrainCompatibilityError, "must be a boolean"):
            check_terrain_compatibility(
                self.mask, self.selected, allow_mean_earth_approximation="true"
            )

    def test_reference_approximation_is_restricted_to_documented_modern_period(self):
        self.dataset["provenance"].update(
            startUtc="2040-01-01T00:00:00Z", endUtc="2040-01-01T01:00:00Z"
        )
        self.dataset["series"][0]["t"] = "2040-01-01T00:00:00Z"
        with self.assertRaisesRegex(TerrainCompatibilityError, "2000–2039"):
            self.check()
        self.dataset["provenance"].update(
            startUtc="2039-12-31T23:00:00Z", endUtc="2040-01-01T00:00:00Z"
        )
        self.dataset["series"][0]["t"] = "2039-12-31T23:00:00Z"
        self.assertEqual(self.check().frame_status, "approximate")
