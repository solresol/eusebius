"""Offline protocol tests: synthetic art only, no S3 account or paid API."""

import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError
from botocore.stub import Stubber
from PIL import Image

from scripts.comic_exchange import (
    STATE_KEY, BusyError, ConflictError, S3Store, acquire, bootstrap, digest,
    encode, hydrate, immutable_key, load_snapshot, next_unit, owned,
    put_immutable, read_hashed, read_state, record_result, release, renew,
    safe_path, write_state,
)


class FakeS3:
    """Model S3's atomic preconditions, rather than a permissive dictionary mock."""

    def __init__(self):
        self.objects = {}
        self.lock = threading.Lock()
        self.writes = []

    def get_object(self, *, Bucket, Key):
        with self.lock:
            if (Bucket, Key) not in self.objects:
                raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
            data = self.objects[Bucket, Key]
            return {"Body": io.BytesIO(data), "ContentLength": len(data), "ETag": digest(data)}

    def put_object(self, *, Bucket, Key, Body, **condition):
        with self.lock:
            self.writes.append((Key, condition))
            old = self.objects.get((Bucket, Key))
            if ((condition.get("IfNoneMatch") == "*" and old is not None) or
                    ("IfMatch" in condition and (old is None or digest(old) != condition["IfMatch"]))):
                raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
            self.objects[Bucket, Key] = Body
            return {"ETag": digest(Body)}


def fake_store():
    return S3Store("s3://test-bucket/isolated-eusebius", FakeS3())


def seed_snapshot(store, units=None, references=None):
    bootstrap(store)
    snapshot = {"version": 1, "exported_at": 1,
                "units": units or [{"panel_id": 1, "pending": True, "greek_text": "Ἑλλάς\n"}],
                "references": references or []}
    data = encode(snapshot)
    pointer = {"sha256": digest(data), "size": len(data)}
    put_immutable(store, immutable_key("snapshots", pointer["sha256"]), data)
    state, etag = read_state(store)
    state["snapshot"] = pointer
    write_state(store, state, etag)
    return pointer


def make_bundle(root):
    """Tiny synthetic fixtures are deliberately unsuitable for production art."""
    image = Image.new("RGB", (8, 6), "navy")
    image.save(root / "original.png")
    image.save(root / "web.webp")
    (root / "prompt.txt").write_text("Source-grounded documentary panel prompt.\n")
    (root / "review.md").write_text("Synthetic test fixture: no production quality claim.\n")
    (root / "source.py").write_text("# Reproduction source for synthetic fixture\n")
    return [("original", "original.png"), ("web", "web.webp"),
            ("prompt", "prompt.txt"), ("review", "review.md"), ("source", "source.py")]


