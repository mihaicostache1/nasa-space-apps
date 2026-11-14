"""Bounded LRU behavior, immutable snapshots, and concurrent storage access."""

import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

from pydantic import ValidationError

from lunarwindow.api.reference_cache import ReferenceEvaluationCache
from lunarwindow.api.reference_cache_key import build_reference_evaluation_cache_key
from lunarwindow.api.reference_models import ReferenceEvaluationRequest


def cache_key(index: int):
    # Identity-only test hashes, with no claim about verified production data.
    return build_reference_evaluation_cache_key(
        ReferenceEvaluationRequest(
            siteId="lola-site01-reference",
            horizonMode="geometric",
            startUtc="2026-11-14T00:00:00Z",
            endUtc="2026-11-15T00:00:00Z",
        ),
        ephemeris_sha256=hashlib.sha256(str(index).encode("ascii")).hexdigest(),
    )


class ReferenceCacheTests(unittest.TestCase):
    def test_hits_misses_and_immutable_json_snapshots(self):
        cache = ReferenceEvaluationCache()
        key = cache_key(0)
        original = {"series": [{"sunLit": True}], "label": "Lună"}
        snapshot = json.dumps(original, ensure_ascii=False).encode("utf-8")
        self.assertIsNone(cache.get(key))
        self.assertTrue(cache.put(key, snapshot))
        original["series"][0]["sunLit"] = False
        returned = cache.get(cache_key(0))
        self.assertIsInstance(returned, bytes)
        decoded = json.loads(returned)
        self.assertTrue(decoded["series"][0]["sunLit"])
        decoded["series"].clear()
        self.assertEqual(cache.get(key), snapshot)
        self.assertIsNone(cache.get(cache_key(1)))
        self.assertEqual(cache.info().entry_count, 1)
        # Budget uses UTF-8 bytes, not characters or a mutable object estimate.
        self.assertEqual(cache.info().stored_bytes, len(snapshot))
        with self.assertRaises(FrozenInstanceError):
            cache.info().stored_bytes = 0

    def test_entry_limit_evicts_least_recently_read_key(self):
        cache = ReferenceEvaluationCache(max_entries=2, max_bytes=100)
        a, b, c = (cache_key(index) for index in range(3))
        cache.put(a, b"a")
        cache.put(b, b"b")
        self.assertEqual(cache.get(a), b"a")
        cache.put(c, b"c")
        self.assertIsNone(cache.get(b))
        self.assertEqual(cache.get(a), b"a")
        self.assertEqual(cache.get(c), b"c")
        self.assertEqual(cache.info().entry_count, 2)
        self.assertEqual(cache.info().stored_bytes, 2)

    def test_byte_limit_can_evict_multiple_entries_and_accepts_exact_boundary(self):
        cache = ReferenceEvaluationCache(max_entries=4, max_bytes=6)
        a, b, c, d = (cache_key(index) for index in range(4))
        for key in (a, b, c):
            self.assertTrue(cache.put(key, b"ab"))
        self.assertEqual(cache.info().stored_bytes, 6)
        self.assertTrue(cache.put(d, b"12345"))
        for key in (a, b, c):
            self.assertIsNone(cache.get(key))
        self.assertEqual(cache.get(d), b"12345")
        self.assertEqual(cache.info().entry_count, 1)
        self.assertEqual(cache.info().stored_bytes, 5)

    def test_replacement_frees_bytes_updates_recency_and_can_grow(self):
        cache = ReferenceEvaluationCache(max_entries=3, max_bytes=10)
        a, b, c = (cache_key(index) for index in range(3))
        cache.put(a, b"123456")
        cache.put(b, b"1234")
        self.assertTrue(cache.put(a, b"12"))
        self.assertEqual(cache.info().entry_count, 2)
        self.assertEqual(cache.info().stored_bytes, 6)
        cache.put(c, b"1234")
        # Order is b, a, c. Growing a removes its old bytes before eviction;
        # b alone frees enough space, retaining c and the new a.
        self.assertTrue(cache.put(a, b"123456"))
        self.assertIsNone(cache.get(b))
        self.assertEqual(cache.get(c), b"1234")
        self.assertEqual(cache.get(a), b"123456")
        self.assertEqual(cache.info().stored_bytes, 10)
        self.assertEqual(cache.info().entry_count, 2)

    def test_replacement_counts_as_recent_use_at_entry_limit(self):
        cache = ReferenceEvaluationCache(max_entries=2, max_bytes=100)
        a, b, c = (cache_key(index) for index in range(3))
        cache.put(a, b"old")
        cache.put(b, b"b")
        cache.put(a, b"new")
        cache.put(c, b"c")
        self.assertIsNone(cache.get(b))
        self.assertEqual(cache.get(a), b"new")
        self.assertEqual(cache.info().stored_bytes, 4)

    def test_oversized_put_preserves_existing_values_and_recency(self):
        cache = ReferenceEvaluationCache(max_entries=2, max_bytes=4)
        a, b, c = (cache_key(index) for index in range(3))
        cache.put(a, b"aa")
        cache.put(b, b"bb")
        self.assertFalse(cache.put(a, b"large"))
        self.assertFalse(cache.put(c, b"large"))
        self.assertEqual(cache.info().stored_bytes, 4)
        cache.put(c, b"cc")
        self.assertIsNone(cache.get(a))
        self.assertEqual(cache.get(b), b"bb")
        self.assertEqual(cache.get(c), b"cc")

    def test_invalid_limits_and_zero_capacity(self):
        for name in ("max_entries", "max_bytes"):
            for value in (-1, True, False, 1.5, "2", None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    ReferenceEvaluationCache(**{name: value})
            with self.subTest(disabled=name):
                cache = ReferenceEvaluationCache(**{name: 0})
                self.assertFalse(cache.put(cache_key(0), b""))
                self.assertFalse(cache.put(cache_key(0), b"value"))
                self.assertIsNone(cache.get(cache_key(0)))
                self.assertEqual(cache.info().entry_count, 0)
                self.assertEqual(cache.info().stored_bytes, 0)

    def test_empty_snapshot_is_a_hit_and_clear_resets_accounting(self):
        cache = ReferenceEvaluationCache(max_entries=1, max_bytes=1)
        a, b = cache_key(0), cache_key(1)
        self.assertTrue(cache.put(a, b""))
        self.assertEqual(cache.get(a), b"")
        self.assertTrue(cache.put(b, b"b"))
        self.assertIsNone(cache.get(a))
        cache.clear()
        cache.clear()
        self.assertIsNone(cache.get(b))
        self.assertEqual(cache.info().entry_count, 0)
        self.assertEqual(cache.info().stored_bytes, 0)
        self.assertTrue(cache.put(a, b"a"))
        self.assertEqual(cache.info().stored_bytes, 1)

    def test_invalid_keys_or_mutable_payloads_cannot_change_storage(self):
        cache = ReferenceEvaluationCache()
        key = cache_key(0)
        cache.put(key, b"valid")
        before = cache.info()
        for snapshot in ({"value": 1}, "text", bytearray(b"value"), memoryview(b"value"), None):
            with self.subTest(snapshot=snapshot), self.assertRaises(TypeError):
                cache.put(key, snapshot)
        bad_key = key.model_copy(update={"stepMinutes": 0})
        with self.assertRaises(ValidationError):
            cache.put(bad_key, b"invalid")
        with self.assertRaises(ValidationError):
            cache.get(bad_key)
        self.assertEqual(cache.info(), before)
        self.assertEqual(cache.get(key), b"valid")

    def test_concurrent_disjoint_writes_and_reads_keep_complete_snapshots(self):
        count = 8
        cache = ReferenceEvaluationCache(max_entries=count, max_bytes=1024)
        barrier = Barrier(count)
        snapshots = [f'{{"worker":{index}}}'.encode("ascii") for index in range(count)]

        def worker(index):
            key = cache_key(index)
            barrier.wait(timeout=10)
            self.assertTrue(cache.put(key, snapshots[index]))
            barrier.wait(timeout=10)
            self.assertEqual(cache.get(key), snapshots[index])
            self.assertEqual(cache.info().entry_count, count)
            self.assertEqual(cache.info().stored_bytes, sum(map(len, snapshots)))

        with ThreadPoolExecutor(max_workers=count) as executor:
            futures = [executor.submit(worker, index) for index in range(count)]
            for future in futures:
                future.result(timeout=15)

    def test_concurrent_replacements_evictions_and_clear_preserve_bounds(self):
        cache = ReferenceEvaluationCache(max_entries=4, max_bytes=32)
        keys = [cache_key(index) for index in range(12)]
        snapshots = [str(index).encode("ascii") * 6 for index in range(12)]
        barrier = Barrier(8)

        def worker(worker_id):
            barrier.wait(timeout=10)
            for step in range(60):
                index = (worker_id + step) % len(keys)
                self.assertTrue(cache.put(keys[index], snapshots[index]))
                found = cache.get(keys[index])
                if found is not None:  # Another thread may already have evicted it.
                    self.assertEqual(found, snapshots[index])
                if step % 17 == 0:
                    cache.clear()
                info = cache.info()
                self.assertLessEqual(info.entry_count, info.max_entries)
                self.assertLessEqual(info.stored_bytes, info.max_bytes)
                self.assertGreaterEqual(info.stored_bytes, 0)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, index) for index in range(8)]
            for future in futures:
                future.result(timeout=15)
        cache.clear()
        self.assertEqual(cache.info().entry_count, 0)
        self.assertEqual(cache.info().stored_bytes, 0)
