"""Failure, concurrency, contract, and batch-boundary regressions."""

import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from lunarwindow.ephemeris import HorizonsClient, HorizonsError, Site, TimeRange
from lunarwindow.ephemeris.contract import validate_dataset, verify_run
from lunarwindow.ephemeris.export import export_run
from lunarwindow.ephemeris.horizons import parse_response, query_parameters, retry_delay
from lunarwindow.ephemeris.models import iso_utc
from lunarwindow.ephemeris.storage import atomic_write, file_lock

FIXTURES = Path(__file__).parent / "fixtures"
SITE = Site("polar-example", "Illustrative polar point", -89.0, 0.0, 0.0, "Test point")
PERIOD = TimeRange("2026-11-14T00:00Z", "2026-11-14T03:00Z")


def archive(target="sun"):
    return json.loads((FIXTURES / f"{target}.json").read_text(encoding="utf-8"))


def sample_dataset():
    return json.loads((FIXTURES / "dataset.json").read_text(encoding="utf-8"))


class RequestTests(unittest.TestCase):
    def test_retry_after_seconds_date_and_limits(self):
        self.assertEqual(retry_delay("7", 1), 7)
        self.assertEqual(retry_delay("broken", 2), 2)
        self.assertEqual(retry_delay("-3", 1), 0)
        future = datetime.now(timezone.utc) + timedelta(seconds=10)
        self.assertGreater(retry_delay(format_datetime(future), 1), 8)
        with self.assertRaises(HorizonsError):
            retry_delay("3600", 1)

    def test_http_throttle_respects_retry_after(self):
        headers = Message()
        headers["Retry-After"] = "7"
        error = HTTPError("https://example.test", 429, "Rate limited", headers, None)
        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            client = HorizonsClient(lock_dir=Path(directory))
            with (
                patch(
                    "lunarwindow.ephemeris.horizons.urlopen",
                    side_effect=[error, io.BytesIO(archive()["rawResponse"].encode())],
                ) as request,
                patch("lunarwindow.ephemeris.horizons.time.sleep") as sleep,
            ):
                client.fetch(params)
            sleep.assert_called_once_with(7)
            self.assertEqual(request.call_count, 2)
            user_agent = request.call_args.args[0].get_header("User-agent")
            self.assertIn("/issues", user_agent)

    def test_timeout_retries_are_bounded(self):
        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "lunarwindow.ephemeris.horizons.urlopen", side_effect=URLError("timeout")
                ) as request,
                patch("lunarwindow.ephemeris.horizons.time.sleep"),
            ):
                with self.assertRaises(HorizonsError):
                    HorizonsClient(lock_dir=Path(directory)).fetch(params)
            self.assertEqual(request.call_count, 3)

    def test_interrupted_retrieval_resumes_from_validated_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = HorizonsClient(root / "cache", lock_dir=root / "locks")
            first = [io.BytesIO(archive("sun")["rawResponse"].encode())] + [URLError("offline")] * 3
            with (
                patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=first),
                patch("lunarwindow.ephemeris.horizons.time.sleep"),
            ):
                with self.assertRaises(HorizonsError):
                    client.evaluate(SITE, PERIOD)
            with patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                return_value=io.BytesIO(archive("earth")["rawResponse"].encode()),
            ) as request:
                dataset = client.evaluate(SITE, PERIOD)
            self.assertEqual(request.call_count, 1)
            validate_dataset(dataset)

    def test_truncated_response_can_retry(self):
        from http.client import IncompleteRead

        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "lunarwindow.ephemeris.horizons.urlopen",
                    side_effect=[
                        IncompleteRead(b"partial"),
                        io.BytesIO(archive()["rawResponse"].encode()),
                    ],
                ) as request,
                patch("lunarwindow.ephemeris.horizons.time.sleep"),
            ):
                HorizonsClient(lock_dir=Path(directory)).fetch(params)
            self.assertEqual(request.call_count, 2)

    def test_nonretryable_error_is_not_repeated(self):
        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                side_effect=HTTPError("x", 400, "Bad request", None, None),
            ) as request:
                with self.assertRaises(HorizonsError):
                    HorizonsClient(lock_dir=Path(directory)).fetch(params)
            self.assertEqual(request.call_count, 1)

    def test_unknown_api_and_missing_diameter_fail(self):
        envelope = json.loads(archive()["rawResponse"])
        envelope["signature"]["version"] = "99.0"
        with self.assertRaises(HorizonsError):
            parse_response(json.dumps(envelope), "sun")
        envelope = json.loads(archive()["rawResponse"])
        envelope["result"] = envelope["result"].replace("Ang-diam", "Removed-column")
        with self.assertRaises(HorizonsError):
            parse_response(json.dumps(envelope), "sun", require_diameter=True)

    def test_invalid_response_is_never_cached(self):
        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "lunarwindow.ephemeris.horizons.urlopen",
                return_value=io.BytesIO(b'{"error":"bad request"}'),
            ):
                with self.assertRaises(HorizonsError):
                    HorizonsClient(root / "cache", lock_dir=root / "locks").fetch(params)
            self.assertFalse(list((root / "cache").glob("*.json")))

    def test_threads_share_request_lock(self):
        active = 0
        maximum = 0
        counter = threading.Lock()

        def response(*args, **kwargs):
            nonlocal active, maximum
            with counter:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.03)
            with counter:
                active -= 1
            return io.BytesIO(archive()["rawResponse"].encode())

        params = query_parameters(SITE, "sun", PERIOD.start, PERIOD.end, 60)
        with tempfile.TemporaryDirectory() as directory:
            with patch("lunarwindow.ephemeris.horizons.urlopen", side_effect=response):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(HorizonsClient(lock_dir=Path(directory)).fetch, params)
                        for _ in range(2)
                    ]
                    for future in futures:
                        future.result(timeout=5)
        self.assertEqual(maximum, 1)


