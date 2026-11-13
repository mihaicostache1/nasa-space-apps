"""Sequential, bounded Horizons requests; no terrain or visibility inference."""

import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Site, TimeRange, iso_utc
from .storage import atomic_write, file_lock

ENDPOINT = "https://ssd.jpl.nasa.gov/api/horizons.api"
TARGETS = {"sun": "10", "earth": "399"}
SUPPORTED_API_VERSIONS = {"1.2", "1.3"}
USER_AGENT = (
    "LunarWindow-Ephemeris/0.2.0 (+https://github.com/mihaicostache1/nasa-space-apps/issues)"
)
MONTHS = {
    name: index + 1
    for index, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    )
}


class HorizonsError(RuntimeError):
    """Provider output cannot be trusted or a request failed."""


def query_parameters(
    site: Site, target: str, start: datetime, end: datetime, step_minutes: int
) -> dict:
    values = {
        "COMMAND": TARGETS[target],
        "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "OBSERVER",
        "CENTER": "coord@301",
        "COORD_TYPE": "GEODETIC",
        "SITE_COORD": f"{site.lon},{site.lat},{site.altitude_km}",
        "START_TIME": start.strftime("%Y-%m-%d %H:%M"),
        "STOP_TIME": end.strftime("%Y-%m-%d %H:%M"),
        "STEP_SIZE": f"{step_minutes} min",
        "QUANTITIES": "4,13",
        "CSV_FORMAT": "YES",
        "TIME_TYPE": "UT",
        "TIME_DIGITS": "SECONDS",
        "TIME_ZONE": "+00:00",
        "CAL_TYPE": "GREGORIAN",
        "APPARENT": "AIRLESS",
        "EXTRA_PREC": "YES",
        "ELEV_CUT": "-90",
        "SKIP_DAYLT": "NO",
    }
    return {"format": "json", **{key: f"'{value}'" for key, value in values.items()}}


def query_url(parameters: dict) -> str:
    return ENDPOINT + "?" + urlencode(parameters)


def parse_response(
    raw: str, target: str, *, require_diameter: bool = False
) -> tuple[dict, dict, str]:
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("Expected a JSON object.")
        if envelope.get("error"):
            raise ValueError(str(envelope["error"]))
        result = envelope["result"]
        version = envelope["signature"]["version"]
        if not isinstance(result, str) or not isinstance(version, str):
            raise ValueError("Missing result text or API version.")
        if version not in SUPPORTED_API_VERSIONS:
            raise ValueError(
                f"Unsupported Horizons API version {version}; review the provider format before upgrading."
            )
        if envelope["signature"].get("source") != "NASA/JPL Horizons API":
            raise ValueError("Unexpected API signature source.")
    except (ValueError, KeyError, TypeError) as exc:
        raise HorizonsError(f"Invalid Horizons response: {exc}") from exc

    if result.count("$$SOE") != 1 or result.count("$$EOE") != 1:
        raise HorizonsError("Expected one complete Horizons ephemeris table.")
    before, remainder = result.split("$$SOE")
    if "$$EOE" not in remainder:
        raise HorizonsError("Ephemeris table markers are out of order.")
    table, _ = remainder.split("$$EOE")
    headers = {}
    for line in before.splitlines():
        match = re.match(r"^([A-Za-z][^:]*?)\s*:\s*(.+)$", line)
        if match:
            headers[match[1].strip()] = match[2].strip()
    if not re.search(rf"\({TARGETS[target]}\)", headers.get("Target body name", "")):
        raise HorizonsError("Horizons returned the wrong target body.")
    if not re.search(r"\(301\)", headers.get("Center body name", "")):
        raise HorizonsError("Horizons did not use the Moon as observer center.")
    if headers.get("Atmos refraction") != "NO (AIRLESS)":
        raise HorizonsError("Expected airless apparent positions.")
    for required in ("Center geodetic", "Center pole/equ", "Center radii"):
        if required not in headers:
            raise HorizonsError(f"Missing model header: {required}.")
    column_lines = [line for line in before.splitlines() if "Date__(UT)" in line and "," in line]
    if len(column_lines) != 1:
        raise HorizonsError("Missing unambiguous UT CSV column header.")
    columns = [value.strip() for value in next(csv.reader(column_lines))]
    try:
        az_index = columns.index("Azimuth_(a-app)")
        el_index = columns.index("Elevation_(a-app)")
    except ValueError as exc:
        raise HorizonsError("Missing airless azimuth/elevation columns.") from exc
    diameter_index = columns.index("Ang-diam") if "Ang-diam" in columns else None
    if require_diameter and diameter_index is None:
        raise HorizonsError("Missing requested angular diameter column.")

    samples = {}
    previous = None
    for row in csv.reader(io.StringIO(table)):
        if not row or not any(item.strip() for item in row):
            continue
        try:
            match = re.fullmatch(
                r"(\d{4})-([A-Za-z]{3})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", row[0].strip()
            )
            if match is None:
                raise ValueError("Unexpected timestamp format.")
            year, month, day, hour, minute, second = match.groups()
            timestamp = datetime(
                int(year),
                MONTHS[month],
                int(day),
                int(hour),
                int(minute),
                int(second),
                tzinfo=timezone.utc,
            )
            az, el = float(row[az_index]), float(row[el_index])
            if (
                not math.isfinite(az)
                or not math.isfinite(el)
                or not 0 <= az <= 360
                or not -90 <= el <= 90
            ):
                raise ValueError("Invalid angle.")
            az %= 360
            if previous is not None and timestamp <= previous:
                raise ValueError("Duplicate or unsorted timestamps.")
            if diameter_index is not None:
                diameter = float(row[diameter_index])
                if not math.isfinite(diameter) or not 0 < diameter < 180 * 3600:
                    raise ValueError("Invalid angular diameter.")
                samples[timestamp] = (az, el, diameter / 7200)
            else:
                samples[timestamp] = (az, el)
            previous = timestamp
        except (ValueError, KeyError, IndexError) as exc:
            raise HorizonsError(f"Invalid ephemeris row: {row}") from exc
    if not samples:
        raise HorizonsError("Horizons returned no samples.")
    return samples, headers, version


