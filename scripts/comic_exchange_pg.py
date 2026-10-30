"""Raksasa-only PostgreSQL adapter; worker commands never import this module."""

from __future__ import annotations

import json
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from scripts.comic_exchange import (
    MAX_FILE, MAX_JSON, MAX_PENDING, VERSION, acquire, bootstrap, digest, encode,
    immutable_key, load_snapshot, next_unit, owned, put_immutable, read_hashed,
    release, safe_path, save_owned, validate_manifest, validate_payloads, write_once,
)

ROOT = Path(__file__).resolve().parent


def collect_units(pg) -> list[dict]:
    """Export panel semantics, exact text, translation provenance and asset baseline."""
    rows = pg.execute(UNIT_QUERY).fetchall()
    assets = pg.execute("""
        SELECT comic_image_asset_id AS asset_id, comic_panel_id AS panel_id,
               model, prompt_sha256, local_path, public_path, sha256, status,
               width, height
        FROM comic_image_assets ORDER BY comic_image_asset_id
    """).fetchall()
    for unit in rows:
        unit["assets"] = [asset for asset in assets if asset["panel_id"] == unit["panel_id"]]
        unit["pending"] = (
            unit["panel_status"] == "queued" and unit["plan_status"] in {"planned", "rendering"}
            and bool(unit["panel_prompt"].strip())
            and not any(asset["status"] == "generated" for asset in unit["assets"])
        )
    return rows


# Kept as SQL rather than a PostgreSQL JSON staging/write path.
UNIT_QUERY = """
    SELECT pn.comic_panel_id AS panel_id, pn.panel_number, pn.panel_title,
           pn.panel_prompt, pn.caption, pn.negative_prompt, pn.status AS panel_status,
           cp.comic_plan_id AS plan_id, cp.title AS plan_title, cp.summary,
           cp.plan_json, cp.model AS plan_model, cp.prompt_version AS plan_prompt_version,
           cp.status AS plan_status, cp.translation_run_id,
           p.passage_id, p.canonical_ref, p.book, p.chapter, p.paragraph_index,
           p.greek_text, p.english_text, p.work_id,
           w.title AS work_title, w.cts_urn AS work_urn,
           s.source_id, s.source_url, s.raw_sha256 AS source_raw_sha256,
           s.edition_note, s.license_note,
           tr.english_translation AS plan_translation, tr.status AS plan_translation_status,
           tr.model AS translation_model, tr.prompt_version AS translation_prompt_version,
           latest.translation_run_id AS latest_translation_run_id,
           latest.english_translation AS latest_translation,
           latest.model AS latest_translation_model,
           latest.prompt_version AS latest_translation_prompt_version
    FROM comic_panels pn
    JOIN comic_plans cp USING (comic_plan_id)
    JOIN passages p USING (passage_id)
    JOIN works w USING (work_id)
    JOIN sources s ON s.source_id = w.source_id
    LEFT JOIN ai_translation_runs tr ON tr.translation_run_id = cp.translation_run_id
    LEFT JOIN LATERAL (
        SELECT translation_run_id, english_translation, model, prompt_version FROM ai_translation_runs
        WHERE passage_id = p.passage_id AND status = 'completed'
          AND english_translation IS NOT NULL
        ORDER BY completed_at DESC NULLS LAST, translation_run_id DESC LIMIT 1
    ) latest ON TRUE
    ORDER BY p.book::integer, p.chapter::integer, p.paragraph_index,
             cp.comic_plan_id, pn.panel_number, pn.comic_panel_id
"""


def rooted(root: Path, relative: str) -> Path:
    """Do not follow symlinks from an artifact directory outside its configured root."""
    path = root / safe_path(relative)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes configured comic root")
    return path


