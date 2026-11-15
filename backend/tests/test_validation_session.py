"""Validation reuse is bounded to identical JSON in one operation, never a file cache."""

import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from lunarwindow.ephemeris import contract

FIXTURE = Path(__file__).parent / "fixtures/dataset.json"


class ValidationSessionTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(FIXTURE.read_text())

    def test_equivalent_copies_share_success_but_not_mutable_objects(self):
        original = contract.Draft202012Validator
        with patch.object(contract, "Draft202012Validator", wraps=original) as validator:
            with contract.validation_session():
                first = contract.validate_dataset(self.dataset)
                second = copy.deepcopy(self.dataset)
                second = dict(reversed(list(second.items())))
                self.assertIs(contract.validate_dataset(second), second)
                self.assertIs(first, self.dataset)
                self.assertEqual(validator.call_count, 1)
            contract.validate_dataset(self.dataset)
            self.assertEqual(validator.call_count, 2)

    def test_changed_values_and_encoded_type_coercions_cannot_reuse_success(self):
        with contract.validation_session():
            contract.validate_dataset(self.dataset)
            for change in ("angle", "tuple", "observer", "nan"):
                bad = copy.deepcopy(self.dataset)
                if change == "angle":
                    bad["series"][0]["sunEl"] = 91
                elif change == "tuple":
                    bad["series"] = tuple(bad["series"])
                elif change == "observer":
                    bad["altitudeKm"] = 123
                else:
                    bad["series"][0]["sunEl"] = float("nan")
                with self.subTest(change=change), self.assertRaises(ValueError):
                    contract.validate_dataset(bad)
            self.assertIs(contract.validate_dataset(self.dataset), self.dataset)

    def test_mutation_invalidates_a_previously_validated_instance(self):
        with contract.validation_session():
            contract.validate_dataset(self.dataset)
            self.dataset["series"][0]["t"] = "2026-11-14T00:01:00Z"
            with self.assertRaises(ValueError):
                contract.validate_dataset(self.dataset)

    def test_nested_sessions_share_and_exception_exit_discards_fingerprints(self):
        original = contract.Draft202012Validator
        with patch.object(contract, "Draft202012Validator", wraps=original) as validator:
            with self.assertRaisesRegex(RuntimeError, "end operation"):
                with contract.validation_session():
                    contract.validate_dataset(self.dataset)
                    with contract.validation_session():
                        contract.validate_dataset(copy.deepcopy(self.dataset))
                    self.assertEqual(validator.call_count, 1)
                    raise RuntimeError("end operation")
            with contract.validation_session():
                contract.validate_dataset(self.dataset)
            self.assertEqual(validator.call_count, 2)

    def test_failures_are_not_remembered_as_successes(self):
        self.dataset["series"][0]["sunEl"] = 91
        original = contract.Draft202012Validator
        with patch.object(contract, "Draft202012Validator", wraps=original) as validator:
            with contract.validation_session():
                for _ in range(2):
                    with self.assertRaises(ValueError):
                        contract.validate_dataset(self.dataset)
            self.assertEqual(validator.call_count, 2)

    def test_parallel_operations_have_independent_fingerprints(self):
        barrier = Barrier(2)
        original = contract.Draft202012Validator

        def work(_):
            with contract.validation_session():
                contract.validate_dataset(copy.deepcopy(self.dataset))
                barrier.wait(timeout=5)
                contract.validate_dataset(copy.deepcopy(self.dataset))

        with patch.object(contract, "Draft202012Validator", wraps=original) as validator:
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(work, range(2)))
            self.assertEqual(validator.call_count, 2)

    def test_fingerprint_retention_is_bounded_without_skipping_new_checks(self):
        original = contract.Draft202012Validator
        with patch.object(contract, "Draft202012Validator", wraps=original) as validator:
            with contract.validation_session():
                for index in range(65):
                    value = copy.deepcopy(self.dataset)
                    value["coordinateSource"] += f"; review {index}"
                    contract.validate_dataset(value)
                # The 65th valid value was not retained, so it is checked again.
                contract.validate_dataset(copy.deepcopy(value))
            self.assertEqual(validator.call_count, 66)
