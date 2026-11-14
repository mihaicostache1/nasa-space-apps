"""Synthetic contract fixtures only; these are not generated or verified GIS masks."""

import copy
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from lunarwindow.terrain import TerrainMask


def contract_fixture():
    return {
        "schemaVersion": "lunarwindow.terrain-mask.v1",
        "maskId": "test-site-mast-2m",
        "siteId": "test-site",
        "site": "Synthetic contract test point",
        "terrainModel": "dem-horizon",
        "observer": {
            "lat": -89.0,
            "lon": 0.0,
            "coordinateSource": "Synthetic coordinates for contract tests only",
            "surfaceElevationM": 1000.0,
            "mastHeightM": 2.0,
            "altitudeKm": 1.002,
        },
        "referenceFrame": {
            "body": "Moon",
            "name": "TEST_MOON_FRAME",
            "realization": "unit-test-v1",
            "coordinateType": "GEODETIC",
            "longitudeConvention": "east-positive",
            "referenceSurface": {"shape": "sphere", "radiusKm": 1737.4},
        },
        "angularUnits": "degrees",
        "azimuthConvention": "clockwise-from-local-north",
        "elevationReference": "local-horizontal",
        "refractionModel": "none",
        "horizon": [{"az": az, "el": -0.5 if az == 0 else 1.0} for az in range(360)],
        "provenance": {
            "createdAtUtc": "2026-11-14T12:34:56.123Z",
            "sources": [
                {
                    "provider": "Synthetic contract fixture",
                    "productId": "test-dem",
                    "productVersion": "test-v1",
                    "sourceUrl": "https://example.invalid/test-dem.tif",
                    "sourceSha256": "1" * 64,
                    "retrievedAtUtc": "2026-11-14T12:30:01Z",
                    "resolutionM": 5.0,
                    "crs": "Synthetic projected CRS for contract testing",
                }
            ],
            "algorithm": {
                "name": "Synthetic test ray tracer",
                "version": "test-v1",
                "curvatureModel": "quadratic-drop",
                "rayStepM": 20.0,
                "maxDistanceM": 10000.0,
                "noDataPolicy": "reject",
            },
        },
    }


class TerrainMaskContractTests(unittest.TestCase):
    def test_contract_round_trip_and_exportable_json_schema(self):
        payload = contract_fixture()
        mask = TerrainMask.model_validate(payload)
        self.assertEqual(mask.model_dump(), payload)
        self.assertEqual(TerrainMask.model_validate_json(mask.model_dump_json()), mask)
        self.assertEqual(mask.horizon[0].el, -0.5)
        schema = TerrainMask.model_json_schema()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        self.assertEqual(
            schema["properties"]["schemaVersion"]["const"], "lunarwindow.terrain-mask.v1"
        )

    def test_coordinates_and_total_observer_height_are_validated(self):
        for changes in (
            {"lat": -91},
            {"lon": 181},
            {"lat": True},
            {"mastHeightM": -1},
            {"surfaceElevationM": float("nan")},
            {"altitudeKm": float("inf")},
            {"altitudeKm": 2.0},
            {"mastHeightM": "2"},
            {"coordinateSource": " "},
        ):
            payload = contract_fixture()
            payload["observer"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)
        payload = contract_fixture()
        payload["observer"] |= {"surfaceElevationM": -1000.0, "altitudeKm": -0.998}
        self.assertEqual(TerrainMask.model_validate(payload).observer.altitudeKm, -0.998)

    def test_incomplete_duplicate_unordered_or_nonfinite_profiles_are_rejected(self):
        for damage in (
            "missing",
            "extra",
            "duplicate",
            "unordered",
            "nonfinite",
            "no-data",
            "range",
        ):
            payload = contract_fixture()
            if damage == "missing":
                payload["horizon"].pop()
            elif damage == "extra":
                payload["horizon"].append({"az": 0, "el": 0.0})
            elif damage == "duplicate":
                payload["horizon"][-1]["az"] = 0
            elif damage == "unordered":
                payload["horizon"].reverse()
            elif damage == "nonfinite":
                payload["horizon"][5]["el"] = float("inf")
            elif damage == "no-data":
                payload["horizon"][5]["el"] = None
            else:
                payload["horizon"][5]["el"] = 91
            with self.subTest(damage=damage), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)

    def test_frame_units_and_required_conventions_cannot_be_implicit(self):
        for field in (
            "schemaVersion",
            "angularUnits",
            "azimuthConvention",
            "elevationReference",
            "refractionModel",
        ):
            payload = contract_fixture()
            del payload[field]
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)
        for field, value in (
            ("body", "Earth"),
            ("name", " "),
            ("realization", ""),
            ("coordinateType", "CARTESIAN"),
            ("longitudeConvention", "west-positive"),
        ):
            payload = contract_fixture()
            payload["referenceFrame"][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)
        payload = contract_fixture()
        payload["referenceFrame"]["referenceSurface"]["radiusKm"] = 0
        with self.assertRaises(ValidationError):
            TerrainMask.model_validate(payload)
        payload = contract_fixture()
        payload["angularUnits"] = "radians"
        with self.assertRaises(ValidationError):
            TerrainMask.model_validate(payload)

    def test_source_evidence_and_algorithm_metadata_are_required_and_validated(self):
        for field, value in (
            ("sourceSha256", "invalid"),
            ("sourceUrl", "relative/dem.tif"),
            ("sourceUrl", "ftp://example.invalid/dem.tif"),
            ("retrievedAtUtc", "2026-02-30T00:00:00Z"),
            ("retrievedAtUtc", "2026-11-14T00:00:00+02:00"),
            ("resolutionM", 0),
            ("productVersion", ""),
            ("crs", " "),
        ):
            payload = contract_fixture()
            payload["provenance"]["sources"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)
        for field, value in (
            ("noDataPolicy", "fill-zero"),
            ("curvatureModel", "none"),
            ("rayStepM", 20000.0),
            ("version", ""),
        ):
            payload = contract_fixture()
            payload["provenance"]["algorithm"][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                TerrainMask.model_validate(payload)
        payload = contract_fixture()
        payload["provenance"]["sources"] = []
        with self.assertRaises(ValidationError):
            TerrainMask.model_validate(payload)

    def test_extra_fields_are_rejected_and_validation_does_not_mutate_input(self):
        payload = contract_fixture()
        original = copy.deepcopy(payload)
        TerrainMask.model_validate(payload)
        self.assertEqual(payload, original)
        payload["verified"] = True
        with self.assertRaises(ValidationError):
            TerrainMask.model_validate(payload)
