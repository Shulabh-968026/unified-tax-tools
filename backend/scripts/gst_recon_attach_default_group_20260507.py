"""Phase C.3 · attach gstin_group_id to every existing GST Recon run.

Pre-Phase-C.3 runs were keyed by ``(client, fy)`` only.  Phase C.3
shifts the canonical key to ``(client, fy, gstin_group_id)`` — every
working doc must point at a real GSTIN group so ingest validation has
a baseline GSTIN to compare against.

For every gst_recon_run currently lacking ``gstin_group_id``:

  1. Idempotently fetch (or create) the hidden ``Default`` group for
     that client via ``ensure_default_group``.
  2. Update the run with:
        gstin_group_id = <default group_id>
        scope_kind     = "gstin_group"
        scope_label    = group label ("Default")
        scope_key      = "gstin_<group_id>"

Idempotent · safe to re-run.

Usage:
    python3 backend/scripts/gst_recon_attach_default_group_20260507.py [--dry]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Importing core.db pulls in the global ``db`` Motor handle the helpers
# expect; load env first so ``MONGO_URL`` is available before import.
load_dotenv("/app/backend/.env")

from core.db import db as _global_db  # noqa: E402  (must be after dotenv)
from modules.library.gstin_groups import ensure_default_group  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="Print plan only")
    args = parser.parse_args()

    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    # Override the imported helper's `db` reference if needed.  In our
    # codebase ``modules.library.gstin_groups`` does ``from core.db
    # import db`` at module scope, so it shares this connection.
    cursor = db.gst_recon_runs.find(
        {"$or": [{"gstin_group_id": {"$in": [None, ""]}},
                 {"gstin_group_id": {"$exists": False}}]},
        {"_id": 0, "id": 1, "client_id": 1, "scope_key": 1},
    )
    seen = updated = 0
    cache: dict[str, dict] = {}
    print(f"=== Phase C.3 · GST Recon backfill — {'DRY' if args.dry else 'LIVE'} ===")
    async for r in cursor:
        seen += 1
        client_id = r.get("client_id")
        if not client_id:
            continue
        # Cache the default group per client to avoid N round-trips.
        grp = cache.get(client_id)
        if grp is None:
            grp = await ensure_default_group(client_id)
            cache[client_id] = grp
        gid = grp["group_id"]
        update = {
            "gstin_group_id": gid,
            "scope_kind":     "gstin_group",
            "scope_label":    grp.get("label") or "Default",
            "scope_key":      f"gstin_{gid}",
            "division_ids":   list(grp.get("division_ids") or []),
        }
        if args.dry:
            print(f"  [DRY] gst_recon_runs/{r['id']} → {update['scope_key']}")
        else:
            await db.gst_recon_runs.update_one({"id": r["id"]}, {"$set": update})
        updated += 1

    print(f"\nseen={seen} updated={updated}")
    print(f"groups synthesised across {len(cache)} clients")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
