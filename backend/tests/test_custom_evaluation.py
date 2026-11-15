"""Custom-provider integration uses real archived angles and controlled adapter fixtures."""

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lunarwindow.api.custom_models import (
    CustomEvaluationRequest,
    canonical_model_sha256,
    observer_site_id,
)
from lunarwindow.api.custom_provider import (
    CustomEvaluationInputError,
    CustomTerrainUnavailableError,
    evaluate_custom,
)
from lunarwindow.api.custom_runtime import CustomRuntime, CustomSettings, build_custom_cache_key
from lunarwindow.ephemeris.custom import CustomEphemerisTimeout, CustomEphemerisUnavailable
from lunarwindow.ephemeris.horizons import query_parameters, query_url
from lunarwindow.reference import VerifiedReferenceDataset
from lunarwindow.terrain.horizon import default_parameters
from lunarwindow.terrain.models import HorizonProfile, TerrainMask
from lunarwindow.visibility import calculate_visibility

FIXTURE = Path(__file__).parent / "fixtures/dataset.json"
REQUEST = {
    "location": {
        "latitudeDeg": -89.0,
        "longitudeDeg": 0.0,
        "surfaceElevationM": 0.0,
        "observerHeightM": 0.0,
    },
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-14T03:00:00Z",
}
ACQUIRE = "lunarwindow.api.custom_provider.acquire_custom_ephemeris"
ENGINE = "lunarwindow.api.custom_provider.calculate_visibility"
PREPARE = "lunarwindow.api.custom_provider._prepare_terrain"


