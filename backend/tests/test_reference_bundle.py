"""Offline backend handoff and provenance checks against the shipped 30-day bundle."""

import hashlib
import json
import os
import unittest
from pathlib import Path

from lunarwindow.ephemeris.contract import validate_dataset, verify_run
from lunarwindow.ephemeris.horizons import merge_series, parse_response
from lunarwindow.ephemeris.models import TimeRange

REFERENCE = Path(
    os.environ.get(
        "LUNARWINDOW_REFERENCE_DIR", str(Path(__file__).resolve().parents[2] / "data/reference")
    )
)


class ReferenceBundleTests(unittest.TestCase):
    def test_backend_can_consume_all_three_reference_datasets(self):
        directory = REFERENCE / "validation-30d"
        manifest = verify_run(directory)
        self.assertEqual(len(manifest["datasets"]), 3)
        for item in manifest["datasets"]:
            dataset = validate_dataset(json.loads((directory / item["json"]).read_text()))
            self.assertEqual(len(dataset["series"]), 720)
            period = TimeRange("2026-11-14T00:00Z", "2026-12-14T00:00Z", 60)
            bodies = {}
            for request in dataset["provenance"]["requests"]:
                key = hashlib.sha256(request["sourceUrl"].encode()).hexdigest()
                archive = json.loads((REFERENCE / "horizons" / f"{key}.json").read_text())
                self.assertEqual(archive["sourceUrl"], request["sourceUrl"])
                self.assertEqual(
                    hashlib.sha256(archive["rawResponse"].encode()).hexdigest(),
                    request["responseSha256"],
                )
                samples, _, _ = parse_response(
                    archive["rawResponse"], request["target"], require_diameter=True
                )
                bodies[request["target"]] = samples
            normalized = merge_series(
                bodies["sun"], bodies["earth"], period.start, period.end, period.step
            )
            self.assertEqual(normalized, dataset["series"])


if __name__ == "__main__":
    unittest.main()
