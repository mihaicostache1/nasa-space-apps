"""Focused offline tests for loading one site from the committed reference run."""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lunarwindow.reference import load_reference_dataset, load_verified_reference_dataset

REFERENCE = (
    Path(
        os.environ.get(
            "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
        )
    )
    / "validation-30d"
)
SITE_ID = "lola-site01-reference"


class ReferenceLoaderTests(unittest.TestCase):
    def test_verified_artifact_checksum_identifies_the_exact_parsed_snapshot(self):
        original = (REFERENCE / f"{SITE_ID}.json").read_bytes()
        manifest = json.loads((REFERENCE / "manifest.json").read_bytes())
        read_bytes = Path.read_bytes
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / f"{SITE_ID}.json"
            path.write_bytes(original)

            def change_after_read(source):
                content = read_bytes(source)
                if source == path:
                    path.write_bytes(b"{}")
                return content

            # Simulate a file changing after verification and the final read.
            # A second read for hashing would identify bytes other than the data.
            with (
                patch("lunarwindow.reference.verify_run", return_value=manifest),
                patch.object(Path, "read_bytes", change_after_read),
            ):
                verified = load_verified_reference_dataset(directory, SITE_ID)
            self.assertEqual(verified.dataset, json.loads(original))
            self.assertEqual(verified.artifact_sha256, hashlib.sha256(original).hexdigest())
            self.assertNotEqual(
                verified.artifact_sha256, hashlib.sha256(path.read_bytes()).hexdigest()
            )

    def test_loads_one_real_dataset_with_original_samples_and_provenance(self):
        source = REFERENCE / f"{SITE_ID}.json"
        original = source.read_bytes()
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No network")
        ):
            dataset = load_reference_dataset(REFERENCE, SITE_ID)
        self.assertEqual(dataset, json.loads(original))
        self.assertEqual(len(dataset["series"]), 720)
        self.assertEqual(dataset["provenance"]["provider"], "NASA/JPL Horizons")
        self.assertEqual(source.read_bytes(), original)

    def test_unknown_site_has_a_clear_lookup_error(self):
        with self.assertRaisesRegex(LookupError, "Unknown reference site 'missing-site'"):
            load_reference_dataset(REFERENCE, "missing-site")

    def test_missing_or_corrupt_bundle_has_a_clear_validation_error(self):
        for damage in ("checksum", "missing-file", "incomplete", "malformed-manifest"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "reference"
                shutil.copytree(REFERENCE, directory)
                manifest_path = directory / "manifest.json"
                if damage == "checksum":
                    # A damaged sibling also invalidates the complete bundle.
                    (directory / "lola-site04-reference.json").write_text("{}", encoding="utf-8")
                elif damage == "missing-file":
                    (directory / f"{SITE_ID}.json").unlink()
                elif damage == "incomplete":
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["status"] = "incomplete"
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                else:
                    manifest_path.write_text("[]", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Cannot load reference bundle"):
                    load_reference_dataset(directory, SITE_ID)
