#!/usr/bin/env python3
"""Lease-controlled S3 handoff for Eusebius comic panels; no cloud DB access."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

VERSION = 1
STATE_KEY = "exchange/v1/state.json"
MAX_JSON = 32 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_FILES = 40
MAX_PENDING = 32
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class BusyError(RuntimeError):
    """Another worker owns the exchange, or an import is required."""


class ConflictError(RuntimeError):
    """Stop using a stale session after lease loss or a conditional failure."""


def encode(value) -> bytes:
    """Serialize exact, deterministic UTF-8 bytes for content addressing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    """Return a SHA-256 content address."""
    return hashlib.sha256(data).hexdigest()


def safe_path(value: str) -> str:
    """Accept only canonical portable relative paths, never filesystem escapes."""
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or
            "\\" in value or str(path) != value or value == "."):
        raise ValueError("Unsafe relative artifact path")
    return value


def immutable_key(kind: str, sha: str) -> str:
    """Make namespaced keys from validated hashes, never arbitrary result paths."""
    if not HASH_RE.fullmatch(sha):
        raise ValueError("Invalid SHA-256")
    return f"exchange/v1/{kind}/{sha}"


class S3Store:
    """Bounded reads, immutable objects and compare-and-swap control state."""

    def __init__(self, uri: str, client=None):
        match = re.fullmatch(r"s3://([^/]+)/(.+)", uri.rstrip("/"))
        if not match:
            raise ValueError("Use an explicitly configured S3 bucket AND dedicated prefix")
        self.bucket, self.prefix = match.groups()
        safe_path(self.prefix)
        self.identity = f"s3://{self.bucket}/{self.prefix}"
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client("s3", config=Config(
                connect_timeout=10, read_timeout=60,
                retries={"mode": "standard", "total_max_attempts": 3},
            ))
        self.client = client

    def get(self, key: str, limit: int = MAX_JSON) -> tuple[bytes, str]:
        """Read bytes and ETag together; close streams even on validation errors."""
        from botocore.exceptions import ClientError
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=f"{self.prefix}/{safe_path(key)}")
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        try:
            if response["ContentLength"] > limit:
                raise ValueError("S3 object exceeds size bound")
            data = response["Body"].read(limit + 1)
            if len(data) > limit:
                raise ValueError("S3 object exceeds size bound")
            return data, response["ETag"]
        finally:
            response["Body"].close()

    def put(self, key: str, data: bytes, etag: str | None = None) -> str:
        """Never retry a stale write using a newly fetched ETag."""
        from botocore.exceptions import ClientError
        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            response = self.client.put_object(
                Bucket=self.bucket, Key=f"{self.prefix}/{safe_path(key)}", Body=data,
                **condition,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {
                "PreconditionFailed", "ConditionalRequestConflict", "412", "409",
            }:
                raise ConflictError("Conditional S3 write failed; stop this session") from exc
            raise
        return response["ETag"]


def put_immutable(store, key: str, data: bytes) -> None:
    """An identical retry is safe; an existing different object is never replaced."""
    try:
        store.put(key, data)
    except ConflictError:
        existing, _ = store.get(key, max(MAX_JSON, MAX_FILE))
        if existing != data:
            raise ConflictError("Immutable object differs")
    actual, _ = store.get(key, max(MAX_JSON, MAX_FILE))
    if actual != data:
        raise ValueError("S3 readback verification failed")


def read_hashed(store, key: str, sha: str, size: int, limit: int = MAX_FILE) -> bytes:
    """Verify both the declared size and digest on each trusted boundary."""
    if not HASH_RE.fullmatch(sha) or not 0 < size <= limit:
        raise ValueError("Invalid artifact digest or size")
    data, _ = store.get(key, size)
    if len(data) != size or digest(data) != sha:
        raise ValueError("Artifact checksum/size mismatch")
    return data


def read_state(store) -> tuple[dict, str]:
    """Read only this version's bounded control object."""
    data, etag = store.get(STATE_KEY)
    state = json.loads(data)
    if (state["version"] != VERSION or not isinstance(state["pending"], list)
            or len(state["pending"]) > MAX_PENDING):
        raise ValueError("Unsupported or oversized exchange state")
    return state, etag


def write_state(store, state: dict, etag: str | None) -> str:
    """Every control-object mutation increments its generation and uses CAS."""
    state["generation"] += 1
    return store.put(STATE_KEY, encode(state), etag)


def bootstrap(store) -> None:
    """Only Raksasa may initialize an empty, separately approved exchange prefix."""
    try:
        read_state(store)
    except FileNotFoundError:
        write_state(store, {"version": VERSION, "generation": 0,
                           "snapshot": None, "lease": None, "pending": []}, None)


def acquire(store, role: str, *, now=None) -> dict:
    """Conditionally claim one shared lease; cloud work requires a fresh export."""
    now = time.time() if now is None else now
    state, etag = read_state(store)
    lease = state["lease"]
    if lease and lease["expires"] > now:
        raise BusyError("Exchange already has an active worker")
    if role == "cloud" and (not state["snapshot"] or state["pending"]):
        raise BusyError("Raksasa must export/import before more production")
    if role not in {"cloud", "raksasa"}:
        raise ValueError("Unknown worker role")
    unit = None
    if role == "cloud":
        snapshot = load_snapshot(store, state["snapshot"])
        unit = next_unit(snapshot)
        if unit is None:
            raise BusyError("No queued panel in the authoritative export")
    token = uuid4().hex
    state["lease"] = {"token": token, "role": role,
                      "expires": now + (21600 if role == "cloud" else 3600),
                      "unit_id": unit["panel_id"] if unit else None,
                      "snapshot": state["snapshot"], "recorded": False}
    etag = write_state(store, state, etag)
    return {"store": store.identity, "token": token, "etag": etag, "state": state}


def owned(store, session: dict, *, now=None) -> dict:
    """Check owner, ETag AND expiry; old owners cannot release their successors."""
    now = time.time() if now is None else now
    if session["store"] != store.identity:
        raise ConflictError("Session belongs to another exchange prefix")
    state, etag = read_state(store)
    lease = state["lease"]
    if (etag != session["etag"] or not lease or lease["token"] != session["token"]
            or lease["expires"] <= now):
        raise ConflictError("Lease expired or exchange changed; stop this session")
    return state


def save_owned(store, session: dict, state: dict) -> None:
    """Publish only while the original conditional claim still belongs to us."""
    owned(store, session)
    session["etag"] = write_state(store, state, session["etag"])
    session["state"] = state


def renew(store, session: dict) -> None:
    """Extend the live owner, never reclaim an expired session."""
    state = owned(store, session)
    state["lease"]["expires"] = time.time() + (
        21600 if state["lease"]["role"] == "cloud" else 3600)
    save_owned(store, session, state)


def release(store, session: dict) -> None:
    """Release a claim while preserving every checkpointed result."""
    state = owned(store, session)
    state["lease"] = None
    save_owned(store, session, state)


def load_snapshot(store, pointer: dict) -> dict:
    """Immutable exports are read only and selected solely by the control object."""
    key = immutable_key("snapshots", pointer["sha256"])
    data = read_hashed(store, key, pointer["sha256"], pointer["size"], MAX_JSON)
    snapshot = json.loads(data)
    if snapshot["version"] != VERSION:
        raise ValueError("Unsupported corpus snapshot")
    return snapshot


def next_unit(snapshot: dict) -> dict | None:
    """Use the server-exported ordered queue, never a worker-selected passage."""
    return next((unit for unit in snapshot["units"] if unit["pending"]), None)


def image_info(data: bytes, expected_format: str) -> tuple[int, int]:
    """Verify the entire raster and protect the importer from oversized images."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if (image.format != expected_format or image.width < 1 or image.height < 1
                or image.width * image.height > 40_000_000 or getattr(image, "n_frames", 1) != 1):
            raise ValueError("Invalid image format, dimensions or frame count")
        dimensions = image.size
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
    return dimensions


def validate_manifest(manifest: dict, entry: dict, snapshot: dict) -> dict:
    """Validate provenance and bounded, complete artifacts independently on import."""
    unit = next_unit(snapshot)
    if (not unit or manifest["version"] != VERSION or
            manifest["result_id"] != entry["result_id"] or
            manifest["claim_token"] != entry["claim_token"] or
            manifest["snapshot"] != entry["snapshot"] or
            manifest["panel_id"] != unit["panel_id"] or
            manifest["unit_sha256"] != digest(encode(unit)) or
            not COMMIT_RE.fullmatch(manifest["source_commit"]) or
            not manifest["model"].strip() or len(manifest["model"]) > 200):
        raise ValueError("Invalid result provenance or queue position")
    expected_id = digest(encode([manifest["claim_token"], manifest["snapshot"], unit["panel_id"]]))
    if manifest["result_id"] != expected_id:
        raise ValueError("Result ID does not match the claim")
    files = manifest["files"]
    if not 5 <= len(files) <= MAX_FILES or sum(f["size"] for f in files) > 256 * 1024 * 1024:
        raise ValueError("Result bundle exceeds bounds or lacks required files")
    paths, roles = set(), []
    for file in files:
        safe_path(file["path"])
        if (file["path"] in paths or not HASH_RE.fullmatch(file["sha256"])
                or not 0 < file["size"] <= MAX_FILE or file["role"] not in
                {"original", "web", "prompt", "review", "source", "component"}):
            raise ValueError("Invalid result file metadata")
        paths.add(file["path"])
        roles.append(file["role"])
    for role in ("original", "web", "review", "prompt"):
        if roles.count(role) != 1:
            raise ValueError(f"Require exactly one {role} artifact")
    if "source" not in roles:
        raise ValueError("Require at least one source artifact")
    return unit


def record_result(store, session: dict, workspace: Path, files: list[tuple[str, str]],
                  source_commit: str, model: str) -> str:
    """Checkpoint one reviewed queued panel and all reproduction/review assets."""
    state = owned(store, session)
    lease = state["lease"]
    if lease["role"] != "cloud":
        raise ValueError("Only a cloud claim can produce a panel")
    snapshot = load_snapshot(store, lease["snapshot"])
    unit = next_unit(snapshot)
    result_id = digest(encode([lease["token"], lease["snapshot"], unit["panel_id"]]))
    entry = {"result_id": result_id, "claim_token": lease["token"], "snapshot": lease["snapshot"]}
    payloads, metadata = {}, []
    root = workspace.resolve()
    total_size = 0
    if len(files) > MAX_FILES:
        raise ValueError("Too many result files")
    for role, name in files:
        safe_path(name)
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise ValueError("Artifact must be a file within the workspace")
        if not 0 < path.stat().st_size <= MAX_FILE:
            raise ValueError("Artifact exceeds size bound")
        total_size += path.stat().st_size
        if total_size > 256 * 1024 * 1024:
            raise ValueError("Result bundle exceeds total size bound")
        data = path.read_bytes()
        payloads[name] = data
        metadata.append({"role": role, "path": name, "sha256": digest(data), "size": len(data)})
    manifest = {"version": VERSION, **entry, "panel_id": unit["panel_id"],
                "unit_sha256": digest(encode(unit)), "source_commit": source_commit,
                "model": model, "files": sorted(metadata, key=lambda f: f["path"])}
    validate_manifest(manifest, entry, snapshot)
    validate_payloads(manifest, payloads)
    for file in manifest["files"]:
        key = f"exchange/v1/results/{result_id}/files/{file['sha256']}"
        put_immutable(store, key, payloads[file["path"]])
    data = encode(manifest)
    put_immutable(store, f"exchange/v1/results/{result_id}/manifest.json", data)
    entry.update({"sha256": digest(data), "size": len(data)})
    if lease["recorded"]:
        if state["pending"] != [entry]:
            raise ConflictError("Checkpoint differs from this claim's immutable result")
        return result_id
    if len(state["pending"]) >= MAX_PENDING:
        raise ValueError("Import required before more results")
    state["pending"].append(entry)
    lease["recorded"] = True
    save_owned(store, session, state)
    return result_id


def validate_payloads(manifest: dict, payloads: dict[str, bytes]) -> tuple[int, int]:
    """Check raster formats plus the complete source/review bundle before acceptance."""
    by_role = {file["role"]: payloads[file["path"]] for file in manifest["files"]}
    dimensions = image_info(by_role["original"], "PNG")
    image_info(by_role["web"], "WEBP")
    for file in manifest["files"]:
        if file["role"] in {"prompt", "review", "source"}:
            if not payloads[file["path"]].decode("utf-8").strip():
                raise ValueError(f"Empty {file['role']} artifact")
    return dimensions


def hydrate(store, snapshot: dict, destination: Path) -> None:
    """Retrieve accepted reference art by hash without clobbering local files."""
    for ref in snapshot["references"]:
        data = read_hashed(store, immutable_key("references", ref["sha256"]),
                           ref["sha256"], ref["size"])
        write_once(destination / ref["sha256"], data)


def write_once(path: Path, data: bytes) -> None:
    """Create immutable local files durably; a retry may only find identical bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".exchange-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.stat().st_size != len(data) or path.read_bytes() != data:
                raise ConflictError("Existing local artifact differs; preserving it")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> int:
    """Worker commands have no PostgreSQL connection path; sync is server only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-uri", default=os.environ.get("EUSEBIUS_EXCHANGE_S3_URI"))
    parser.add_argument("--session", type=Path, default=Path(".comic-exchange/session.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("begin", "next", "renew", "finish", "abort", "status"):
        sub.add_parser(name)
    get = sub.add_parser("hydrate")
    get.add_argument("--destination", type=Path, default=Path(".comic-exchange/references"))
    record = sub.add_parser("record-result")
    record.add_argument("--workspace", type=Path, default=Path.cwd())
    record.add_argument("--source-commit", required=True)
    record.add_argument("--model", required=True)
    record.add_argument("--file", action="append", required=True, help="role=relative/path")
    sync = sub.add_parser("sync")
    sync.add_argument("--database-url", default=os.environ.get("EUSEBIUS_DATABASE_URL"))
    sync.add_argument("--comic-root", type=Path, required=True)
    sync.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()
    if not args.s3_uri:
        parser.error("Configure EUSEBIUS_EXCHANGE_S3_URI with an approved dedicated prefix")
    store = S3Store(args.s3_uri)
    try:
        if args.command == "sync":
            if not args.database_url:
                parser.error("Server sync requires an explicit --database-url or EUSEBIUS_DATABASE_URL")
            from scripts.comic_exchange_pg import sync_raksasa
            print(sync_raksasa(store, args.database_url, args.comic_root, args.limit))
            return 0
        if args.command == "status":
            state, _ = read_state(store)
            print(encode({"generation": state["generation"], "snapshot": state["snapshot"],
                          "worker": {key: value for key, value in (state["lease"] or {}).items()
                                     if key != "token"}, "pending": len(state["pending"])}).decode())
            return 0
        if args.command == "begin":
            if args.session.exists():
                parser.error("Local session exists; finish/abort it or archive it after confirming expiry")
            session = acquire(store, "cloud")
            pointer = session["state"]["snapshot"]
            snapshot = load_snapshot(store, pointer)
            local_snapshot = args.session.parent / f"snapshot-{pointer['sha256']}.json"
            write_once(local_snapshot, encode(snapshot))
            print(encode({"snapshot_file": str(local_snapshot), "unit": next_unit(snapshot)}).decode())
        else:
            session = json.loads(args.session.read_bytes())
            state = owned(store, session)
            if args.command == "next":
                print(encode(next_unit(load_snapshot(store, state["lease"]["snapshot"]))).decode())
            elif args.command == "hydrate":
                hydrate(store, load_snapshot(store, state["lease"]["snapshot"]), args.destination)
            elif args.command == "renew":
                renew(store, session)
            elif args.command == "record-result":
                files = [tuple(value.split("=", 1)) for value in args.file]
                if any(len(value) != 2 for value in files):
                    parser.error("--file must have role=relative/path form")
                print(record_result(store, session, args.workspace, files, args.source_commit, args.model))
            elif args.command in {"finish", "abort"}:
                release(store, session)
                args.session.unlink()
                return 0
        args.session.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.session.with_suffix(".tmp")
        temporary.write_bytes(encode(session))
        temporary.chmod(0o600)
        temporary.replace(args.session)
    except BusyError as exc:
        print(str(exc))
        return 3
    except ConflictError as exc:
        print(str(exc))
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
