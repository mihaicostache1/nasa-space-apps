"""Sequential, bounded Horizons requests; no terrain or visibility inference."""

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Site, TimeRange, iso_utc

ENDPOINT = "https://ssd.jpl.nasa.gov/api/horizons.api"
TARGETS = {"sun": "10", "earth": "399"}
MONTHS = {name: index + 1 for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
)}


class HorizonsError(RuntimeError):
    """Provider output cannot be trusted or a request failed."""


def query_parameters(site: Site, target: str, start: datetime, end: datetime, step_minutes: int) -> dict:
    values = {
        "COMMAND": TARGETS[target], "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "OBSERVER", "CENTER": "coord@301", "COORD_TYPE": "GEODETIC",
        "SITE_COORD": f"{site.lon},{site.lat},{site.altitude_km}",
        "START_TIME": start.strftime("%Y-%m-%d %H:%M"),
        "STOP_TIME": end.strftime("%Y-%m-%d %H:%M"),
        "STEP_SIZE": f"{step_minutes} min", "QUANTITIES": "4", "CSV_FORMAT": "YES",
        "TIME_TYPE": "UT", "TIME_DIGITS": "SECONDS", "TIME_ZONE": "+00:00",
        "CAL_TYPE": "GREGORIAN", "APPARENT": "AIRLESS", "EXTRA_PREC": "YES",
        "ELEV_CUT": "-90", "SKIP_DAYLT": "NO",
    }
    return {"format": "json", **{key: f"'{value}'" for key, value in values.items()}}


def query_url(parameters: dict) -> str:
    return ENDPOINT + "?" + urlencode(parameters)


def parse_response(raw: str, target: str) -> tuple[dict, dict, str]:
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

    samples = {}
    previous = None
    for row in csv.reader(io.StringIO(table)):
        if not row or not any(item.strip() for item in row):
            continue
        try:
            match = re.fullmatch(r"(\d{4})-([A-Za-z]{3})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", row[0].strip())
            if match is None:
                raise ValueError("Unexpected timestamp format.")
            year, month, day, hour, minute, second = match.groups()
            timestamp = datetime(int(year), MONTHS[month], int(day), int(hour), int(minute), int(second), tzinfo=timezone.utc)
            az, el = float(row[az_index]), float(row[el_index])
            if not math.isfinite(az) or not math.isfinite(el) or not 0 <= az <= 360 or not -90 <= el <= 90:
                raise ValueError("Invalid angle.")
            az %= 360
            if previous is not None and timestamp <= previous:
                raise ValueError("Duplicate or unsorted timestamps.")
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
    if abs(lon_difference) > 0.0001 or abs(lat - site.lat) > 0.0001 or abs(altitude - site.altitude_km) > 0.0001:
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
    return [{"t": iso_utc(t), "sunAz": sun[t][0], "sunEl": sun[t][1], "earthAz": earth[t][0], "earthEl": earth[t][1]} for t in expected]


class HorizonsClient:
    def __init__(self, cache_dir: Path | None = None, *, refresh: bool = False, timeout: float = 40):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.timeout = timeout

    def fetch(self, parameters: dict) -> dict:
        url = query_url(parameters)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists() and not self.refresh:
            try:
                cached = json.loads(path.read_text())
                if cached["sourceUrl"] != url or hashlib.sha256(cached["rawResponse"].encode()).hexdigest() != cached["responseSha256"]:
                    raise ValueError("Cache integrity mismatch.")
                return cached
            except (ValueError, KeyError, TypeError) as exc:
                raise HorizonsError(f"Invalid cache entry {path}; rerun with --refresh.") from exc
        for attempt in range(3):
            try:
                request = Request(url, headers={"User-Agent": "LunarWindow-Ephemeris/0.1"})
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                break
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise HorizonsError(f"Horizons HTTP {exc.code}.") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise HorizonsError(f"Horizons request failed: {exc}") from exc
            time.sleep(2 ** attempt)
        return {
            "sourceUrl": url, "retrievedAtUtc": iso_utc(datetime.now(timezone.utc)),
            "responseSha256": hashlib.sha256(raw.encode()).hexdigest(), "rawResponse": raw,
        }

    def evaluate(self, site: Site, period: TimeRange) -> dict:
        series, requests = [], []
        model = None
        for start, end in period.chunks():
            bodies = {}
            for target in TARGETS:
                params = query_parameters(site, target, start, end, period.step_minutes)
                archive = self.fetch(params)
                samples, headers, version = parse_response(archive["rawResponse"], target)
                validate_observer(headers, site)
                current_model = (headers["Center pole/equ"], headers["Center radii"])
                if model is not None and model != current_model:
                    raise HorizonsError("Observer reference model changed between requests.")
                model = current_model
                bodies[target] = samples
                requests.append({key: value for key, value in archive.items() if key != "rawResponse"} | {
                    "target": target, "apiVersion": version, "modelHeader": headers,
                })
                # Cache only responses that passed parsing and observer checks.
                if self.cache_dir:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    key = hashlib.sha256(archive["sourceUrl"].encode()).hexdigest()
                    path = self.cache_dir / f"{key}.json"
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(archive, indent=2) + "\n")
                    temporary.replace(path)
            series.extend(merge_series(bodies["sun"], bodies["earth"], start, end, period.step))
        return {
            "schemaVersion": "lunarwindow.ephemeris.v1",
            "siteId": site.site_id, "site": site.name, "lat": site.lat, "lon": site.lon,
            "altitudeKm": site.altitude_km, "coordinateSource": site.coordinate_source,
            "series": series,
            "provenance": {
                "provider": "NASA/JPL Horizons", "observerCenter": "coord@301",
                "coordinateType": "GEODETIC", "longitudeConvention": "east-positive",
                "timeScale": "UTC", "startUtc": iso_utc(period.start), "endUtc": iso_utc(period.end),
                "endExclusive": True, "stepMinutes": period.step_minutes,
                "terrainModel": "none", "positionType": "airless-apparent-body-center",
                "requests": requests,
            },
        }