def export_snapshot(store, pg, comic_root: Path) -> dict:
    """Publish an immutable corpus and checked originals/derivatives for reference."""
    with pg.transaction():
        pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        units = collect_units(pg)
    references = []
    for unit in units:
        generated = [asset for asset in unit["assets"] if asset["status"] == "generated"]
        current_asset_id = max((asset["asset_id"] for asset in generated), default=None)
        for asset in unit["assets"]:
            if asset["status"] != "generated":
                continue
            original = Path(asset["local_path"])
            if not original.resolve().is_relative_to(comic_root.resolve()):
                raise ValueError("Existing original is outside configured comic root")
            paths = [("original", original)]
            # The legacy web directory holds only the latest panel derivative.
            # Preserve historical originals without attributing today's WebP to them.
            if asset["public_path"] and asset["asset_id"] == current_asset_id:
                suffix = Path(asset["public_path"]).suffix
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError("Unsupported existing derivative suffix")
                paths.append(("web", rooted(comic_root, f"web/{unit['plan_id']}/{unit['panel_number']}{suffix}")))
            for role, path in paths:
                if not 0 < path.stat().st_size <= MAX_FILE:
                    raise ValueError("Reference asset exceeds size bound")
                data = path.read_bytes()
                sha = digest(data)
                if role == "original" and sha != asset["sha256"]:
                    raise ValueError("Existing original checksum differs from PostgreSQL")
                put_immutable(store, immutable_key("references", sha), data)
                references.append({"asset_id": asset["asset_id"], "panel_id": unit["panel_id"],
                                   "role": role, "sha256": sha, "size": len(data)})
    snapshot = {"version": VERSION, "exported_at": time.time(),
                "units": units, "references": references}
    data = encode(snapshot)
    if len(data) > MAX_JSON:
        raise ValueError("Corpus snapshot exceeds size bound")
    sha = digest(data)
    put_immutable(store, immutable_key("snapshots", sha), data)
    return {"sha256": sha, "size": len(data)}


def download_result(store, entry: dict) -> tuple[dict, dict, dict]:
    """Validate all remote bytes before taking PostgreSQL write locks."""
    result_id = entry["result_id"]
    immutable_key("results", result_id)
    data = read_hashed(store, f"exchange/v1/results/{result_id}/manifest.json",
                       entry["sha256"], entry["size"], MAX_JSON)
    manifest = json.loads(data)
    snapshot = load_snapshot(store, entry["snapshot"])
    validate_manifest(manifest, entry, snapshot)
    payloads = {}
    for file in manifest["files"]:
        key = f"exchange/v1/results/{result_id}/files/{file['sha256']}"
        payloads[file["path"]] = read_hashed(store, key, file["sha256"], file["size"])
    validate_payloads(manifest, payloads)
    return manifest, snapshot, payloads


def materialize_bundle(comic_root: Path, manifest: dict, unit: dict, payloads: dict) -> tuple[Path, str]:
    """Durable immutable storage also repairs local files after an unacknowledged commit."""
    result_id = manifest["result_id"]
    for file in manifest["files"]:
        destination = rooted(comic_root, f"exchange/{result_id}/{file['sha256']}")
        write_once(destination, payloads[file["path"]])
    by_role = {file["role"]: file for file in manifest["files"]}
    original_file, web = by_role["original"], by_role["web"]
    public_path = f"/comic/{unit['plan_id']}/{unit['panel_number']}.webp"
    derivative = rooted(comic_root, f"web/{unit['plan_id']}/{unit['panel_number']}.webp")
    write_once(derivative, payloads[web["path"]])
    local_path = rooted(comic_root, f"exchange/{result_id}/{original_file['sha256']}")
    return local_path, public_path