def verified_dataset(dataset):
    content = json.dumps(dataset, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return VerifiedReferenceDataset(dataset, hashlib.sha256(content).hexdigest())


def controlled_acquisition(site, period, **kwargs):
    """Adapt identity to the requested observer in an explicitly controlled test response.

    Base observer angles are real archived fixtures. Other observers deliberately
    use synthetic latitude-dependent Sun angles to test integration, not astronomy.
    The real Horizons adapter separately tests request construction and raw replay.
    """
    dataset = json.loads(FIXTURE.read_bytes())
    dataset.update(
        siteId=site.site_id,
        site=site.name,
        lat=site.lat,
        lon=site.lon,
        altitudeKm=site.altitude_km,
        coordinateSource=site.coordinate_source,
    )
    for request in dataset["provenance"]["requests"]:
        request["modelHeader"]["Center geodetic"] = (
            f"{site.lon},{site.lat},{site.altitude_km} {{E-lon(deg),Lat(deg),Alt(km)}}"
        )
        request["sourceUrl"] = query_url(
            query_parameters(site, request["target"], period.start, period.end, period.step_minutes)
        )
    for row in dataset["series"]:
        row["sunEl"] -= (site.lat + 89) * 10
    return verified_dataset(dataset)


def controlled_terrain(request, elevation=5.0):
    """Clearly synthetic profile/mask pair for testing the provider join, not GIS quality."""
    from os import environ

    reference = Path(
        environ.get("LUNARWINDOW_REFERENCE_DIR", str(FIXTURE.parents[3] / "data/reference"))
    )
    payload = json.loads(
        (reference / "terrain-masks/lola-site01-reference-mast-0m.json").read_bytes()
    )
    location = request.location
    ground = location.surfaceElevationM or 0.0
    altitude = (ground + location.observerHeightM) / 1000
    site_id = observer_site_id(location, altitude)
    payload.update(siteId=site_id, site="Custom lunar observer", maskId=f"{site_id}-terrain")
    payload["observer"].update(
        lat=location.latitudeDeg,
        lon=location.longitudeDeg,
        surfaceElevationM=ground,
        mastHeightM=location.observerHeightM,
        altitudeKm=altitude,
        coordinateSource="Controlled synthetic terrain observer for provider tests",
    )
    payload["horizon"] = [{"az": az, "el": elevation} for az in range(360)]
    payload["provenance"]["algorithm"]["name"] = "SYNTHETIC test horizon, not scientific data"
    mask = TerrainMask.model_validate(payload)
    profile = HorizonProfile(
        siteId=site_id,
        name=mask.site,
        lat=location.latitudeDeg,
        lon=location.longitudeDeg,
        coordinateSource=mask.observer.coordinateSource,
        terrainModel="lola-dem",
        surfaceElevationM=ground,
        mastHeightM=location.observerHeightM,
        observerAltitudeKm=altitude,
        referenceRadiusM=1_737_400,
        horizon=mask.horizon,
        rays={
            "stepDeg": 1.0,
            "el": [elevation] * 360,
            "horizonDistanceKm": [1.0] * 360,
            "reachKm": [200.0] * 360,
        },
        quality={
            "truncatedAzimuths": [],
            "minReachKm": 200,
            "missingSampleFraction": 0,
            "nearFieldAvailable": True,
            "warnings": ["SYNTHETIC provider fixture, not scientific data"],
        },
        parameters=default_parameters(mastHeightM=location.observerHeightM, raysPerDegree=1),
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
        algorithmVersion="synthetic-provider-test",
    )
    return SimpleNamespace(
        profile=profile,
        mask=mask,
        profile_sha256=canonical_model_sha256(profile),
        mask_sha256=canonical_model_sha256(mask),
    )


class CustomEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.make_runtime()
        self.request = CustomEvaluationRequest.model_validate(REQUEST)

    def make_runtime(self, **changes):
        return CustomRuntime(
            CustomSettings(
                **(
                    {
                        "enabled": True,
                        "archive_directory": self.root / "archive",
                        "dem_directory": self.root / "missing-dems",
                    }
                    | changes
                )
            )
        )

    def test_geometric_results_reuse_metrics_windows_engine_for_all_visibility_rules(self):
        for rule in ("any-disc", "body-center", "full-disc"):
            request = CustomEvaluationRequest.model_validate(
                REQUEST | {"visibilityRule": rule, "asOfUtc": "2026-11-14T01:00:00Z"}
            )
            with (
                self.subTest(rule=rule),
                patch(ACQUIRE, side_effect=controlled_acquisition) as acquire,
                patch(ENGINE, wraps=calculate_visibility) as engine,
                patch(
                    "lunarwindow.terrain.export.open_dems", side_effect=AssertionError("No DEMs")
                ),
            ):
                result = evaluate_custom(request, self.runtime)
                source = controlled_acquisition(*acquire.call_args.args)
                expected = calculate_visibility(
                    source.dataset["series"],
                    [{"az": az, "el": 0.0} for az in range(360)],
                    request.to_time_range(),
                    rule=rule,
                    as_of_utc=request.asOfUtc,
                )
                self.assertEqual(result.metrics, expected.metrics)
                self.assertEqual(result.windows, expected.windows)
                self.assertEqual(result.series, expected.series)
                self.assertEqual(result.calculation, expected.calculation)
                self.assertEqual(result.provenance.ephemeris, source.dataset["provenance"])
                self.assertEqual(result.provenance.ephemerisSha256, source.artifact_sha256)
                self.assertEqual(result.dataMode, "custom")
                self.assertEqual(engine.call_count, 1)
                self.assertLessEqual(acquire.call_args.kwargs["timeout_seconds"], 30)

    def test_coordinates_and_observer_height_reach_acquisition_and_change_result_identity(self):
        changed = CustomEvaluationRequest.model_validate(
            REQUEST
            | {
                "location": REQUEST["location"]
                | {"latitudeDeg": -88.0, "longitudeDeg": 17.0, "observerHeightM": 2.0}
            }
        )
        with patch(ACQUIRE, side_effect=controlled_acquisition) as acquire:
            first = evaluate_custom(self.request, self.runtime)
            second = evaluate_custom(changed, self.runtime)
        site = acquire.call_args.args[0]
        self.assertEqual((site.lat, site.lon, site.altitude_km), (-88.0, 17.0, 0.002))
        self.assertNotEqual(first.siteId, second.siteId)
        self.assertNotEqual(first.series, second.series)
        self.assertNotEqual(first.metrics.pctSun, second.metrics.pctSun)
        self.assertEqual(second.observer.mastHeightM, 2.0)
        self.assertEqual(second.observer.surfaceElevationM, 0.0)

    def test_cache_hits_reverify_sources_and_return_fresh_models(self):
        with patch(ACQUIRE, side_effect=controlled_acquisition) as acquire:
            first = evaluate_custom(self.request, self.runtime)
            original = first.model_dump()
            first.series[0] = first.series[0].model_copy(update={"sunEl": -90})
            first.metrics = first.metrics.model_copy(update={"pctSun": 0})
            with patch(ENGINE, side_effect=AssertionError("Cache hit must not calculate")):
                second = evaluate_custom(self.request, self.runtime)
            self.assertEqual(second.model_dump(), original)
            self.assertEqual(acquire.call_count, 2)
        with (
            patch(ACQUIRE, side_effect=CustomEphemerisUnavailable("Changed upstream archive")),
            self.assertRaises(CustomEphemerisUnavailable),
        ):
            evaluate_custom(self.request, self.runtime)

    def test_invalid_cached_payload_is_a_miss_without_losing_valid_source_evidence(self):
        with patch(ACQUIRE, side_effect=controlled_acquisition) as acquire:
            result = evaluate_custom(self.request, self.runtime)
            key = build_custom_cache_key(
                self.request, ephemeris_sha256=result.provenance.ephemerisSha256
            )
            self.runtime.cache.put(key, b"{}")
            with patch(ENGINE, wraps=calculate_visibility) as engine:
                replacement = evaluate_custom(self.request, self.runtime)
                self.assertEqual(replacement, result)
                self.assertEqual(engine.call_count, 1)
            self.assertEqual(acquire.call_count, 2)

    def test_wrong_snapshot_identity_or_checksum_is_rejected_before_cache_use(self):
        with patch(ACQUIRE, side_effect=controlled_acquisition) as acquire:
            evaluate_custom(self.request, self.runtime)
            original = controlled_acquisition(*acquire.call_args.args)
        changed = deepcopy(original.dataset)
        # This difference passes Horizons' displayed-header tolerance, but must
        # never identify the exact requested observer in the custom API.
        changed["lat"] += 1e-8
        for returned in (
            verified_dataset(changed),
            VerifiedReferenceDataset(original.dataset, "0" * 64),
        ):
            with (
                self.subTest(checksum=returned.artifact_sha256),
                patch(ACQUIRE, return_value=returned),
                patch(ENGINE, side_effect=AssertionError("Invalid sources cannot calculate")),
                self.assertRaises(CustomEphemerisUnavailable),
            ):
                evaluate_custom(self.request, self.runtime)

    def test_configured_limits_and_disabled_runtime_reject_before_work(self):
        from lunarwindow.api.custom_runtime import CustomDisabledError

        with patch(ACQUIRE, side_effect=AssertionError("No work")):
            with self.assertRaises(CustomEvaluationInputError):
                evaluate_custom(self.request, self.make_runtime(max_samples=2))
            with self.assertRaises(CustomDisabledError):
                evaluate_custom(self.request, self.make_runtime(enabled=False))

    def test_total_budget_expiry_does_not_publish_result_cache(self):
        with (
            patch(ACQUIRE, side_effect=controlled_acquisition),
            patch("lunarwindow.api.custom_provider.time.monotonic", side_effect=[0, 0, 31]),
            self.assertRaises(CustomEphemerisTimeout),
        ):
            evaluate_custom(self.request, self.runtime)
        self.assertEqual(self.runtime.cache.info().entry_count, 0)

    def test_terrain_joins_generated_observer_and_horizon_with_shared_engine(self):
        request = CustomEvaluationRequest.model_validate(
            REQUEST | {"horizonMode": "terrain", "allowMeanEarthApproximation": True}
        )
        prepared = controlled_terrain(request)
        with (
            patch(PREPARE, return_value=prepared),
            patch(ACQUIRE, side_effect=controlled_acquisition) as acquire,
            patch(ENGINE, wraps=calculate_visibility) as engine,
        ):
            result = evaluate_custom(request, self.make_runtime(terrain_enabled=True))
        self.assertEqual(acquire.call_args.args[0].altitude_km, prepared.mask.observer.altitudeKm)
        self.assertEqual(
            acquire.call_args.args[0].coordinate_source, prepared.mask.observer.coordinateSource
        )
        self.assertEqual(result.horizon, prepared.mask.horizon)
        self.assertEqual(result.observer, prepared.mask.observer)
        self.assertEqual(result.metrics.pctSun, 0)
        self.assertEqual(result.metrics.pctBoth, 0)
        self.assertEqual(result.metrics.longestDarkHrs, 3)
        self.assertEqual(result.provenance.terrain.profile, prepared.profile)
        self.assertEqual(result.provenance.terrain.maskSha256, prepared.mask_sha256)
        self.assertEqual(result.provenance.terrain.reviewStatus, "preliminary")
        self.assertEqual(result.provenance.terrain.compatibility.frameStatus, "approximate")
        self.assertFalse(result.provenance.terrain.compatibility.transformationApplied)
        self.assertIn("preliminary", result.provenance.warning)
        self.assertEqual(engine.call_count, 1)

    def test_terrain_cache_checks_current_full_provenance_and_changes_with_source_profile(self):
        request = CustomEvaluationRequest.model_validate(
            REQUEST | {"horizonMode": "terrain", "allowMeanEarthApproximation": True}
        )
        runtime = self.make_runtime(terrain_enabled=True)
        blocked = controlled_terrain(request, 5.0)
        clear = controlled_terrain(request, -60.0)
        with (
            patch(PREPARE, return_value=blocked),
            patch(ACQUIRE, side_effect=controlled_acquisition) as acquire,
        ):
            first = evaluate_custom(request, runtime)
            with patch(ENGINE, side_effect=AssertionError("Expected terrain cache hit")):
                self.assertEqual(evaluate_custom(request, runtime), first)
            self.assertEqual(acquire.call_count, 2)
        with (
            patch(PREPARE, return_value=clear),
            patch(ACQUIRE, side_effect=controlled_acquisition),
            patch(ENGINE, wraps=calculate_visibility) as engine,
        ):
            second = evaluate_custom(request, runtime)
            self.assertEqual(second.metrics.pctSun, 100)
            self.assertEqual(second.metrics.pctBoth, 100)
            self.assertEqual(engine.call_count, 1)
            terrain_checksum = hashlib.sha256(
                json.dumps(
                    [clear.profile_sha256, clear.mask_sha256], separators=(",", ":")
                ).encode()
            ).hexdigest()
            key = build_custom_cache_key(
                request,
                ephemeris_sha256=second.provenance.ephemerisSha256,
                terrain_sha256=terrain_checksum,
            )
            runtime.cache.put(key, first.model_dump_json().encode())
            replacement = evaluate_custom(request, runtime)
            self.assertEqual(replacement, second)
            self.assertEqual(engine.call_count, 2)

    def test_terrain_acceptance_and_enablement_fail_before_acquisition_or_dem_work(self):
        request = CustomEvaluationRequest.model_validate(REQUEST | {"horizonMode": "terrain"})
        with patch(ACQUIRE, side_effect=AssertionError("No upstream request")):
            with self.assertRaises(CustomEvaluationInputError):
                evaluate_custom(request, self.make_runtime(terrain_enabled=True))
            accepted = request.model_copy(update={"allowMeanEarthApproximation": True})
            with self.assertRaises(CustomTerrainUnavailableError):
                evaluate_custom(accepted, self.runtime)
