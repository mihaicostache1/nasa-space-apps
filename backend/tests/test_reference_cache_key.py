"""Cache identity equivalence, invalidation boundaries, and strict input checks."""

import hashlib
import json
import unittest
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from lunarwindow.api.reference_cache_key import (
    ReferenceEvaluationCacheKey,
    build_reference_evaluation_cache_key,
)
from lunarwindow.api.terrain_models import ReferenceEvaluationRequestContract
from lunarwindow.visibility.models import VISIBILITY_MODEL_VERSION

REQUEST = {
    "siteId": "lola-site01-reference",
    "horizonMode": "geometric",
    "startUtc": "2026-11-14T00:00:00Z",
    "endUtc": "2026-11-15T00:00:00Z",
}
TERRAIN = {
    **REQUEST,
    "horizonMode": "terrain",
    "maskId": "lola-site01-reference-mast-0m",
    "allowMeanEarthApproximation": True,
}
# Identity-only test inputs, not claims about verified production artifacts.
EPHEMERIS_SHA256 = "1" * 64
MASK_SHA256 = "2" * 64
ADAPTER = TypeAdapter(ReferenceEvaluationRequestContract)


def key(payload=None, **sources):
    payload = REQUEST if payload is None else payload
    options = {"ephemeris_sha256": EPHEMERIS_SHA256}
    if payload["horizonMode"] == "terrain":
        options["terrain_mask_sha256"] = MASK_SHA256
    options.update(sources)
    return build_reference_evaluation_cache_key(ADAPTER.validate_python(payload), **options)


class ReferenceCacheKeyTests(unittest.TestCase):
    def test_defaults_equivalent_utc_forms_and_mapping_order_share_identity(self):
        for base in (REQUEST, TERRAIN):
            explicit = base | {
                "stepMinutes": 60,
                "visibilityRule": "any-disc",
                "asOfUtc": base["startUtc"],
            }
            minutes = explicit | {
                name: explicit[name].replace(":00Z", "Z")
                for name in ("startUtc", "endUtc", "asOfUtc")
            }
            expected = key(base)
            for payload in (explicit, minutes, dict(reversed(list(explicit.items())))):
                with self.subTest(mode=base["horizonMode"], payload=payload):
                    actual = key(payload)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual.digest, expected.digest)

    def test_each_calculation_input_changes_identity(self):
        original = key()
        for change in (
            {"siteId": "lola-site04-reference"},
            {"startUtc": "2026-11-14T01:00:00Z"},
            {"endUtc": "2026-11-14T23:00:00Z"},
            # An end between samples changes the final interval's weight.
            {"endUtc": "2026-11-14T23:30:00Z"},
            {"stepMinutes": 120},
            {"visibilityRule": "body-center"},
            {"visibilityRule": "full-disc"},
            {"asOfUtc": "2026-11-14T01:00:00Z"},
        ):
            with self.subTest(change=change):
                self.assertNotEqual(key(REQUEST | change).digest, original.digest)
        self.assertNotEqual(key(TERRAIN).digest, original.digest)

    def test_source_artifacts_mask_id_acceptance_and_model_version_change_identity(self):
        for base in (REQUEST, TERRAIN):
            original = key(base)
            self.assertNotEqual(key(base, ephemeris_sha256="3" * 64).digest, original.digest)
            self.assertNotEqual(
                key(base, calculation_model_version="lunarwindow.visibility.v2").digest,
                original.digest,
            )
        original = key(TERRAIN)
        self.assertNotEqual(key(TERRAIN, terrain_mask_sha256="4" * 64).digest, original.digest)
        self.assertNotEqual(
            key(TERRAIN | {"maskId": "another-reviewed-mask"}).digest, original.digest
        )
        # Recording a rejected policy is not the same as accepting it. Neither
        # key authorizes a lookup before the provider checks compatibility.
        self.assertNotEqual(
            key(TERRAIN | {"allowMeanEarthApproximation": False}).digest, original.digest
        )

    def test_digest_has_a_fixed_canonical_encoding_and_round_trips(self):
        actual = key()
        expected = (
            '{"allowMeanEarthApproximation":false,"asOfUtc":"2026-11-14T00:00:00Z",'
            '"calculationModelVersion":"lunarwindow.visibility.v1",'
            '"endUtc":"2026-11-15T00:00:00Z",'
            '"ephemerisSha256":"' + EPHEMERIS_SHA256 + '",'
            '"horizonMode":"geometric","maskId":null,'
            '"schemaVersion":"lunarwindow.reference-cache-key.v1",'
            '"siteId":"lola-site01-reference","startUtc":"2026-11-14T00:00:00Z",'
            '"stepMinutes":60,"terrainMaskSha256":null,"visibilityRule":"any-disc"}'
        )
        self.assertEqual(actual.model_dump(mode="json"), json.loads(expected))
        self.assertEqual(actual.digest, hashlib.sha256(expected.encode("utf-8")).hexdigest())
        self.assertEqual(actual.calculationModelVersion, VISIBILITY_MODEL_VERSION)
        restored = ReferenceEvaluationCacheKey.model_validate_json(actual.model_dump_json())
        self.assertEqual(restored, actual)
        self.assertEqual(restored.digest, actual.digest)
        with self.assertRaises(ValidationError):
            actual.stepMinutes = 120

    def test_checksums_are_required_and_geometric_keys_cannot_include_a_mask(self):
        for checksum in ("", "a" * 63, "A" * 64, "g" * 64, 1, None):
            with self.subTest(checksum=checksum), self.assertRaises(ValidationError):
                key(ephemeris_sha256=checksum)
            with self.subTest(mask_checksum=checksum), self.assertRaises(ValidationError):
                key(TERRAIN, terrain_mask_sha256=checksum)
        with self.assertRaises(ValidationError):
            key(REQUEST, terrain_mask_sha256=MASK_SHA256)
        for version in ("", "  ", 1):
            with self.subTest(version=version), self.assertRaises(ValidationError):
                key(calculation_model_version=version)

    def test_malformed_or_mutated_requests_cannot_create_a_key(self):
        for change in (
            {"asOfUtc": REQUEST["endUtc"]},
            {"stepMinutes": True},
            {"visibilityRule": "unknown"},
            {"unexpected": "value"},
            {"horizonMode": "synthetic"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                key(REQUEST | change)
        request = ADAPTER.validate_python(REQUEST)
        request.stepMinutes = 0
        with self.assertRaises(ValidationError):
            build_reference_evaluation_cache_key(request, ephemeris_sha256=EPHEMERIS_SHA256)
        payload = key().model_dump() | {"maskId": "unexpected-mask"}
        with self.assertRaises(ValidationError):
            ReferenceEvaluationCacheKey.model_validate(payload)

    def test_building_identity_never_loads_sources_or_calculates_visibility(self):
        with (
            patch("pathlib.Path.read_bytes", side_effect=AssertionError("No source reads")),
            patch("pathlib.Path.write_bytes", side_effect=AssertionError("No cache writes")),
            patch("socket.socket.connect", side_effect=AssertionError("No network")),
            patch(
                "lunarwindow.api.reference_provider.calculate_visibility",
                side_effect=AssertionError("No calculation"),
            ),
        ):
            self.assertEqual(key().digest, key().digest)
            self.assertEqual(key(TERRAIN).digest, key(TERRAIN).digest)