def accept_result(store, session: dict, pg, comic_root: Path, entry: dict,
                  manifest: dict, snapshot: dict, payloads: dict) -> str:
    """Atomically receipt an immutable result; existing accepted art is never updated."""
    result_id = entry["result_id"]
    with pg.transaction():
        pg.execute("SELECT pg_advisory_xact_lock(17338657)")
        # Protect the fingerprint and queue ordering from concurrent legacy writers.
        pg.execute("""LOCK TABLE sources, works, passages, ai_translation_runs,
                      comic_plans, comic_panels, comic_image_assets IN SHARE ROW EXCLUSIVE MODE""")
        receipt = pg.execute("SELECT * FROM comic_exchange_receipts WHERE result_id=%s",
                             (result_id,)).fetchone()
        if receipt:
            if receipt["manifest_sha256"] != entry["sha256"]:
                raise ValueError("Replay differs from the durable receipt")
            if receipt["status"] == "accepted":
                materialize_bundle(comic_root, manifest, validate_manifest(manifest, entry, snapshot), payloads)
            owned(store, session)
            return receipt["status"]
        current = next_unit({"units": collect_units(pg)})
        original = validate_manifest(manifest, entry, snapshot)
        reason = ""
        if current is None or encode(current) != encode(original):
            reason = "Authoritative queue, source, plan, translation or asset baseline changed"
        status = "rejected" if reason else "accepted"
        asset_id = None
        if status == "accepted":
            width, height = validate_payloads(manifest, payloads)
            by_role = {file["role"]: file for file in manifest["files"]}
            original_file = by_role["original"]
            local_path, public_path = materialize_bundle(comic_root, manifest, original, payloads)
            row = pg.execute("""
                INSERT INTO comic_image_assets
                    (comic_panel_id, model, prompt_sha256, local_path, s3_uri, public_path,
                     sha256, width, height, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'generated') RETURNING comic_image_asset_id
            """, (original["panel_id"], manifest["model"], by_role["prompt"]["sha256"],
                  str(local_path), f"{store.identity}/exchange/v1/results/{result_id}/files/{original_file['sha256']}",
                  public_path, original_file["sha256"], width, height)).fetchone()
            asset_id = row["comic_image_asset_id"]
            pg.execute("UPDATE comic_panels SET status='rendered' WHERE comic_panel_id=%s",
                       (original["panel_id"],))
        pg.execute("""
            INSERT INTO comic_exchange_receipts
                (result_id,comic_panel_id,claim_token,snapshot_sha256,manifest_sha256,
                 source_commit,model,status,reason,comic_image_asset_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (result_id, original["panel_id"], entry["claim_token"], entry["snapshot"]["sha256"],
              entry["sha256"], manifest["source_commit"], manifest["model"], status, reason, asset_id))
        for file in manifest["files"]:
            pg.execute("""INSERT INTO comic_exchange_files
                        (result_id,path,role,s3_key,sha256,byte_count) VALUES (%s,%s,%s,%s,%s,%s)""",
                       (result_id, file["path"], file["role"],
                        f"exchange/v1/results/{result_id}/files/{file['sha256']}", file["sha256"], file["size"]))
        # A lost lease rolls back DB changes; files are harmless immutable orphans.
        owned(store, session)
    return status


def sync_raksasa(store, database_url: str, comic_root: Path, limit: int = 4) -> dict:
    """Bounded import then refresh; acknowledge only after the PG transaction commits."""
    if not 1 <= limit <= MAX_PENDING:
        raise ValueError("Import limit must be between 1 and 32")
    if not database_url:
        raise ValueError("Server sync requires an explicit PostgreSQL connection string")
    comic_root = comic_root.resolve()
    bootstrap(store)
    session = acquire(store, "raksasa")
    counts = {"accepted": 0, "rejected": 0}
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as pg:
        pg.execute("SET lock_timeout = '5s'")
        pg.execute("SET statement_timeout = '120s'")
        pg.execute("SET idle_in_transaction_session_timeout = '120s'")
        pg.execute((ROOT / "comic_exchange.sql").read_text())
        pending = list(session["state"]["pending"][:limit])
        for entry in pending:
            manifest, snapshot, payloads = download_result(store, entry)
            status = accept_result(store, session, pg, comic_root, entry, manifest, snapshot, payloads)
            counts[status] += 1
            state = owned(store, session)
            state["pending"].remove(entry)
            save_owned(store, session, state)
        pointer = export_snapshot(store, pg, comic_root)
        state = owned(store, session)
        state["snapshot"] = pointer
        save_owned(store, session, state)
    release(store, session)
    # On failure, an uncertain CAS may already have succeeded. Never fetch a new
    # ETag and clear a claim using it; let an unconfirmed owner expire safely.
    return counts