class ComicExchangeTests(unittest.TestCase):
    def setUp(self):
        self.store = fake_store()
        seed_snapshot(self.store)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.files = make_bundle(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, session):
        return record_result(self.store, session, self.root, self.files, "a" * 40, "fixture")

    def test_conditional_claim_race_has_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        original_get = self.store.get

        def synchronized_get(key, limit=32 * 1024 * 1024):
            result = original_get(key, limit)
            if key == STATE_KEY:
                barrier.wait(timeout=5)
            return result

        with patch.object(self.store, "get", side_effect=synchronized_get):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(acquire, self.store, "cloud") for _ in range(2)]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except ConflictError:
                        pass
        self.assertEqual(len(results), 1)
        self.assertTrue(all("IfMatch" in c or c == {"IfNoneMatch": "*"}
                            for _, c in self.store.client.writes))

    def test_real_sdk_accepts_both_conditional_put_parameters(self):
        import boto3
        client = boto3.client("s3", region_name="ap-southeast-2",
                              aws_access_key_id="synthetic-test", aws_secret_access_key="synthetic-test")
        with Stubber(client) as stub:
            base = {"Bucket": "test-bucket", "Key": "isolated/state", "Body": b"fixture"}
            stub.add_response("put_object", {"ETag": '"one"'}, {**base, "IfNoneMatch": "*"})
            stub.add_response("put_object", {"ETag": '"two"'}, {**base, "IfMatch": '"one"'})
            store = S3Store("s3://test-bucket/isolated", client)
            self.assertEqual(store.put("state", b"fixture"), '"one"')
            self.assertEqual(store.put("state", b"fixture", '"one"'), '"two"')
            stub.assert_no_pending_responses()

    def test_only_eligible_exported_units_can_be_claimed(self):
        seed_snapshot(self.store, [{"panel_id": 5, "pending": False},
                                   {"panel_id": 9, "pending": True}])
        session = acquire(self.store, "cloud")
        self.assertEqual(session["state"]["lease"]["unit_id"], 9)

    def test_active_lease_blocks_both_roles(self):
        acquire(self.store, "cloud")
        for role in ("cloud", "raksasa"):
            with self.assertRaises(BusyError):
                acquire(self.store, role)

    def test_expired_owner_cannot_publish_release_or_renew(self):
        old = acquire(self.store, "cloud", now=1)
        successor = acquire(self.store, "cloud", now=21602)
        with patch("scripts.comic_exchange.time.time", return_value=21603):
            for action in (self.record, lambda s: release(self.store, s), lambda s: renew(self.store, s)):
                with self.assertRaises(ConflictError):
                    action(old)
            self.assertEqual(owned(self.store, successor)["lease"]["token"], successor["token"])

    def test_expired_session_cannot_reclaim_even_without_successor(self):
        session = acquire(self.store, "cloud", now=1)
        with patch("scripts.comic_exchange.time.time", return_value=21602):
            with self.assertRaises(ConflictError):
                renew(self.store, session)

    def test_record_is_immutable_idempotent_and_survives_abort(self):
        session = acquire(self.store, "cloud")
        result_id = self.record(session)
        self.assertEqual(self.record(session), result_id)
        release(self.store, session)
        state, _ = read_state(self.store)
        self.assertIsNone(state["lease"])
        self.assertEqual([e["result_id"] for e in state["pending"]], [result_id])
        with self.assertRaises(BusyError):
            acquire(self.store, "cloud")

    def test_changed_checkpoint_never_overwrites_first_result(self):
        session = acquire(self.store, "cloud")
        result_id = self.record(session)
        manifest_key = (self.store.bucket,
                        f"{self.store.prefix}/exchange/v1/results/{result_id}/manifest.json")
        before = self.store.client.objects[manifest_key]
        (self.root / "review.md").write_text("A different review")
        with self.assertRaises(ConflictError):
            self.record(session)
        self.assertEqual(self.store.client.objects[manifest_key], before)

    def test_missing_review_or_source_is_rejected_before_upload(self):
        session = acquire(self.store, "cloud")
        before = len(self.store.client.objects)
        for missing in ("review", "source", "prompt", "original", "web"):
            files = [(role, path) for role, path in self.files if role != missing]
            with self.assertRaises(ValueError):
                record_result(self.store, session, self.root, files, "a" * 40, "fixture")
        self.assertEqual(len(self.store.client.objects), before)

    def test_bad_raster_is_rejected_before_upload(self):
        session = acquire(self.store, "cloud")
        (self.root / "web.webp").write_bytes(b"not an image")
        with self.assertRaises(OSError):
            self.record(session)
        self.assertEqual(read_state(self.store)[0]["pending"], [])

    def test_hash_corruption_and_oversized_read_are_detected(self):
        self.store.put("fixture", b"abc")
        with self.assertRaises(ValueError):
            read_hashed(self.store, "fixture", digest(b"xyz"), 3)
        with self.assertRaises(ValueError):
            self.store.get("fixture", 2)

    def test_no_bucket_root_default_and_no_legacy_backup_default(self):
        for uri in ("s3://test-bucket", "s3://test-bucket/../backup", "s3://test-bucket//backup"):
            with self.assertRaises(ValueError):
                S3Store(uri, FakeS3())

    def test_path_traversal_absolute_and_symlink_escape_rejected(self):
        for value in ("../x", "/tmp/x", "a/../b", "a//b", "./a", "a\\b", "."):
            with self.assertRaises(ValueError):
                safe_path(value)
        (self.root / "escape").symlink_to(self.root.parent)
        session = acquire(self.store, "cloud")
        with self.assertRaises(ValueError):
            record_result(self.store, session, self.root, [("source", "escape/outside")], "a" * 40, "fixture")

    def test_snapshot_checksum_and_exact_text(self):
        pointer = read_state(self.store)[0]["snapshot"]
        self.assertEqual(next_unit(load_snapshot(self.store, pointer))["greek_text"], "Ἑλλάς\n")
        key = (self.store.bucket, f"{self.store.prefix}/{immutable_key('snapshots', pointer['sha256'])}")
        self.store.client.objects[key] = b"corrupt"
        with self.assertRaises(ValueError):
            acquire(self.store, "cloud")

    def test_reference_hydration_verifies_and_preserves_existing_files(self):
        data = (self.root / "original.png").read_bytes()
        sha = digest(data)
        put_immutable(self.store, immutable_key("references", sha), data)
        snapshot = {"references": [{"sha256": sha, "size": len(data)}]}
        target = self.root / "references"
        hydrate(self.store, snapshot, target)
        hydrate(self.store, snapshot, target)
        (target / sha).write_bytes(b"local work")
        with self.assertRaises(ConflictError):
            hydrate(self.store, snapshot, target)
        self.assertEqual((target / sha).read_bytes(), b"local work")

    def test_unexported_store_cannot_start_work(self):
        store = fake_store()
        bootstrap(store)
        with self.assertRaises(BusyError):
            acquire(store, "cloud")

    def test_session_cannot_be_used_in_another_namespace(self):
        session = acquire(self.store, "cloud")
        other = S3Store("s3://test-bucket/another-prefix", self.store.client)
        with self.assertRaises(ConflictError):
            owned(other, session)


if __name__ == "__main__":
    unittest.main()
