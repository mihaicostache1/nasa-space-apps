"""Offline integrity/contract checks using the reviewed Site01 terrain-mask artifact."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from lunarwindow.terrain import TerrainMask, load_terrain_mask

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)
MASK = REFERENCE / "terrain-masks/lola-site01-reference-mast-0m.json"
# Pinned to the reviewed handoff, independently of the artifact's adjacent sidecar.
SHA256 = "4554c4dd492b59f57d30e2de8cecb33d84714da5248f98acefdb8abccc446f6d"


class TerrainMaskLoaderTests(unittest.TestCase):
    def test_loads_reviewed_mask_offline_and_preserves_values_provenance_and_file(self):
        original = MASK.read_bytes()
        with patch("socket.socket.connect", side_effect=AssertionError("No network")):
            mask = load_terrain_mask(str(MASK), expected_sha256=SHA256)

        self.assertIsInstance(mask, TerrainMask)
        self.assertEqual(mask.model_dump(), json.loads(original))
        self.assertEqual(mask.maskId, "lola-site01-reference-mast-0m")
        self.assertEqual(len(mask.horizon), 360)
        self.assertLess(min(point.el for point in mask.horizon), 0)
        self.assertEqual(mask.observer.mastHeightM, 0.0)
        self.assertEqual(mask.referenceFrame.name, "MOON_ME")
        self.assertIn("DE421", mask.referenceFrame.realization)
        self.assertEqual([source.resolutionM for source in mask.provenance.sources], [5, 20, 120])
        Draft202012Validator(
            TerrainMask.model_json_schema(), format_checker=FormatChecker()
        ).validate(mask.model_dump())
        self.assertEqual(MASK.read_bytes(), original)

    def test_rejects_changed_bytes_even_when_the_json_and_contract_remain_valid(self):
        original = MASK.read_bytes()
        modified = json.loads(original)
        modified["horizon"][0]["el"] += 0.01
        for content in (original + b"\n", json.dumps(modified).encode("utf-8")):
            TerrainMask.model_validate_json(content)
            with self.subTest(content_hash=hashlib.sha256(content).hexdigest()):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "mask.json"
                    path.write_bytes(content)
                    with self.assertRaisesRegex(ValueError, "SHA-256 checksum mismatch"):
                        load_terrain_mask(path, expected_sha256=SHA256)

    def test_invalid_expected_checksums_are_rejected_before_reading_the_file(self):
        for checksum in (None, True, "", SHA256.upper(), "g" * 64, "0" * 63, "0" * 65):
            with self.subTest(checksum=checksum):
                with patch.object(Path, "read_bytes", side_effect=AssertionError("No read")):
                    with self.assertRaisesRegex(ValueError, "expected_sha256 must be"):
                        load_terrain_mask(MASK, expected_sha256=checksum)

    def test_missing_and_unreadable_files_fail_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            for path in (Path(temporary) / "missing.json", Path(temporary)):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, "Cannot load terrain mask"):
                        load_terrain_mask(path, expected_sha256=SHA256)
        with patch.object(Path, "read_bytes", side_effect=PermissionError("Access denied")):
            with self.assertRaisesRegex(ValueError, "Cannot load terrain mask.*Access denied"):
                load_terrain_mask(MASK, expected_sha256=SHA256)

    def test_matching_checksum_cannot_bypass_json_or_contract_validation(self):
        payload = json.loads(MASK.read_bytes())
        for damage in ("json", "encoding", "shape", "version", "metadata", "profile", "height"):
            altered = json.loads(json.dumps(payload))
            if damage == "json":
                content = b"{"
            elif damage == "encoding":
                content = b"\xff"
            elif damage == "shape":
                content = b"[]"
            else:
                if damage == "version":
                    altered["schemaVersion"] = "lunarwindow.terrain-mask.v999"
                elif damage == "metadata":
                    del altered["provenance"]
                elif damage == "profile":
                    altered["horizon"].pop()
                else:
                    altered["observer"]["altitudeKm"] += 1
                content = json.dumps(altered).encode("utf-8")
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "mask.json"
                path.write_bytes(content)
                with self.assertRaisesRegex(ValueError, "Cannot load terrain mask"):
                    load_terrain_mask(path, expected_sha256=hashlib.sha256(content).hexdigest())

    def test_hash_and_validation_use_the_same_file_snapshot(self):
        original = MASK.read_bytes()
        with patch.object(Path, "read_bytes", autospec=True, side_effect=[original, b"{}"]):
            mask = load_terrain_mask(MASK, expected_sha256=SHA256)
        self.assertEqual(mask.model_dump(), json.loads(original))
