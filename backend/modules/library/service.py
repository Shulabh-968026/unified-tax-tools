"""Library lifecycle helpers — upload / read / soft-delete / outdated check.

Pure async functions; controllers in `controller.py` adapt these to HTTP.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from core.db import db
from lib.file_storage import (
    blob_exists,
    build_storage_path,
    delete_blob,
    read_blob,
    save_blob,
    sha256_hex,
)
from modules.library.catalog import (
    FILE_TYPE_BY_KEY,
    FILE_TYPE_KEYS,
    MODULE_DEPENDENCIES,
)

# Maximum versions retained per (firm, client, period, division, file_type).
# When a fresh upload arrives that would push us past this limit, the
# *oldest, non-pinned* version is soft-deleted (not hard-deleted — pinned
# versions of any age stay alive).
MAX_VERSIONS = 3
SOFT_DELETE_GRACE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key_filter(*, firm_id: str, client_id: str, period: str, division: str | None, file_type: str) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "period": period,
        "division": division,
        "file_type": file_type,
    }


# ---------------------------------------------------------------------------
# Upload — creates a new version row, demotes prior version's `is_current`,
# auto-prunes anything past MAX_VERSIONS that isn't pinned.
# ---------------------------------------------------------------------------
async def create_file_version(
    *,
    firm_id: str,
    client_id: str,
    period: str,
    division: str | None,
    file_type: str,
    filename_original: str,
    content: bytes,
    uploaded_by_email: str,
    parse_status: str = "skipped",
    parse_summary: dict | None = None,
    parse_errors: list[str] | None = None,
) -> dict:
    """Persist a new version of `file_type` for the given key.

    Same checksum as the current version → returns the existing row
    untouched (idempotent re-upload of unchanged file).
    """
    if file_type not in FILE_TYPE_KEYS:
        raise ValueError(f"Unknown file_type '{file_type}'")

    checksum = sha256_hex(content)

    # Idempotency — if the latest non-deleted version has the same
    # checksum, return it as-is (don't bump versions for a no-op).
    current = await db.client_files.find_one(
        {**_key_filter(firm_id=firm_id, client_id=client_id, period=period, division=division, file_type=file_type),
         "is_current": True, "soft_deleted_at": None},
        {"_id": 0},
    )
    if current and current.get("checksum_sha256") == checksum:
        return current

    # Pick next version_no for this key.
    last = await db.client_files.find_one(
        _key_filter(firm_id=firm_id, client_id=client_id, period=period, division=division, file_type=file_type),
        sort=[("version_no", -1)],
        projection={"_id": 0, "version_no": 1},
    )
    next_v = (last["version_no"] + 1) if last else 1

    rel = build_storage_path(
        firm_id=firm_id, client_id=client_id, period=period, division=division,
        file_type=file_type, version_no=next_v, checksum=checksum,
        original_filename=filename_original,
    )
    save_blob(rel, content)

    file_id = f"file_{uuid.uuid4().hex[:12]}"
    doc = {
        "file_id": file_id,
        "firm_id": firm_id,
        "client_id": client_id,
        "period": period,
        "division": division,
        "file_type": file_type,
        "version_no": next_v,

        "filename_original": filename_original,
        "storage_path": rel,
        "checksum_sha256": checksum,
        "size_bytes": len(content),

        "uploaded_at": _now().isoformat(),
        "uploaded_by_email": uploaded_by_email,
        "replaces_file_id": current["file_id"] if current else None,
        "is_current": True,

        "parse_status": parse_status,
        "parse_summary": parse_summary or {},
        "parse_errors": parse_errors or [],

        "soft_deleted_at": None,
        "pinned_by_runs": [],
    }
    await db.client_files.insert_one(doc)

    # Demote the previous current row, if any.
    if current:
        await db.client_files.update_one(
            {"file_id": current["file_id"]},
            {"$set": {"is_current": False}},
        )

    # Prune (soft) — anything beyond MAX_VERSIONS that isn't pinned.
    await _prune_old_versions(firm_id=firm_id, client_id=client_id, period=period, division=division, file_type=file_type)

    doc.pop("_id", None)
    return doc


async def _prune_old_versions(*, firm_id, client_id, period, division, file_type):
    """Soft-delete the oldest unpinned versions over MAX_VERSIONS."""
    rows = await db.client_files.find(
        {**_key_filter(firm_id=firm_id, client_id=client_id, period=period, division=division, file_type=file_type),
         "soft_deleted_at": None},
        sort=[("version_no", -1)],
        projection={"_id": 0},
    ).to_list(length=200)
    keepers = rows[:MAX_VERSIONS]  # noqa: F841 — kept for clarity / future use
    candidates = rows[MAX_VERSIONS:]
    for r in candidates:
        if r.get("pinned_by_runs"):
            continue  # never auto-prune a pinned version
        await db.client_files.update_one(
            {"file_id": r["file_id"]},
            {"$set": {"soft_deleted_at": _now().isoformat()}},
        )


# ---------------------------------------------------------------------------
# List + read
# ---------------------------------------------------------------------------
async def list_files_for_client(*, firm_id: str, client_id: str, period: str | None = None,
                                 include_soft_deleted: bool = False) -> list[dict]:
    q: dict[str, Any] = {"firm_id": firm_id, "client_id": client_id}
    if period:
        q["period"] = period
    if not include_soft_deleted:
        q["soft_deleted_at"] = None
    return await db.client_files.find(q, {"_id": 0}).sort([("file_type", 1), ("version_no", -1)]).to_list(length=2000)


async def get_file(file_id: str) -> dict | None:
    return await db.client_files.find_one({"file_id": file_id}, {"_id": 0})


async def get_current_file(*, firm_id, client_id, period, division, file_type) -> dict | None:
    return await db.client_files.find_one(
        {**_key_filter(firm_id=firm_id, client_id=client_id, period=period, division=division, file_type=file_type),
         "is_current": True, "soft_deleted_at": None},
        {"_id": 0},
    )


async def read_file_bytes(file_id: str) -> bytes:
    f = await get_file(file_id)
    if not f or f.get("soft_deleted_at") and not blob_exists(f["storage_path"]):
        raise FileNotFoundError(file_id)
    return read_blob(f["storage_path"])


# ---------------------------------------------------------------------------
# Pinning (called by modules when a run consumes a file).
# ---------------------------------------------------------------------------
async def pin_file_to_run(file_id: str, run_id: str):
    await db.client_files.update_one(
        {"file_id": file_id},
        {"$addToSet": {"pinned_by_runs": run_id}},
    )


async def unpin_file_from_run(file_id: str, run_id: str):
    await db.client_files.update_one(
        {"file_id": file_id},
        {"$pull": {"pinned_by_runs": run_id}},
    )


# ---------------------------------------------------------------------------
# Soft-delete + restore + hard-prune (the 30-day cleanup).
# ---------------------------------------------------------------------------
async def soft_delete(file_id: str) -> dict:
    f = await get_file(file_id)
    if not f:
        raise FileNotFoundError(file_id)
    if f.get("pinned_by_runs"):
        raise PermissionError(
            f"File pinned by {len(f['pinned_by_runs'])} run(s); unpin first."
        )
    await db.client_files.update_one(
        {"file_id": file_id},
        {"$set": {"soft_deleted_at": _now().isoformat(), "is_current": False}},
    )
    return await get_file(file_id)  # type: ignore[return-value]


async def restore(file_id: str) -> dict:
    f = await get_file(file_id)
    if not f:
        raise FileNotFoundError(file_id)
    # Only restore if still within grace + the blob is on disk.
    if not f.get("soft_deleted_at"):
        return f
    if not blob_exists(f["storage_path"]):
        raise FileNotFoundError("blob already pruned from disk")
    # Mark as current ONLY if no other current row exists for this key.
    has_current = await db.client_files.find_one(
        {**_key_filter(firm_id=f["firm_id"], client_id=f["client_id"], period=f["period"],
                       division=f["division"], file_type=f["file_type"]),
         "is_current": True, "soft_deleted_at": None},
        {"_id": 0, "file_id": 1},
    )
    set_doc = {"soft_deleted_at": None}
    if not has_current:
        set_doc["is_current"] = True
    await db.client_files.update_one({"file_id": file_id}, {"$set": set_doc})
    return await get_file(file_id)  # type: ignore[return-value]


async def hard_prune_expired() -> int:
    """Delete blobs + DB rows for soft-deleted files past the grace window
    AND not pinned by any run.  Called by the daily cleanup job (or
    manually by an admin endpoint).  Returns count pruned."""
    cutoff = (_now() - timedelta(days=SOFT_DELETE_GRACE_DAYS)).isoformat()
    candidates = await db.client_files.find(
        {"soft_deleted_at": {"$lte": cutoff}, "pinned_by_runs": {"$size": 0}},
        {"_id": 0},
    ).to_list(length=10_000)
    pruned = 0
    for c in candidates:
        try:
            delete_blob(c["storage_path"])
        except Exception:
            pass
        await db.client_files.delete_one({"file_id": c["file_id"]})
        pruned += 1
    return pruned


# ---------------------------------------------------------------------------
# Outdated detection — the heart of the "Data outdated" UX.
# ---------------------------------------------------------------------------
async def compute_module_status(
    *,
    firm_id: str,
    client_id: str,
    period: str,
    division: str | None,
    module_key: str,
    pinned_files: dict[str, str] | None = None,
) -> dict:
    """For ONE module, return its status:

      • `outdated`       : any pinned file_type has a newer is_current row
      • `missing`        : module has dependencies not yet uploaded
      • `dependencies`   : per-dep detail (current_file_id, pinned_file_id, status)

    `pinned_files` should be the run's `{file_type → file_id}` map; pass
    None if the module has no run yet.
    """
    deps = MODULE_DEPENDENCIES.get(module_key, [])
    pinned_files = pinned_files or {}

    detail = []
    any_missing = False
    any_outdated = False

    for ft in deps:
        current = await get_current_file(
            firm_id=firm_id, client_id=client_id, period=period,
            division=division, file_type=ft,
        )
        pinned_id = pinned_files.get(ft)
        if not current:
            status = "missing"
            any_missing = True
        elif not pinned_id:
            status = "missing_pin"  # run never pinned, but file exists in library
            any_missing = True
        elif current["file_id"] != pinned_id:
            status = "outdated"
            any_outdated = True
        else:
            status = "fresh"
        detail.append({
            "file_type": ft,
            "label": FILE_TYPE_BY_KEY[ft]["label"],
            "current_file_id": current["file_id"] if current else None,
            "pinned_file_id": pinned_id,
            "status": status,
        })

    return {
        "module_key": module_key,
        "outdated": any_outdated and not any_missing,
        "missing": any_missing,
        "dependencies": detail,
    }


async def compute_client_status(
    *,
    firm_id: str,
    client_id: str,
    period: str,
    division: str | None,
) -> dict:
    """Summarise the engagement: per-file-type chip data + per-module
    outdated/missing flags.  Drives the ClientHome Library panel and the
    9-tile catalog badges in one round-trip."""

    # File-type rollup — for each catalog entry, the current version (or null).
    files = await db.client_files.find(
        {"firm_id": firm_id, "client_id": client_id, "period": period,
         "is_current": True, "soft_deleted_at": None},
        {"_id": 0},
    ).to_list(length=200)
    by_type = {f["file_type"]: f for f in files}
    file_chips = []
    for ft in FILE_TYPE_BY_KEY.values():
        cur = by_type.get(ft["key"])
        file_chips.append({
            "key": ft["key"],
            "label": ft["label"],
            "kind": ft["kind"],
            "ext": ft["ext"],
            "description": ft["description"],
            "uploaded": bool(cur),
            "file_id": cur["file_id"] if cur else None,
            "version_no": cur["version_no"] if cur else 0,
            "uploaded_at": cur["uploaded_at"] if cur else None,
            "uploaded_by_email": cur["uploaded_by_email"] if cur else None,
            "filename_original": cur["filename_original"] if cur else None,
            "size_bytes": cur["size_bytes"] if cur else 0,
        })

    # Module rollup — read the latest run for each module and compute its status.
    module_chips = []
    for module_key in MODULE_DEPENDENCIES:
        run = await db.runs.find_one(
            {"client_id": client_id, "period": period, "module": module_key, "archived": False},
            sort=[("created_at", -1)],
            projection={"_id": 0, "run_id": 1, "pinned_files": 1},
        )
        # Fallback: pre-Library runs lived in `db.runs` without a `module`
        # field — for Clause 44, those are the 100% of runs we have today.
        if not run and module_key == "clause44":
            run = await db.runs.find_one(
                {"client_id": client_id, "period": period, "archived": False, "module": {"$exists": False}},
                sort=[("created_at", -1)],
                projection={"_id": 0, "run_id": 1, "pinned_files": 1},
            )
        st = await compute_module_status(
            firm_id=firm_id, client_id=client_id, period=period, division=division,
            module_key=module_key, pinned_files=(run or {}).get("pinned_files") or {},
        )
        st["has_run"] = bool(run)
        st["run_id"] = (run or {}).get("run_id")
        module_chips.append(st)

    return {"files": file_chips, "modules": module_chips}
