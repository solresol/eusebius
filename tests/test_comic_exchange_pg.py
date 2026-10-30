"""Opt-in disposable PostgreSQL tests; never use the production DSN variable."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from PIL import Image
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from scripts.comic_exchange import (
    BusyError, ConflictError, acquire, digest, load_snapshot, owned, read_state, record_result,
    release, save_owned, write_state,
)
from scripts.comic_exchange_pg import collect_units, promote_result, sync_raksasa
from scripts.generate_site import fetch_comic_rows, publish_comic_images
from test_comic_exchange import fake_store, make_bundle

TEST_DSN = os.environ.get("EUSEBIUS_EXCHANGE_TEST_DSN")
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(TEST_DSN, "Set EUSEBIUS_EXCHANGE_TEST_DSN to a disposable PostgreSQL database")
class ComicExchangePostgresTests(unittest.TestCase):
    def setUp(self):
        self.schema = "test_exchange_" + uuid4().hex
        self.admin = psycopg.connect(TEST_DSN, autocommit=True)
        self.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.dsn = make_conninfo(TEST_DSN, options=f"-csearch_path={self.schema}")
        self.pg = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
        self.pg.execute((ROOT / "scripts/init_db.sql").read_text())
        self.pg.execute("""INSERT INTO sources
            (source_id,title,source_url,cts_urn,edition_note,license_note,raw_sha256,raw_bytes)
            VALUES ('fixture','Fixture','https://example.invalid/tei','urn:fixture','Test only','Test only',%s,1)""",
                        ("1" * 64,))
        self.pg.execute("INSERT INTO works VALUES ('he','Historia Ecclesiastica','Eusebius','urn:fixture','fixture')")
        # Reversed lexical book order proves the exported queue uses numeric order.
        for book in (10, 2):
            row = self.pg.execute("""INSERT INTO passages
                (work_id,canonical_ref,book,chapter,paragraph_index,greek_text,english_text,greek_word_count)
                VALUES ('he',%s,%s,'1',1,'Ἑλλάς\n','Exact reference text.\n',1) RETURNING passage_id""",
                                  (f"HE {book}.1.1", str(book))).fetchone()
            plan = self.pg.execute("""INSERT INTO comic_plans
                (passage_id,model,prompt_version,title,summary,plan_json)
                VALUES (%s,'fixture','fixture','Letter','Source-grounded plan','{"panels": []}')
                RETURNING comic_plan_id""", (row["passage_id"],)).fetchone()
            self.pg.execute("""INSERT INTO comic_panels
                (comic_plan_id,panel_number,panel_title,panel_prompt,caption)
                VALUES (%s,1,'Document','A source-grounded documentary scene.','A letter.')""",
                            (plan["comic_plan_id"],))
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.comic_root = self.root / "comic"
        self.work = self.root / "work"
        self.work.mkdir()
        self.files = make_bundle(self.work)
        self.store = fake_store()
        sync_raksasa(self.store, self.dsn, self.comic_root)

    def tearDown(self):
        self.pg.close()
        self.admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()
        self.temp.cleanup()

    def checkpoint(self):
        session = acquire(self.store, "cloud")
        snapshot = load_snapshot(self.store, session["state"]["snapshot"])
        self.unit = next(u for u in snapshot["units"] if u["pending"])
        result_id = record_result(self.store, session, self.work, self.files, "a" * 40, "fixture")
        release(self.store, session)
        return result_id, read_state(self.store)[0]["pending"][0]

    def expire_test_lease(self):
        state, etag = read_state(self.store)
        state["lease"]["expires"] = 0
        write_state(self.store, state, etag)

    def counts(self):
        return [self.pg.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in ("comic_exchange_receipts", "comic_image_assets", "comic_exchange_files")]

    def site_rows(self):
        with psycopg.connect(self.dsn) as pg:
            return fetch_comic_rows(pg)

    def assert_staged_publication(self):
        self.assertEqual(self.counts(), [1, 1, 5])
        asset = self.pg.execute("SELECT status,public_path FROM comic_image_assets").fetchone()
        self.assertEqual(asset, {"status": "staged", "public_path": None})
        self.assertEqual(self.pg.execute("SELECT status FROM comic_panels WHERE comic_panel_id=%s",
                                         (self.unit["panel_id"],)).fetchone()["status"], "queued")
        self.assertEqual(self.site_rows(), [])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)

    def test_import_publishes_existing_site_and_replay_is_idempotent(self):
        result_id, entry = self.checkpoint()
        self.assertEqual(self.unit["book"], "2")
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root), {"accepted": 1, "rejected": 0})
        self.assertEqual(self.counts(), [1, 1, 5])
        with psycopg.connect(self.dsn) as pg:
            rows = fetch_comic_rows(pg)
        output = self.root / "site"
        published = publish_comic_images(output, rows, self.comic_root / "web")
        self.assertEqual(len(published), 1)
        self.assertEqual((output / rows[0]["public_path"].lstrip("/")).read_bytes(),
                         (self.work / "web.webp").read_bytes())
        snapshot = load_snapshot(self.store, read_state(self.store)[0]["snapshot"])
        self.assertEqual(len(snapshot["references"]), 2)
        self.assertEqual(next(u for u in snapshot["units"] if u["pending"])["book"], "10")
        owner = acquire(self.store, "raksasa")
        state = owner["state"]
        state["pending"].append(entry)
        save_owned(self.store, owner, state)
        release(self.store, owner)
        sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        receipt = self.pg.execute("SELECT result_id FROM comic_exchange_receipts").fetchone()
        self.assertEqual(receipt["result_id"], result_id)

    def test_source_change_is_receipted_as_rejected_without_altering_art(self):
        self.checkpoint()
        self.pg.execute("UPDATE passages SET greek_text='Changed source' WHERE passage_id=%s",
                        (self.unit["passage_id"],))
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root), {"accepted": 0, "rejected": 1})
        self.assertEqual(self.counts(), [1, 0, 5])
        self.assertEqual(read_state(self.store)[0]["pending"], [])

    def test_new_translation_after_export_rejects_old_result(self):
        self.checkpoint()
        self.pg.execute("""INSERT INTO ai_translation_runs
            (passage_id,model,prompt_version,status,english_translation,completed_at)
            VALUES (%s,'fixture','new','completed','Changed translation',now())""",
                        (self.unit["passage_id"],))
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["rejected"], 1)
        self.assertEqual(self.counts()[1], 0)

    def test_plan_edit_after_export_rejects_result(self):
        self.checkpoint()
        self.pg.execute("UPDATE comic_panels SET caption='An edited caption' WHERE comic_panel_id=%s",
                        (self.unit["panel_id"],))
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["rejected"], 1)

    def test_existing_generated_asset_is_never_replaced(self):
        self.checkpoint()
        original = self.comic_root / "accepted.png"
        original.parent.mkdir(parents=True)
        data = (self.work / "original.png").read_bytes()
        original.write_bytes(data)
        self.pg.execute("""INSERT INTO comic_image_assets
            (comic_panel_id,model,prompt_sha256,local_path,sha256,status)
            VALUES (%s,'previous',%s,%s,%s,'generated')""",
                        (self.unit["panel_id"], "0" * 64, str(original), digest(data)))
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["rejected"], 1)
        self.assertEqual(self.counts()[1], 1)
        self.assertEqual(original.read_bytes(), data)
        self.assertEqual(self.pg.execute("SELECT model FROM comic_image_assets").fetchone()["model"], "previous")

    def test_reference_export_preserves_old_original_without_mislabeling_current_webp(self):
        unit = collect_units(self.pg)[0]
        self.comic_root.mkdir(parents=True)
        for index, color in enumerate(("navy", "red")):
            original = self.comic_root / f"accepted-{index}.png"
            image = Image.new("RGB", (8, 6), color)
            image.save(original)
            web = self.comic_root / "web" / str(unit["plan_id"]) / "1.webp"
            web.parent.mkdir(parents=True, exist_ok=True)
            image.save(web)
            self.pg.execute("""INSERT INTO comic_image_assets
                (comic_panel_id,model,prompt_sha256,local_path,sha256,public_path,status)
                VALUES (%s,'previous',%s,%s,%s,%s,'generated')""",
                            (unit["panel_id"], "0" * 64, str(original), digest(original.read_bytes()),
                             f"/comic/{unit['plan_id']}/1.webp"))
        sync_raksasa(self.store, self.dsn, self.comic_root)
        snapshot = load_snapshot(self.store, read_state(self.store)[0]["snapshot"])
        self.assertEqual([ref["role"] for ref in snapshot["references"]], ["original", "original", "web"])
        web_ref = snapshot["references"][-1]
        self.assertEqual(web_ref["sha256"], digest(web.read_bytes()))
        self.assertEqual(web_ref["asset_id"], max(ref["asset_id"] for ref in snapshot["references"]))

    def test_commit_then_lost_ack_replays_without_duplicate_import(self):
        self.checkpoint()
        with patch("scripts.comic_exchange_pg.save_owned", side_effect=ConflictError("lost acknowledgement")):
            with self.assertRaises(ConflictError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)
        asset = self.pg.execute("SELECT local_path,public_path FROM comic_image_assets").fetchone()
        Path(asset["local_path"]).unlink()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        web.unlink()
        self.expire_test_lease()
        sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        self.assertEqual(read_state(self.store)[0]["pending"], [])
        self.assertTrue(Path(asset["local_path"]).is_file())
        self.assertTrue(web.is_file())

    def test_transaction_failure_preserves_pending_and_retry_accepts_orphan_files(self):
        self.checkpoint()
        self.pg.execute("""CREATE FUNCTION fail_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic transaction failure'; END $$;
            CREATE TRIGGER fail_receipt BEFORE INSERT ON comic_exchange_receipts
            FOR EACH ROW EXECUTE FUNCTION fail_receipt()""")
        with self.assertRaises(psycopg.errors.RaiseException):
            sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)
        self.pg.execute("DROP TRIGGER fail_receipt ON comic_exchange_receipts")
        self.expire_test_lease()
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["accepted"], 1)
        self.assertEqual(self.counts(), [1, 1, 5])

    def test_derivative_collision_preserves_file_and_rolls_back_database(self):
        self.checkpoint()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        web.parent.mkdir(parents=True)
        web.write_bytes(b"existing untracked artwork")
        with self.assertRaises(ConflictError):
            sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(web.read_bytes(), b"existing untracked artwork")
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)

    def test_tampered_result_asset_never_reaches_database(self):
        result_id, _ = self.checkpoint()
        objects = self.store.client.objects
        key = next(key for key in objects if f"/results/{result_id}/files/" in key[1])
        objects[key] = b"corrupt"
        with self.assertRaises(ValueError):
            sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)

    def test_expired_importer_rolls_back_and_cannot_ack(self):
        self.checkpoint()
        with patch("scripts.comic_exchange_pg.owned", side_effect=ConflictError("lease expired")):
            with self.assertRaises(ConflictError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(len(read_state(self.store)[0]["pending"]), 1)

    def test_rollback_after_archive_does_not_poison_a_different_valid_result(self):
        old_result_id, _ = self.checkpoint()
        old_image = (self.work / "original.png").read_bytes()
        old_archive = self.comic_root / "exchange" / old_result_id / digest(old_image)
        with patch("scripts.comic_exchange_pg.owned", side_effect=ConflictError("lease lost after archive")):
            with self.assertRaises(ConflictError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertEqual(old_archive.read_bytes(), old_image)
        # A changed authoritative plan legitimately rejects the old result and
        # permits a new claim. Retain every old artifact, including the orphan.
        self.pg.execute("UPDATE comic_panels SET caption='A corrected source-grounded caption' WHERE comic_panel_id=%s",
                        (self.unit["panel_id"],))
        self.expire_test_lease()
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["rejected"], 1)
        image = Image.new("RGB", (8, 6), "red")
        image.save(self.work / "original.png")
        image.save(self.work / "web.webp")
        new_result_id, _ = self.checkpoint()
        self.assertNotEqual(old_result_id, new_result_id)
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["accepted"], 1)
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        self.assertEqual(web.read_bytes(), (self.work / "web.webp").read_bytes())
        self.assertEqual(old_archive.read_bytes(), old_image)
        self.assertEqual(self.counts(), [2, 1, 10])

    def test_committed_stage_is_invisible_until_postcommit_promotion(self):
        self.checkpoint()
        with patch("scripts.comic_exchange_pg.promote_result", side_effect=OSError("interrupted before promotion")):
            with self.assertRaises(OSError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assert_staged_publication()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        self.assertFalse(web.exists())
        self.assertFalse(next(u for u in collect_units(self.pg) if u["panel_id"] == self.unit["panel_id"])["pending"])
        self.expire_test_lease()
        with self.assertRaises(BusyError):
            acquire(self.store, "cloud")
        sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        self.assertEqual(len(self.site_rows()), 1)

    def test_publication_rollback_after_canonical_write_reconciles_same_acceptance(self):
        self.checkpoint()
        self.pg.execute("""CREATE FUNCTION fail_publication() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.status = 'generated' THEN RAISE EXCEPTION 'synthetic promotion failure'; END IF;
            RETURN NEW; END $$;
            CREATE TRIGGER fail_publication BEFORE UPDATE ON comic_image_assets
            FOR EACH ROW EXECUTE FUNCTION fail_publication()""")
        with self.assertRaises(psycopg.errors.RaiseException):
            sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assert_staged_publication()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        self.assertEqual(web.read_bytes(), (self.work / "web.webp").read_bytes())
        self.pg.execute("DROP TRIGGER fail_publication ON comic_image_assets")
        self.expire_test_lease()
        sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        self.assertEqual(len(self.site_rows()), 1)
        self.assertEqual(read_state(self.store)[0]["pending"], [])

    def test_site_reader_cannot_see_uncommitted_promotion(self):
        self.checkpoint()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"
        observations = []

        def inspect_ownership(store, session):
            state = owned(store, session)
            asset = self.pg.execute("SELECT status FROM comic_image_assets").fetchone()
            if asset and asset["status"] == "staged" and web.exists():
                observations.append(web.read_bytes())
                self.assertEqual(self.site_rows(), [])
            return state

        with patch("scripts.comic_exchange_pg.owned", side_effect=inspect_ownership):
            sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(observations, [(self.work / "web.webp").read_bytes()])
        self.assertEqual(len(self.site_rows()), 1)

    def test_postcommit_collision_preserves_unrelated_file_and_staged_receipt(self):
        self.checkpoint()
        web = self.comic_root / "web" / str(self.unit["plan_id"]) / "1.webp"

        def conflicting_promotion(*args):
            web.parent.mkdir(parents=True)
            web.write_bytes(b"unrelated concurrent artwork")
            return promote_result(*args)

        with patch("scripts.comic_exchange_pg.promote_result", side_effect=conflicting_promotion):
            with self.assertRaises(ConflictError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(web.read_bytes(), b"unrelated concurrent artwork")
        self.assert_staged_publication()

    def test_export_failure_cannot_acknowledge_into_stale_queue(self):
        self.checkpoint()
        old_pointer = read_state(self.store)[0]["snapshot"]
        with patch("scripts.comic_exchange_pg.export_snapshot", side_effect=OSError("interrupted export")):
            with self.assertRaises(OSError):
                sync_raksasa(self.store, self.dsn, self.comic_root)
        self.assertEqual(self.counts(), [1, 1, 5])
        state, _ = read_state(self.store)
        self.assertEqual(state["snapshot"], old_pointer)
        self.assertEqual(len(state["pending"]), 1)
        self.expire_test_lease()
        with self.assertRaises(BusyError):
            acquire(self.store, "cloud")
        sync_raksasa(self.store, self.dsn, self.comic_root)
        state, _ = read_state(self.store)
        self.assertNotEqual(state["snapshot"], old_pointer)
        self.assertEqual(state["pending"], [])

    def test_sync_never_falls_back_to_default_database_or_unbounded_limit(self):
        for limit in (0, 33):
            with self.assertRaises(ValueError):
                sync_raksasa(self.store, self.dsn, self.comic_root, limit)
        with self.assertRaises(ValueError):
            sync_raksasa(self.store, "", self.comic_root)

    def test_ineligible_plans_and_blank_prompts_are_not_queued(self):
        first = collect_units(self.pg)[0]
        self.pg.execute("UPDATE comic_plans SET status='done' WHERE comic_plan_id=%s", (first["plan_id"],))
        self.assertFalse(collect_units(self.pg)[0]["pending"])
        self.pg.execute("UPDATE comic_plans SET status='planned' WHERE comic_plan_id=%s", (first["plan_id"],))
        self.pg.execute("UPDATE comic_panels SET panel_prompt='' WHERE comic_panel_id=%s", (first["panel_id"],))
        self.assertFalse(collect_units(self.pg)[0]["pending"])

    def test_prologue_labels_export_and_import_before_numbered_books_and_chapters(self):
        unit = collect_units(self.pg)[1]
        self.pg.execute("UPDATE passages SET book='2',chapter='prologue' WHERE passage_id=%s",
                        (unit["passage_id"],))
        self.assertEqual([row["chapter"] for row in collect_units(self.pg)], ["prologue", "1"])
        self.pg.execute("UPDATE passages SET book='prologue',chapter='prologue' WHERE passage_id=%s",
                        (unit["passage_id"],))
        units = collect_units(self.pg)
        self.assertEqual([row["book"] for row in units], ["prologue", "2"])
        sync_raksasa(self.store, self.dsn, self.comic_root)
        self.checkpoint()
        self.assertEqual(self.unit["book"], "prologue")
        self.assertEqual(self.unit["chapter"], "prologue")
        self.assertEqual(sync_raksasa(self.store, self.dsn, self.comic_root)["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