def validate_observer(headers: dict, site: Site) -> None:
    try:
        values = headers["Center geodetic"].split("{")[0].split(",")
        lon, lat, altitude = (float(value.strip()) for value in values)
        if not all(math.isfinite(value) for value in (lon, lat, altitude)):
            raise ValueError("Non-finite observer coordinate.")
    except (ValueError, KeyError) as exc:
        raise HorizonsError("Cannot verify observer coordinates.") from exc
    lon_difference = (lon - site.lon + 180) % 360 - 180
    if (
        abs(lon_difference) > 0.0001
        or abs(lat - site.lat) > 0.0001
        or abs(altitude - site.altitude_km) > 0.0001
    ):
        raise HorizonsError("Returned observer coordinates differ from the requested site.")


def merge_series(sun: dict, earth: dict, start: datetime, end: datetime, step) -> list[dict]:
    # Horizons includes STOP_TIME when aligned; our export is [start, end).
    sun = {key: value for key, value in sun.items() if start <= key < end}
    earth = {key: value for key, value in earth.items() if start <= key < end}
    expected = []
    current = start
    while current < end:
        expected.append(current)
        current += step
    if set(sun) != set(expected) or set(earth) != set(expected):
        raise HorizonsError("Missing or misaligned Sun/Earth samples; refusing to fill gaps.")
    result = []
    for t in expected:
        row = {
            "t": iso_utc(t),
            "sunAz": sun[t][0],
            "sunEl": sun[t][1],
            "earthAz": earth[t][0],
            "earthEl": earth[t][1],
        }
        if len(sun[t]) == 3 and len(earth[t]) == 3:
            row.update(sunAngularRadiusDeg=sun[t][2], earthAngularRadiusDeg=earth[t][2])
        elif len(sun[t]) != len(earth[t]):
            raise HorizonsError("Inconsistent body-size columns.")
        result.append(row)
    return result


def retry_delay(value: str | None, fallback: float, *, maximum: float = 60) -> float:
    """Never retry earlier than a valid Retry-After; fail rather than truncate it."""
    delay = fallback
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = fallback
    if not math.isfinite(delay):
        delay = fallback
    delay = max(0, delay)
    if delay > maximum:
        raise HorizonsError(
            f"Provider requested Retry-After {delay:.0f}s; resume later (automatic wait limit {maximum:.0f}s)."
        )
    return delay


class HorizonsClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        refresh: bool = False,
        timeout: float = 40,
        lock_dir: Path | None = None,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite.")
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.timeout = timeout
        self.lock_dir = lock_dir or Path(
            os.environ.get(
                "LUNARWINDOW_LOCK_DIR", str(Path(tempfile.gettempdir()) / "lunarwindow-locks")
            )
        )

    def fetch(self, parameters: dict) -> dict:
        # All cooperating processes must use the same lock directory.
        with file_lock(self.lock_dir / "horizons-request.lock"):
            if self.cache_dir:
                key = hashlib.sha256(query_url(parameters).encode()).hexdigest()
                with file_lock(self.cache_dir / ".locks" / f"{key}.lock"):
                    return self._fetch_locked(parameters)
            return self._fetch_locked(parameters)

    def _validate_archive(self, archive: dict, parameters: dict) -> None:
        if not isinstance(archive, dict) or not all(
            isinstance(archive.get(key), str)
            for key in ("rawResponse", "sourceUrl", "responseSha256", "retrievedAtUtc")
        ):
            raise ValueError("Malformed cache metadata.")
        raw = archive["rawResponse"]
        if (
            archive["sourceUrl"] != query_url(parameters)
            or hashlib.sha256(raw.encode()).hexdigest() != archive["responseSha256"]
        ):
            raise ValueError("Cache integrity mismatch.")
        if not archive["retrievedAtUtc"].endswith("Z"):
            raise ValueError("Retrieval timestamp must end in Z.")
        retrieved = datetime.fromisoformat(archive["retrievedAtUtc"].replace("Z", "+00:00"))
        if retrieved.utcoffset() != timezone.utc.utcoffset(retrieved):
            raise ValueError("Invalid retrieval timestamp.")
        target = next(
            name for name, code in TARGETS.items() if parameters["COMMAND"] == f"'{code}'"
        )
        _, headers, _ = parse_response(raw, target, require_diameter=True)
        lon, lat, altitude = map(float, parameters["SITE_COORD"].strip("'").split(","))
        validate_observer(
            headers, Site("request", "Requested observer", lat, lon, altitude, "Request")
        )

    def _fetch_locked(self, parameters: dict) -> dict:
        url = query_url(parameters)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists() and not self.refresh:
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                self._validate_archive(cached, parameters)
                return cached
            except (ValueError, KeyError, TypeError, HorizonsError) as exc:
                raise HorizonsError(f"Invalid cache entry {path}; rerun with --refresh.") from exc
        for attempt in range(3):
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                break
            except HTTPError as exc:
                try:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise HorizonsError(f"Horizons HTTP {exc.code}.") from exc
                    delay = retry_delay(
                        exc.headers.get("Retry-After") if exc.headers else None, 2**attempt
                    )
                finally:
                    exc.close()
            except (URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
                if attempt == 2:
                    raise HorizonsError(f"Horizons request failed: {exc}") from exc
                delay = 2**attempt
            time.sleep(delay)
        archive = {
            "sourceUrl": url,
            "retrievedAtUtc": iso_utc(datetime.now(timezone.utc)),
            "responseSha256": hashlib.sha256(raw.encode()).hexdigest(),
            "rawResponse": raw,
        }
        self._validate_archive(archive, parameters)
        if path:
            atomic_write(path, json.dumps(archive, indent=2) + "\n")
        return archive

    def evaluate(self, site: Site, period: TimeRange) -> dict:
        series, requests = [], []
        model = None
        for start, end in period.chunks():
            bodies = {}
            for target in TARGETS:
                params = query_parameters(site, target, start, end, period.step_minutes)
                archive = self.fetch(params)
                samples, headers, version = parse_response(
                    archive["rawResponse"], target, require_diameter=True
                )
                validate_observer(headers, site)
                current_model = (headers["Center pole/equ"], headers["Center radii"])
                if model is not None and model != current_model:
                    raise HorizonsError("Observer reference model changed between requests.")
                model = current_model
                bodies[target] = samples
                requests.append(
                    {key: value for key, value in archive.items() if key != "rawResponse"}
                    | {
                        "target": target,
                        "apiVersion": version,
                        "modelHeader": headers,
                    }
                )
            series.extend(merge_series(bodies["sun"], bodies["earth"], start, end, period.step))
        return {
            "schemaVersion": "lunarwindow.ephemeris.v2",
            "siteId": site.site_id,
            "site": site.name,
            "lat": site.lat,
            "lon": site.lon,
            "altitudeKm": site.altitude_km,
            "coordinateSource": site.coordinate_source,
            "series": series,
            "provenance": {
                "provider": "NASA/JPL Horizons",
                "observerCenter": "coord@301",
                "coordinateType": "GEODETIC",
                "longitudeConvention": "east-positive",
                "timeScale": "UTC",
                "startUtc": iso_utc(period.start),
                "endUtc": iso_utc(period.end),
                "endExclusive": True,
                "stepMinutes": period.step_minutes,
                "terrainModel": "none",
                "positionType": "airless-apparent-body-center",
                "quantities": [4, 13],
                "angularSizeModel": "equatorial-radius",
                "requests": requests,
            },
        }
