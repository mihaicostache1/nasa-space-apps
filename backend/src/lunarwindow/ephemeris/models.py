"""Coordinate and time contracts shared by the CLI and a future FastAPI service."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z", value):
        raise ValueError("Times must be ISO 8601 UTC strings ending in Z.")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"Invalid UTC time: {value}") from exc
    if result.second or result.microsecond:
        raise ValueError("Use whole-minute timestamps.")
    if result.year < 1962:
        raise ValueError("This UTC exporter supports dates from 1962 onward.")
    return result.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    return float(value)


@dataclass(frozen=True)
class Site:
    site_id: str
    name: str
    lat: float
    lon: float
    altitude_km: float
    coordinate_source: str

    def __post_init__(self) -> None:
        if not isinstance(self.site_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.site_id):
            raise ValueError("site_id must be a lowercase filename-safe slug.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("A site name is required.")
        if not -90 <= finite_number(self.lat, "Latitude") <= 90:
            raise ValueError("Latitude must be in [-90, 90].")
        if not -180 <= finite_number(self.lon, "Longitude") <= 180:
            raise ValueError("Longitude must be east-positive in [-180, 180].")
        finite_number(self.altitude_km, "Altitude in km")
        if not isinstance(self.coordinate_source, str) or not self.coordinate_source.strip():
            raise ValueError("coordinate_source is required, including for illustrative points.")


@dataclass(frozen=True)
class TimeRange:
    start_utc: str
    end_utc: str
    step_minutes: int = 60

    def __post_init__(self) -> None:
        if isinstance(self.step_minutes, bool) or not isinstance(self.step_minutes, int) or not 1 <= self.step_minutes <= 1440:
            raise ValueError("step_minutes must be an integer in [1, 1440].")
        if self.end <= self.start:
            raise ValueError("End must follow start.")
        if self.sample_count > 200_000:
            raise ValueError("At most 200,000 samples per export; shorten the interval or increase the step.")

    @property
    def start(self) -> datetime:
        return parse_utc(self.start_utc)

    @property
    def end(self) -> datetime:
        return parse_utc(self.end_utc)

    @property
    def step(self) -> timedelta:
        return timedelta(minutes=self.step_minutes)

    @property
    def sample_count(self) -> int:
        return math.ceil((self.end - self.start) / self.step)

    def chunks(self):
        """Bound requests to 30 days and at most 744 output intervals."""
        span = min(timedelta(days=30), self.step * 744)
        # Keep all chunk starts on the original sampling grid.
        intervals = max(1, span // self.step)
        current = self.start
        while current < self.end:
            end = min(current + intervals * self.step, self.end)
            yield current, end
            current = end
