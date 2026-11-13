"""Offline tests against archived, real NASA responses; no API calls."""

import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from lunarwindow.ephemeris import HorizonsClient, HorizonsError, Site, TimeRange
from lunarwindow.ephemeris.cli import load_sites
from lunarwindow.ephemeris.horizons import (
    merge_series,
    parse_response,
    query_parameters,
    query_url,
    validate_observer,
)
from lunarwindow.ephemeris.models import parse_utc

FIXTURES = Path(__file__).parent / "fixtures"
SITE = Site("polar-example", "Illustrative polar point", -89, 0, 0, "Test point")
PERIOD = TimeRange("2026-11-14T00:00:00Z", "2026-11-14T03:00:00Z")


def archive(target):
    return json.loads((FIXTURES / f"{target}.json").read_text())


class ModelTests(unittest.TestCase):
    def test_invalid_coordinates(self):
        for lat, lon, altitude in [(-91, 0, 0), (0, 181, 0), (True, 0, 0), (0, 0, float("nan"))]:
            with self.subTest(lat=lat, lon=lon, altitude=altitude), self.assertRaises(ValueError):
                Site("test", "Test", lat, lon, altitude, "Test")

    def test_invalid_times(self):
        for value in [
            "2026-11-14",
            "2026-11-14Z",
            "2026-11-14T00:00:00+02:00",
            "2026-02-30T00:00Z",
            "2026-11-14T00:00:01Z",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_utc(value)
        with self.assertRaises(ValueError):
            TimeRange(PERIOD.start_utc, PERIOD.start_utc)
        with self.assertRaises(ValueError):
            TimeRange("2026-01-01T00:00Z", "2031-01-01T00:00Z", 1)

    def test_chunks_remain_on_grid(self):
        period = TimeRange("2026-01-01T00:00Z", "2026-04-01T00:00Z", 137)
        chunks = list(period.chunks())
        self.assertEqual(chunks[0][0], period.start)
        self.assertEqual(chunks[-1][1], period.end)
        for index, (start, end) in enumerate(chunks):
            self.assertEqual((start - period.start) % period.step, timedelta(0))
            self.assertLessEqual(end - start, timedelta(days=30))
            if index:
                self.assertEqual(chunks[index - 1][1], start)

    def test_reject_duplicate_site_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sites.json"
            site = {
                "id": "test",
                "name": "Test",
                "lat": 0,
                "lon": 0,
                "altitudeKm": 0,
                "coordinateSource": "Test",
            }
            path.write_text(json.dumps([site, site]))
            with self.assertRaises(ValueError):
                load_sites(path)

    def test_query_keeps_below_horizon_samples(self):
        params = query_parameters(SITE, "earth", PERIOD.start, PERIOD.end, 60)
        self.assertEqual(params["CENTER"], "'coord@301'")
        self.assertEqual(params["COMMAND"], "'399'")
        self.assertEqual(params["ELEV_CUT"], "'-90'")
        self.assertEqual(params["APPARENT"], "'AIRLESS'")


class ProviderTests(unittest.TestCase):
    def test_real_fixtures_and_provenance_checksums(self):
        for target in ("sun", "earth"):
            data = archive(target)
            self.assertEqual(
                hashlib.sha256(data["rawResponse"].encode()).hexdigest(), data["responseSha256"]
            )
            samples, headers, version = parse_response(data["rawResponse"], target)
            self.assertEqual(len(samples), 4)
            self.assertTrue(version)
            validate_observer(headers, SITE)
            with self.assertRaises(HorizonsError):
                validate_observer(headers, Site("other", "Other", -88, 0, 0, "Test"))

    def test_export_contract_and_exclusive_end(self):
        client = HorizonsClient()
        with patch.object(client, "fetch", side_effect=[archive("sun"), archive("earth")]):
            result = client.evaluate(SITE, PERIOD)
        self.assertEqual(len(result["series"]), 3)
        self.assertEqual(result["series"][-1]["t"], "2026-11-14T02:00:00Z")
        self.assertEqual(
            set(result["series"][0]),
            {
                "t",
                "sunAz",
                "sunEl",
                "earthAz",
                "earthEl",
                "sunAngularRadiusDeg",
                "earthAngularRadiusDeg",
            },
        )
        self.assertEqual(result["provenance"]["terrainModel"], "none")
        self.assertNotIn("sunLit", result["series"][0])
        self.assertNotIn("horizon", result)
        self.assertEqual(
            result["provenance"]["requests"][0]["retrievedAtUtc"], archive("sun")["retrievedAtUtc"]
        )

    def test_known_archived_angles(self):
        sun, _, _ = parse_response(archive("sun")["rawResponse"], "sun")
        earth, _, _ = parse_response(archive("earth")["rawResponse"], "earth")
        self.assertAlmostEqual(sun[PERIOD.start][0], 126.635106260, places=9)
        self.assertAlmostEqual(sun[PERIOD.start][1], 0.960002237, places=9)
        self.assertAlmostEqual(earth[PERIOD.start][0], 358.774106299, places=9)
        self.assertAlmostEqual(earth[PERIOD.start][1], -3.648805378, places=9)

    def test_does_not_fill_missing_earth_samples(self):
        sun, _, _ = parse_response(archive("sun")["rawResponse"], "sun")
        earth, _, _ = parse_response(archive("earth")["rawResponse"], "earth")
        earth.pop(PERIOD.start)
        with self.assertRaises(HorizonsError):
            merge_series(sun, earth, PERIOD.start, PERIOD.end, PERIOD.step)

    def test_provider_errors_and_wrong_target_fail(self):
        for raw in ['{"error":"test provider error"}', "{}", "not json"]:
            with self.subTest(raw=raw), self.assertRaises(HorizonsError):
                parse_response(raw, "sun")
        with self.assertRaises(HorizonsError):
            parse_response(archive("sun")["rawResponse"], "earth")

    def test_unavailable_nan_and_duplicate_rows_fail(self):
        data = json.loads(archive("sun")["rawResponse"])
        original = data["result"]
        table = original.split("$$SOE")[1].split("$$EOE")[0]
        row = next(line for line in table.splitlines() if line.strip())
        cells = row.split(",")
        for replacement in ("n.a.", "nan"):
            changed = cells.copy()
            changed[3] = replacement
            data["result"] = original.replace(row, ",".join(changed))
            with self.subTest(replacement=replacement), self.assertRaises(HorizonsError):
                parse_response(json.dumps(data), "sun")
        data["result"] = original.replace(row, row + "\n" + row)
        with self.assertRaises(HorizonsError):
            parse_response(json.dumps(data), "sun")

    def test_cache_reuse_is_offline(self):
        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        url = query_url(params)
        data = archive("sun") | {"sourceUrl": url}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (hashlib.sha256(url.encode()).hexdigest() + ".json")
            path.write_text(json.dumps(data))
            with patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                side_effect=AssertionError("Network forbidden"),
            ):
                self.assertEqual(HorizonsClient(Path(directory)).fetch(params), data)
            data["responseSha256"] = "invalid"
            path.write_text(json.dumps(data))
            with self.assertRaises(HorizonsError):
                HorizonsClient(Path(directory)).fetch(params)


if __name__ == "__main__":
    unittest.main()
