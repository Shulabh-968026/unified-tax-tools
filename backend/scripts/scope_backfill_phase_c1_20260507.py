"""Phase C.1 · Scope backfill + index migration (2026-05-07).

Goal: every active row across the 6 module collections gets canonical
``scope_kind`` / ``division_ids`` / ``scope_label`` / ``scope_key`` fields,
and the unique compound index is rebuilt from the legacy
``(firm_id, client_id, period_field, division_id, archived)`` shape to the
new scope-aware ``(firm_id, client_id, period_field, scope_key, archived)``.

Backfill logic per row:
  * Single-entity client → scope = consolidation.
  * Multi-div client with ``division_id`` set → scope = division (single id).
  * Multi-div client with ``division_id`` null/missing → scope = consolidation
    (engagement-wide pre-Phase-C runs).

Idempotent · safe to re-run.  Supports ``--dry`` for plan-only output.

Usage:
    python3 backend/scripts/scope_backfill_phase_c1_20260507.py [--dry]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure

# Make `backend.modules` importable when running this script directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.library.scope import resolve_scope  # noqa: E402

# (collection, period_field, id_field, module_label)
COLLECTIONS = [
    ("runs",            "period", "run_id", "clause44"),
    ("bc_runs",         "fy",     "id",     "balance_confirmation"),
    ("fa_runs",         "fy",     "id",     "fixed_assets"),
    ("gst_recon_runs",  "fy",     "id",     "gst_recon"),
    ("fs_runs",         "fy",     "id",     "fin_statement"),
    ("msme_sessions",   "fy",     "id",     "msme43bh"),
]

OLD_INDEX_NAME = "canonical_run_v45"
NEW_INDEX_NAME = "canonical_run_v45_scoped"


async def _client_lookup(db) -> dict[str, dict]:
    """Pre-load every client doc keyed by client_id (cheap — < 50 clients)."""
    cursor = db.clients.find({}, {"_id": 0, "client_id": 1, "type": 1, "divisions": 1})
    out = {}
    async for c in cursor:
        out[c["client_id"]] = c
    return out


async def backfill_one(db, *, coll: str, dry: bool, clients_by_id: dict[str, dict]):
    cursor = db[coll].find({"archived": {"$ne": True}}, {"_id": 0})
    n_seen = n_updated = n_skipped = 0
    async for row in cursor:
        n_seen += 1
        # Already migrated?
        if row.get("scope_key") and row.get("scope_kind"):
            n_skipped += 1
            continue
        client_id = row.get("client_id")
        if not client_id:
            n_skipped += 1
            continue
        cli = clients_by_id.get(client_id) or {}
        legacy_div = row.get("division_id")
        scope = resolve_scope(
            client_doc=cli,
            legacy_division_id=legacy_div,
        )
        # Build update payload.  We DO NOT touch any other field.
        update = {
            "scope_kind": scope["scope_kind"],
            "division_ids": scope["division_ids"],
            "scope_label": scope["scope_label"],
            "scope_key": scope["scope_key"],
            "gstin_group_id": scope["gstin_group_id"],
        }
        n_updated += 1
        if dry:
            id_val = row.get("run_id") or row.get("id") or row.get("session_id")
            print(f"  [DRY] {coll} {id_val} → {update['scope_key']} ({update['scope_kind']})")
        else:
            # Pin the update by the row's primary key (varies by collection).
            primary_key = (
                {"run_id": row["run_id"]}      if "run_id"     in row else
                {"id": row["id"]}              if "id"         in row else
                {"session_id": row["session_id"]} if "session_id" in row else
                None
            )
            if not primary_key:
                # Last resort — match by all the legacy keys (safe but slow).
                primary_key = {
                    "client_id": client_id,
                    "archived": row.get("archived", False),
                }
                if row.get("period"):
                    primary_key["period"] = row["period"]
                if row.get("fy"):
                    primary_key["fy"] = row["fy"]
            await db[coll].update_one(primary_key, {"$set": update})
    return {"seen": n_seen, "updated": n_updated, "skipped": n_skipped}


async def rebuild_index(db, *, coll: str, period_field: str, dry: bool):
    """Drop legacy index (if present) and create the new scope-aware one."""
    info = await db[coll].index_information()
    # Drop the legacy by name (best-effort).
    if OLD_INDEX_NAME in info:
        if dry:
            print(f"  [DRY] would drop {coll}.{OLD_INDEX_NAME}")
        else:
            try:
                await db[coll].drop_index(OLD_INDEX_NAME)
                print(f"  ✓ dropped {coll}.{OLD_INDEX_NAME}")
            except OperationFailure as e:
                print(f"  ⚠ drop {coll}.{OLD_INDEX_NAME} failed: {e}")

    keys = [
        ("firm_id", 1),
        ("client_id", 1),
        (period_field, 1),
        ("scope_key", 1),
        ("archived", 1),
    ]
    if dry:
        print(f"  [DRY] would create {coll}.{NEW_INDEX_NAME}: {keys}")
        return
    if NEW_INDEX_NAME in info:
        print(f"  · {coll}.{NEW_INDEX_NAME} already present")
        return
    try:
        await db[coll].create_index(
            keys,
            name=NEW_INDEX_NAME,
            unique=True,
            partialFilterExpression={"archived": False},
        )
        print(f"  ✓ created {coll}.{NEW_INDEX_NAME}")
    except OperationFailure as e:
        print(f"  ⚠ create {coll}.{NEW_INDEX_NAME} failed: {e}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="Print plan only, no writes")
    args = parser.parse_args()

    load_dotenv("/app/backend/.env")
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    print(f"=== Phase C.1 · scope backfill — {'DRY RUN' if args.dry else 'EXECUTING'} ===")
    clients_by_id = await _client_lookup(db)
    print(f"Loaded {len(clients_by_id)} clients for backfill lookup.\n")

    grand = {"seen": 0, "updated": 0, "skipped": 0}
    for coll, period_field, _id_field, module in COLLECTIONS:
        print(f"--- {coll} ({module}) ---")
        stats = await backfill_one(db, coll=coll, dry=args.dry, clients_by_id=clients_by_id)
        await rebuild_index(db, coll=coll, period_field=period_field, dry=args.dry)
        for k, v in stats.items():
            grand[k] += v
        print(f"  · {stats}\n")

    print("=== Grand totals ===")
    print(grand)
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
