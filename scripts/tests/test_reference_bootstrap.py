"""Startup discovery metadata must be reproducible from verified release evidence."""

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "build_reference_bootstrap",
    Path(__file__).resolve().parents[1] / "build_reference_bootstrap.py",
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class ReferenceBootstrapTests(unittest.TestCase):
    def test_committed_metadata_matches_verified_release_and_reviewed_catalog(self):
        metadata = bootstrap.build_metadata()
        self.assertEqual(
            metadata, json.loads(bootstrap.OUTPUT.read_text(encoding="utf-8"))
        )
        self.assertEqual([item["slot"] for item in metadata["scenarios"]], ["A", "B"])
        self.assertEqual(len(metadata["catalog"]["sites"]), 3)
        self.assertTrue(
            all(
                item["request"]["horizonMode"] == "geometric"
                for item in metadata["scenarios"]
            )
        )

    def test_unverified_release_cannot_produce_startup_metadata(self):
        with (
            patch.object(
                bootstrap, "verify_release", side_effect=ValueError("checksum mismatch")
            ),
            self.assertRaisesRegex(ValueError, "checksum mismatch"),
        ):
            bootstrap.build_metadata()


if __name__ == "__main__":
    unittest.main()
