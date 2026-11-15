"""Custom acquisition exercises real HTTP/parsing/archive paths with controlled NASA fixtures."""

import hashlib
import io
import json
import re
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from lunarwindow.ephemeris.custom import (
    CustomArchiveError,
    CustomEphemerisTimeout,
    CustomEphemerisUnavailable,
    acquire_custom_ephemeris,
)
from lunarwindow.ephemeris.horizons import (
    HorizonsClient,
    HorizonsError,
    HorizonsTimeoutError,
    query_parameters,
)
from lunarwindow.ephemeris.models import Site, TimeRange
from lunarwindow.ephemeris.storage import file_lock

FIXTURES = Path(__file__).parent / "fixtures"
SITE = Site("custom-fixture", "Custom fixture observer", -89.0, 0.0, 0.0, "Test input")
PERIOD = TimeRange("2026-11-14T00:00:00Z", "2026-11-14T03:00:00Z", 60)


def raw_fixture(target):
    return json.loads((FIXTURES / f"{target}.json").read_text())["rawResponse"]


def fixture_response(request, timeout):
    query = parse_qs(urlsplit(request.full_url).query)
    target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
    return io.BytesIO(raw_fixture(target).encode("utf-8"))


def synthetic_observer_response(request, timeout):
    """Only for request-identity tests: change fixture observer header, not production data."""
    query = parse_qs(urlsplit(request.full_url).query)
    target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
    envelope = json.loads(raw_fixture(target))
    coordinates = query["SITE_COORD"][0].strip("'")
    envelope["result"] = re.sub(
        r"Center geodetic\s*:[^\n]+",
        f"Center geodetic : {coordinates} {{E-lon(deg),Lat(deg),Alt(km)}}",
        envelope["result"],
    )
    return io.BytesIO(json.dumps(envelope).encode("utf-8"))


class CustomEphemerisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def acquire(self, site=SITE, **changes):
        return acquire_custom_ephemeris(
            site,
            PERIOD,
            archive_directory=self.root,
            timeout_seconds=changes.pop("timeout_seconds", 10),
            **changes,
        )

    def entries(self):
        return list(self.root.glob("*.json"))

    def test_fetch_archives_exact_observer_raw_evidence_and_reuses_without_network(self):
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response
        ) as request:
            result = self.acquire()
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(0 < call.kwargs["timeout"] <= 10 for call in request.call_args_list))
        self.assertEqual(len(result.dataset["series"]), 3)
        self.assertEqual(result.dataset["lat"], SITE.lat)
        self.assertEqual(result.dataset["lon"], SITE.lon)
        self.assertEqual(result.dataset["altitudeKm"], SITE.altitude_km)
        self.assertAlmostEqual(result.dataset["series"][0]["sunEl"], 0.960002237, places=9)
        entry = json.loads(self.entries()[0].read_bytes())
        self.assertEqual(entry["datasetSha256"], result.artifact_sha256)
        self.assertEqual(len(entry["rawResponses"]), 2)
        self.assertEqual(entry["rawResponses"][0]["rawResponse"], raw_fixture("sun"))
        self.assertEqual(entry["identity"]["site"]["lat"], SITE.lat)
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No network")
        ):
            replay = self.acquire()
        self.assertEqual(replay, result)
        # Caller mutations do not affect the archived snapshot.
        result.dataset["series"][0]["sunEl"] = 80
        self.assertNotEqual(result, self.acquire())

    def test_exact_coordinates_and_height_are_in_queries_and_archive_identity(self):
        observers = (
            SITE,
            Site("custom-fixture", SITE.name, -88.999999999, SITE.lon, 0.0, "Test input"),
            Site("custom-fixture", SITE.name, SITE.lat, 1.0, 0.0, "Test input"),
            Site("custom-fixture", SITE.name, SITE.lat, SITE.lon, 0.002, "Test input"),
        )
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=synthetic_observer_response
        ) as request:
            for site in observers:
                result = self.acquire(site)
                self.assertEqual(result.dataset["altitudeKm"], site.altitude_km)
                self.assertEqual(result.dataset["lat"], site.lat)
        self.assertEqual(request.call_count, 8)
        self.assertEqual(len(self.entries()), 4)
        coordinates = {
            parse_qs(urlsplit(call.args[0].full_url).query)["SITE_COORD"][0]
            for call in request.call_args_list
        }
        self.assertEqual(len(coordinates), 4)

    def test_corrupt_raw_dataset_identity_and_rehashed_dataset_fail_without_refresh(self):
        with patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response):
            self.acquire()
        path = self.entries()[0]
        original = path.read_bytes()
        for damage in ("raw", "dataset", "rehashed-dataset", "identity", "missing-raw", "json"):
            archive = json.loads(original)
            if damage == "raw":
                archive["rawResponses"][0]["rawResponse"] += "changed"
            elif damage in ("dataset", "rehashed-dataset"):
                archive["dataset"]["series"][0]["sunEl"] += 0.1
                if damage == "rehashed-dataset":
                    content = json.dumps(
                        archive["dataset"], sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()
                    archive["datasetSha256"] = hashlib.sha256(content).hexdigest()
            elif damage == "identity":
                archive["identity"]["site"]["lat"] += 0.1
            elif damage == "missing-raw":
                archive["rawResponses"].pop()
            path.write_text("{" if damage == "json" else json.dumps(archive), encoding="utf-8")
            with (
                self.subTest(damage=damage),
                patch(
                    "lunarwindow.ephemeris.horizons.urlopen",
                    side_effect=AssertionError("No refresh"),
                ),
                self.assertRaises(CustomArchiveError),
            ):
                self.acquire()
            path.write_bytes(original)

    def test_wrong_returned_observer_and_upstream_failure_do_not_publish_success(self):
        other = Site("other", "Other", -88, 10, 1, "Test")
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response),
            self.assertRaises(CustomEphemerisUnavailable),
        ):
            self.acquire(other)
        self.assertEqual(self.entries(), [])
        with (
            patch(
                "lunarwindow.ephemeris.horizons.urlopen", side_effect=URLError("failure")
            ) as request,
            self.assertRaises(CustomEphemerisUnavailable),
        ):
            self.acquire()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.entries(), [])

    def test_timeout_and_response_size_limits_fail_without_publishing(self):
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=TimeoutError("slow")),
            self.assertRaises(CustomEphemerisTimeout),
        ):
            self.acquire()
        with (
            patch("lunarwindow.ephemeris.custom.MAX_RESPONSE_BYTES", 100),
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response),
            self.assertRaises(CustomEphemerisUnavailable),
        ):
            self.acquire()
        self.assertEqual(self.entries(), [])

    def test_archive_count_and_byte_limits_evict_oldest_complete_entries(self):
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=synthetic_observer_response
        ):
            first = self.acquire(max_archive_entries=1)
            second_site = Site("second", "Second", -88, 1, 0, "Test")
            second = self.acquire(second_site, max_archive_entries=1)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(
            json.loads(self.entries()[0].read_bytes())["datasetSha256"], second.artifact_sha256
        )
        self.assertNotEqual(first.artifact_sha256, second.artifact_sha256)
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response),
            self.assertRaises(CustomArchiveError),
        ):
            self.acquire(max_archive_bytes=100)
        self.assertEqual(len(self.entries()), 1)

    def test_lowered_caps_are_enforced_even_on_an_offline_archive_hit(self):
        other = Site("second", "Second", -88, 1, 0, "Test")
        with patch(
            "lunarwindow.ephemeris.horizons.urlopen", side_effect=synthetic_observer_response
        ):
            self.acquire()
            self.acquire(other)
        self.assertEqual(len(self.entries()), 2)
        with patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("Offline")):
            result = self.acquire(other, max_archive_entries=1)
        self.assertEqual(result.dataset["siteId"], other.site_id)
        self.assertEqual(len(self.entries()), 1)

    def test_unsupported_frame_sphere_and_dynamical_model_are_rejected(self):
        replacements = (
            (r"Center pole/equ\s*:[^\n]+", "Center pole/equ : UNKNOWN_FRAME"),
            (r"Center radii\s*:[^\n]+", "Center radii : 1700, 1700, 1700 km"),
            (r"Center body name\s*:[^\n]+", "Center body name : Moon (301) {source: DE999}"),
        )
        for pattern, replacement in replacements:

            def respond(request, timeout):
                query = parse_qs(urlsplit(request.full_url).query)
                target = "sun" if query["COMMAND"] == ["'10'"] else "earth"
                envelope = json.loads(raw_fixture(target))
                envelope["result"] = re.sub(pattern, replacement, envelope["result"])
                return io.BytesIO(json.dumps(envelope).encode())

            with (
                self.subTest(replacement=replacement),
                patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=respond),
                self.assertRaises(CustomEphemerisUnavailable),
            ):
                self.acquire()
            self.assertEqual(self.entries(), [])

    def test_total_budget_includes_archive_lock_wait_without_network_calls(self):
        with (
            file_lock(self.root / "archive.lock"),
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No call")),
            self.assertRaises(CustomEphemerisTimeout),
        ):
            self.acquire(timeout_seconds=0.01)

    def test_simultaneous_identical_requests_share_one_acquisition(self):
        barrier = threading.Barrier(2)

        def acquire():
            barrier.wait()
            return self.acquire()

        with (
            patch(
                "lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response
            ) as request,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            tasks = [pool.submit(acquire), pool.submit(acquire)]
            results = [task.result(timeout=5) for task in tasks]
        self.assertEqual(results[0], results[1])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(self.entries()), 1)

    def test_symlink_entry_and_lock_are_rejected(self):
        with patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response):
            self.acquire()
        path = self.entries()[0]
        copied = self.root / "outside.json"
        copied.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(copied)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(CustomArchiveError):
            self.acquire()
        path.unlink()
        lock = self.root / "archive.lock"
        lock.unlink()
        lock.symlink_to(copied)
        with self.assertRaises(CustomArchiveError):
            self.acquire()


class HorizonsBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)

    def test_expired_budget_prevents_network_and_bounded_body_read_rejects_oversize(self):
        client = HorizonsClient(lock_dir=self.root, deadline_monotonic=time.monotonic() - 1)
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=AssertionError("No call")),
            self.assertRaises(HorizonsTimeoutError),
        ):
            client.fetch(self.params)
        client = HorizonsClient(lock_dir=self.root, max_attempts=1, max_response_bytes=100)
        with (
            patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=fixture_response),
            self.assertRaisesRegex(HorizonsError, "byte limit"),
        ):
            client.fetch(self.params)

    def test_slow_response_consumes_total_budget_without_retries(self):
        class SlowBody(io.BytesIO):
            def read1(self, size=-1):
                time.sleep(0.03)
                return super().read1(size)

        client = HorizonsClient(
            lock_dir=self.root,
            deadline_monotonic=time.monotonic() + 0.01,
            max_attempts=1,
            max_response_bytes=1024,
        )
        with (
            patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                return_value=SlowBody(raw_fixture("sun").encode()),
            ) as request,
            self.assertRaises(HorizonsTimeoutError),
        ):
            client.fetch(self.params)
        self.assertEqual(request.call_count, 1)
