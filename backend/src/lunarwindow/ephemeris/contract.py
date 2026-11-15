"""JSON Schema plus semantic checks at the backend handoff boundary."""

import argparse
import csv
import hashlib
import json
import math
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .horizons import HorizonsError, validate_observer
from .models import Site, TimeRange, iso_utc

_VALIDATED: ContextVar[set[bytes] | None] = ContextVar("ephemeris_validation_session", default=None)


@contextmanager
def validation_session():
    """Reuse successful validation of identical JSON within one operation only.

    No datasets or file snapshots are retained. Callers still read/hash sources
    and check manifests on every lookup. Nested calls share the current operation;
    the fingerprints are discarded on return or failure, including HTTP errors.
    """
    if _VALIDATED.get() is not None:
        yield
        return
    token = _VALIDATED.set(set())
    try:
        yield
    finally:
        _VALIDATED.reset(token)


def _plain_json(value) -> bool:
    # JSON encoders coerce tuples to lists and non-string dict keys to strings.
    # Those values have different schema semantics and must never share a cache hit.
    if type(value) in (str, int, float, bool, type(None)):
        return True
    if type(value) is list:
        return all(_plain_json(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _plain_json(item) for key, item in value.items())
    return False


def dataset_schema() -> dict:
    return json.loads(
        files(__package__).joinpath("ephemeris.schema.json").read_text(encoding="utf-8")
    )


def validate_dataset(dataset: dict) -> dict:
    validated = _VALIDATED.get()
    fingerprint = None
    if validated is not None and _plain_json(dataset):
        try:
            fingerprint = hashlib.sha256(
                json.dumps(dataset, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).digest()
        except ValueError:
            pass  # Non-finite values still go through the existing validation path.
        if fingerprint is not None and fingerprint in validated:
            return dataset
    try:
        Draft202012Validator(dataset_schema(), format_checker=FormatChecker()).validate(dataset)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid ephemeris contract at {list(exc.absolute_path)}: {exc.message}"
        ) from exc
    site = Site(
        dataset["siteId"],
        dataset["site"],
        dataset["lat"],
        dataset["lon"],
        dataset["altitudeKm"],
        dataset["coordinateSource"],
    )
    provenance = dataset["provenance"]
    period = TimeRange(provenance["startUtc"], provenance["endUtc"], provenance["stepMinutes"])
    if len(dataset["series"]) != period.sample_count:
        raise ValueError("Series length does not match the declared sampling grid.")
    for index, row in enumerate(dataset["series"]):
        if row["t"] != iso_utc(period.start + period.step * index):
            raise ValueError(f"Missing, duplicate, or off-grid sample at index {index}.")
        if not all(math.isfinite(value) for key, value in row.items() if key != "t"):
            raise ValueError("Non-finite ephemeris value.")
    requests = provenance["requests"]
    try:
        for request in requests:
            validate_observer(request["modelHeader"], site)
    except HorizonsError as exc:
        raise ValueError("Provenance observer differs from dataset coordinates.") from exc
    if {request["target"] for request in requests} != {"sun", "earth"}:
        raise ValueError("Provenance must include both Sun and Earth requests.")
    models = {
        (r["modelHeader"]["Center pole/equ"], r["modelHeader"]["Center radii"]) for r in requests
    }
    if len(models) != 1:
        raise ValueError("Inconsistent observer reference models in provenance.")
    if validated is not None and fingerprint is not None and len(validated) < 64:
        validated.add(fingerprint)
    return dataset


def verify_run(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != "lunarwindow.run.v1":
        raise ValueError("Unsupported run manifest version.")
    if manifest.get("status") != "complete" or not manifest.get("datasets"):
        raise ValueError("Only complete, nonempty run manifests are consumable.")
    if len({item["siteId"] for item in manifest["datasets"]}) != len(manifest["datasets"]):
        raise ValueError("Run manifests must contain unique site IDs.")
    for item in manifest["datasets"]:
        for key in ("json", "csv"):
            filename = item[key]
            if Path(filename).name != filename:
                raise ValueError("Manifest filenames must be relative basenames.")
            path = directory / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != item[key + "Sha256"]:
                raise ValueError(f"Checksum mismatch: {filename}")
        dataset = validate_dataset(
            json.loads((directory / item["json"]).read_text(encoding="utf-8"))
        )
        if item["siteId"] != dataset["siteId"]:
            raise ValueError("Manifest and dataset site IDs differ.")
        if any(
            manifest["period"][key] != dataset["provenance"][key]
            for key in ("startUtc", "endUtc", "stepMinutes")
        ):
            raise ValueError("Manifest and dataset periods differ.")
        with (directory / item["csv"]).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != len(dataset["series"]) or item["samples"] != len(rows):
            raise ValueError("CSV/JSON/manifest row counts differ.")
        for csv_row, row in zip(rows, dataset["series"]):
            if set(csv_row) != set(row) or csv_row["t"] != row["t"]:
                raise ValueError("CSV and JSON sample fields differ.")
            if any(float(csv_row[key]) != value for key, value in row.items() if key != "t"):
                raise ValueError("CSV and JSON sample values differ.")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Dataset JSON or complete run directory")
    args = parser.parse_args()
    try:
        if args.path.is_dir():
            result = verify_run(args.path)
            print(f"Validated complete run: {len(result['datasets'])} datasets")
        else:
            result = validate_dataset(json.loads(args.path.read_text(encoding="utf-8")))
            print(f"Validated {result['siteId']}: {len(result['series'])} samples")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