class StorageTests(unittest.TestCase):
    def test_lock_excludes_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "process.lock"
            code = "from pathlib import Path; from lunarwindow.ephemeris.storage import file_lock; import sys\ntry:\n with file_lock(Path(sys.argv[1]), timeout=.1): pass\nexcept TimeoutError:\n sys.exit(7)"
            with file_lock(path):
                result = subprocess.run(
                    [sys.executable, "-c", code, str(path)], timeout=10, capture_output=True
                )
            self.assertEqual(result.returncode, 7, result.stderr.decode())
            with file_lock(path, timeout=0.1):
                pass

    def test_failed_atomic_replace_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            path.write_text("previous", encoding="utf-8")
            with patch.object(Path, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    atomic_write(path, "replacement")
            self.assertEqual(path.read_text(), "previous")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class HandoffTests(unittest.TestCase):
    def test_last_supported_calendar_day_does_not_overflow_chunking(self):
        period = TimeRange("9999-12-30T00:00Z", "9999-12-31T00:00Z", 60)
        self.assertEqual(list(period.chunks()), [(period.start, period.end)])

    def test_schema_and_semantics_reject_corruption(self):
        dataset = sample_dataset()
        validate_dataset(dataset)
        for change in (
            lambda d: d["series"][0].pop("earthAngularRadiusDeg"),
            lambda d: d["series"][0].update(sunAz=360),
            lambda d: d["series"][1].update(t=d["series"][0]["t"]),
            lambda d: d["provenance"].update(endExclusive=False),
        ):
            changed = deepcopy(dataset)
            change(changed)
            with self.assertRaises(ValueError):
                validate_dataset(changed)

    def test_export_runs_are_immutable_and_consumable(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HorizonsClient()
            with patch.object(client, "evaluate", return_value=sample_dataset()):
                first = export_run(client, [SITE], PERIOD, Path(directory))
                second = export_run(client, [SITE], PERIOD, Path(directory))
            self.assertNotEqual(first, second)
            self.assertEqual(verify_run(first)["status"], "complete")
            self.assertEqual(verify_run(second)["datasets"][0]["samples"], 3)
            (first / "polar-example.csv").write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_run(first)

    def test_manifest_period_must_match_its_datasets(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HorizonsClient()
            with patch.object(client, "evaluate", return_value=sample_dataset()):
                run = export_run(client, [SITE], PERIOD, Path(directory))
            path = run / "manifest.json"
            manifest = json.loads(path.read_text())
            manifest["period"]["stepMinutes"] = 15
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_run(run)

    def test_interrupted_batch_publishes_no_partial_run(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HorizonsClient()
            with patch.object(
                client,
                "evaluate",
                side_effect=[sample_dataset(), HorizonsError("upstream failure")],
            ):
                with self.assertRaises(HorizonsError):
                    export_run(
                        client, [SITE, replace(SITE, site_id="second")], PERIOD, Path(directory)
                    )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_full_multi_chunk_export_has_no_duplicate_boundary(self):
        # Synthetic angles isolate scheduling, including leap day and year boundaries.
        # Scientific reference angles are tested separately against archived NASA data.
        for start, end in [
            ("2028-02-28T00:00Z", "2028-04-01T00:00Z"),
            ("2026-12-31T23:00Z", "2027-02-02T02:17Z"),
        ]:
            period = TimeRange(start, end, 137)
            client = HorizonsClient()

            def fetch(parameters):
                target = "sun" if parameters["COMMAND"] == "'10'" else "earth"
                body = json.loads(archive(target)["rawResponse"])
                a = datetime.strptime(
                    parameters["START_TIME"].strip("'"), "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)
                b = datetime.strptime(parameters["STOP_TIME"].strip("'"), "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc
                )
                lines = []
                current = a
                months = [
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ]
                while current <= b:
                    date = f"{current.year:04}-{months[current.month - 1]}-{current.day:02} {current:%H:%M:%S}"
                    lines.append(f" {date},*, ,120,1,1900,")
                    current += period.step
                before, rest = body["result"].split("$$SOE")
                _, after = rest.split("$$EOE")
                body["result"] = before + "$$SOE\n" + "\n".join(lines) + "\n$$EOE" + after
                return archive(target) | {"rawResponse": json.dumps(body)}

            with patch.object(client, "fetch", side_effect=fetch):
                dataset = client.evaluate(SITE, period)
            self.assertEqual(len(dataset["series"]), period.sample_count)
            self.assertEqual(len({r["t"] for r in dataset["series"]}), period.sample_count)
            self.assertEqual(
                dataset["series"][-1]["t"],
                iso_utc(period.start + (period.sample_count - 1) * period.step),
            )

    def test_wrapped_longitude_observer_is_equivalent(self):
        from lunarwindow.ephemeris.horizons import validate_observer

        headers = {"Center geodetic": "355, -89, 0 {E-lon(deg),Lat(deg),Alt(km)}"}
        validate_observer(headers, Site("west", "West", -89, -5, 0, "Test"))


if __name__ == "__main__":
    unittest.main()
