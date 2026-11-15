"""Custom observer units, strict validation, and response consistency without API calls."""

import copy
import hashlib
import json
import math
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from lunarwindow.api.custom_models import (
    CustomEvaluation,
    CustomEvaluationRequest,
    CustomLocation,
    canonical_model_sha256,
    observer_site_id,
)
from lunarwindow.api.terrain_models import TerrainCompatibilityProvenance
from lunarwindow.ephemeris.horizons import HorizonsClient
from lunarwindow.ephemeris.models import Site, TimeRange
from lunarwindow.reference import load_reference_dataset, select_reference_dataset
from lunarwindow.terrain.compatibility import check_terrain_compatibility
from lunarwindow.terrain.horizon import default_parameters
from lunarwindow.terrain.models import HorizonProfile, TerrainMask
from lunarwindow.visibility import calculate_visibility

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
FIXTURES = Path(__file__).parent / "fixtures"
REQUEST = {
    "location": {
        "latitudeDeg": -89.0,
        "longitudeDeg": 0.0,
        "observerHeightM": 0.0,
        "surfaceElevationM": 0.0,
    },
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
}


class CustomRequestContractTests(unittest.TestCase):
    def test_explicit_geometric_height_semantics_and_defaults(self):
        request = CustomEvaluationRequest.model_validate(REQUEST)
        self.assertEqual(request.location.observerHeightM, 0)
        self.assertEqual(request.location.surfaceElevationM, 0)
        self.assertEqual(request.stepMinutes, 60)
        self.assertEqual(request.visibilityRule, "any-disc")
        self.assertFalse(request.allowMeanEarthApproximation)
        self.assertIsNone(request.asOfUtc)
        terrain = copy.deepcopy(REQUEST)
        terrain["horizonMode"] = "terrain"
        del terrain["location"]["surfaceElevationM"]
        self.assertIsNone(
            CustomEvaluationRequest.model_validate(terrain).location.surfaceElevationM
        )
        self.assertFalse(
            CustomEvaluationRequest.model_validate(terrain).allowMeanEarthApproximation
        )

    def test_missing_observer_fields_mode_or_geometric_surface_are_rejected(self):
        for field in ("latitudeDeg", "longitudeDeg", "observerHeightM", "surfaceElevationM"):
            payload = copy.deepcopy(REQUEST)
            del payload["location"][field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CustomEvaluationRequest.model_validate(payload)
        payload = copy.deepcopy(REQUEST)
        del payload["horizonMode"]
        with self.assertRaises(ValidationError):
            CustomEvaluationRequest.model_validate(payload)

    def test_coordinates_and_heights_reject_strings_booleans_nonfinite_and_out_of_range(self):
        cases = {
            "latitudeDeg": [True, "-89", -90.001, 90.001, None],
            "longitudeDeg": [False, "0", -180.001, 180.001, None],
            "observerHeightM": [False, "2", -0.001, 1000.001, None],
            "surfaceElevationM": [True, "0", -20_001, 20_001],
        }
        for field, values in cases.items():
            for value in values + [math.nan, math.inf, -math.inf]:
                payload = copy.deepcopy(REQUEST)
                payload["location"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    CustomEvaluationRequest.model_validate(payload)

    def test_invalid_options_unknown_fields_and_unbounded_dates_are_rejected(self):
        cases = (
            {"horizonMode": "fake"},
            {"allowMeanEarthApproximation": True},
            {"allowMeanEarthApproximation": "true"},
            {"allowMeanEarthApproximation": 1},
            {"visibilityRule": "unknown"},
            {"stepMinutes": True},
            {"stepMinutes": 0},
            {"stepMinutes": "60"},
            {"startUtc": "1999-12-31T23:00:00Z"},
            {"endUtc": "2040-01-01T00:01:00Z"},
            {"endUtc": "2026-12-16T00:00:00Z"},
            {"endUtc": "2026-11-22T00:00:00Z", "stepMinutes": 1},
            {"asOfUtc": REQUEST["endUtc"]},
            {"startUtc": "2026-11-14T00:00:01Z"},
            {"maskPath": "/tmp/arbitrary.json"},
            {"siteId": "reference-site"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CustomEvaluationRequest.model_validate(REQUEST | changes)

    def test_equivalent_coordinates_and_times_have_stable_identity_without_rounding(self):
        request = CustomEvaluationRequest.model_validate(
            REQUEST
            | {
                "location": REQUEST["location"] | {"longitudeDeg": 180, "observerHeightM": -0.0},
                "startUtc": "2026-11-14T00:00Z",
            }
        )
        equivalent = CustomLocation.model_validate(REQUEST["location"] | {"longitudeDeg": -180.0})
        self.assertEqual(request.startUtc, REQUEST["startUtc"])
        self.assertEqual(request.location.longitudeDeg, -180)
        self.assertEqual(math.copysign(1, request.location.observerHeightM), 1)
        self.assertEqual(observer_site_id(request.location, -0.0), observer_site_id(equivalent, 0))
        changed = equivalent.model_copy(update={"latitudeDeg": equivalent.latitudeDeg + 1e-9})
        self.assertNotEqual(observer_site_id(changed, 0), observer_site_id(equivalent, 0))
        self.assertNotEqual(observer_site_id(equivalent, 1e-9), observer_site_id(equivalent, 0))

    def test_json_schema_exposes_required_units_and_model_shapes(self):
        schema = CustomEvaluationRequest.model_json_schema()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(REQUEST)
        location = schema["$defs"]["CustomLocation"]
        self.assertIn("observerHeightM", location["required"])
        self.assertIn(
            "metres above the local ground",
            location["properties"]["observerHeightM"]["description"],
        )
        self.assertIn("horizonMode", schema["required"])


class CustomResponseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = CustomLocation.model_validate(REQUEST["location"])
        site_id = observer_site_id(location, 0.0)
        site = Site(site_id, "Custom observer", -89.0, 0.0, 0.0, "User-supplied ground and height")
        period = TimeRange(REQUEST["startUtc"], REQUEST["endUtc"])
        archives = [
            json.loads((FIXTURES / f"{target}.json").read_bytes()) for target in ("sun", "earth")
        ]
        client = HorizonsClient()
        with patch.object(client, "fetch", side_effect=archives):
            dataset = client.evaluate(site, period)
        horizon = [{"az": az, "el": 0.0} for az in range(360)]
        calculated = calculate_visibility(dataset["series"], horizon, period)
        cls.geometric = {
            "siteId": site_id,
            "site": site.name,
            "observer": {
                "lat": -89.0,
                "lon": 0.0,
                "coordinateSource": site.coordinate_source,
                "surfaceElevationM": 0.0,
                "mastHeightM": 0.0,
                "altitudeKm": 0.0,
            },
            "horizonMode": "geometric",
            "allowMeanEarthApproximation": False,
            "horizon": horizon,
            **calculated.model_dump(),
            "provenance": {
                "ephemeris": dataset["provenance"],
                "ephemerisSha256": hashlib.sha256(
                    json.dumps(
                        dataset, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest(),
                "warning": "Geometric horizon; terrain and link performance are not modeled.",
            },
        }
        mask = TerrainMask.model_validate_json(
            (REFERENCE / "terrain-masks/lola-site01-reference-mast-0m.json").read_bytes()
        )
        source = select_reference_dataset(
            load_reference_dataset(REFERENCE / "validation-30d", mask.siteId),
            end_utc="2026-11-14T03:00:00Z",
        )
        parameters = default_parameters(mastHeightM=0, raysPerDegree=1)
        profile = HorizonProfile(
            siteId=mask.siteId,
            name=mask.site,
            lat=mask.observer.lat,
            lon=mask.observer.lon,
            coordinateSource=mask.observer.coordinateSource,
            terrainModel="lola-dem",
            surfaceElevationM=mask.observer.surfaceElevationM,
            mastHeightM=0,
            observerAltitudeKm=mask.observer.altitudeKm,
            referenceRadiusM=1_737_400,
            horizon=mask.horizon,
            rays={
                "stepDeg": 1.0,
                "el": [point.el for point in mask.horizon],
                "horizonDistanceKm": [1.0] * 360,
                "reachKm": [200.0] * 360,
            },
            quality={
                "truncatedAzimuths": [],
                "minReachKm": 200,
                "missingSampleFraction": 0,
                "nearFieldAvailable": True,
                "warnings": ["Synthetic profile wrapper for contract tests only"],
            },
            parameters=parameters,
            sources=[
                {
                    "productId": item.productId,
                    "role": "site-tile",
                    "sourceUrl": item.sourceUrl,
                    "sha256": item.sourceSha256,
                    "resolutionM": item.resolutionM,
                }
                for item in mask.provenance.sources
            ],
            algorithmVersion="contract-test-profile",
        )
        visibility = calculate_visibility(source["series"], mask.horizon, period)
        compatibility = check_terrain_compatibility(
            mask, source, allow_mean_earth_approximation=True
        )
        cls.terrain = {
            "siteId": mask.siteId,
            "site": mask.site,
            "observer": mask.observer.model_dump(),
            "horizonMode": "terrain",
            "allowMeanEarthApproximation": True,
            "horizon": [point.model_dump() for point in mask.horizon],
            **visibility.model_dump(),
            "provenance": {
                "ephemeris": source["provenance"],
                "ephemerisSha256": hashlib.sha256(
                    json.dumps(
                        source, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                ).hexdigest(),
                "terrain": {
                    "profile": profile.model_dump(),
                    "profileSha256": canonical_model_sha256(profile),
                    "mask": mask.model_dump(),
                    "maskSha256": canonical_model_sha256(mask),
                    "compatibility": TerrainCompatibilityProvenance.from_assessment(
                        compatibility
                    ).model_dump(),
                },
                "warning": "Generated terrain is preliminary, with an accepted frame approximation.",
            },
        }

    def test_geometric_and_terrain_response_round_trip_without_recalculation(self):
        for original in (self.geometric, self.terrain):
            with (
                self.subTest(mode=original["horizonMode"]),
                patch(
                    "lunarwindow.visibility.calculate_visibility",
                    side_effect=AssertionError("No run"),
                ),
            ):
                response = CustomEvaluation.model_validate(original)
            self.assertEqual(response.schemaVersion, "lunarwindow.custom-evaluation.v1")
            self.assertEqual(response.dataMode, "custom")
            self.assertEqual(
                CustomEvaluation.model_validate_json(response.model_dump_json()), response
            )
            Draft202012Validator(CustomEvaluation.model_json_schema()).validate(
                response.model_dump()
            )

    def test_geometric_response_cannot_hide_terrain_or_change_source_observer(self):
        for change in (
            "observer",
            "horizon",
            "sample-horizon",
            "acceptance",
            "grid",
            "hours",
            "source",
        ):
            payload = copy.deepcopy(self.geometric)
            if change == "observer":
                payload["observer"]["lat"] = -88
            elif change == "horizon":
                payload["horizon"][0]["el"] = 1
            elif change == "sample-horizon":
                payload["series"][0]["sunHorizonEl"] = 1
            elif change == "acceptance":
                payload["allowMeanEarthApproximation"] = True
            elif change == "grid":
                payload["calculation"]["stepMinutes"] = 30
            elif change == "hours":
                payload["metrics"]["evaluatedHrs"] = 7
            else:
                payload["provenance"]["ephemerisSha256"] = "0" * 64
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CustomEvaluation.model_validate(payload)

    def test_rehashed_profile_cannot_disagree_with_mask_sources_or_claim_complete_reach(self):
        for damage in ("sources", "reach"):
            payload = copy.deepcopy(self.terrain)
            terrain = payload["provenance"]["terrain"]
            if damage == "sources":
                terrain["profile"]["sources"][0]["sha256"] = "0" * 64
            else:
                terrain["profile"]["quality"]["minReachKm"] = 100
            terrain["profileSha256"] = canonical_model_sha256(
                HorizonProfile.model_validate(terrain["profile"])
            )
            with self.subTest(damage=damage), self.assertRaises(ValidationError):
                CustomEvaluation.model_validate(payload)

    def test_terrain_response_rejects_mismatch_missing_data_or_claimed_review(self):
        for change in (
            "missing",
            "acceptance",
            "observer",
            "profile-hash",
            "mask-hash",
            "frame",
            "incomplete",
            "review",
        ):
            payload = copy.deepcopy(self.terrain)
            terrain = payload["provenance"]["terrain"]
            if change == "missing":
                payload["provenance"]["terrain"] = None
            elif change == "acceptance":
                payload["allowMeanEarthApproximation"] = False
            elif change == "observer":
                terrain["profile"]["lat"] += 0.001
            elif change == "profile-hash":
                terrain["profileSha256"] = "0" * 64
            elif change == "mask-hash":
                terrain["maskSha256"] = "0" * 64
            elif change == "frame":
                terrain["compatibility"]["ephemerisDynamicalSource"] = "DE440"
            elif change == "incomplete":
                terrain["profile"]["quality"]["truncatedAzimuths"] = [0]
            else:
                terrain["reviewStatus"] = "reviewed"
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CustomEvaluation.model_validate(payload)
