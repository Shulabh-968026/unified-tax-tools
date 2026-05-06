"""Release 4.6 · R2 backfill — populate head/subhead on pre-4.6 BC ledgers.

Existing `bc_ledgers` rows ingested before Release 4.6 have blank
`head` / `subhead` fields because the chain-walker
(`compute_head_subhead`) didn't exist at ingest time.  The BC Summary
Subhead Heatmap + workbench fall back to `parent_group`, which is why
users still see "Indian Creditors" / "MSME Vendors" instead of
"Sundry Creditors" / "Bank Accounts".

This script:
  1. Walks every `bc_runs` row.
  2. Looks up the cached gzipped books JSON in `bc_books_raw` for that
     run (still available since we store it at ingest time).
  3. Rebuilds the Tally group index from the JSON.
  4. For each ledger in that run, computes (head, subhead) from the
     parent_group chain and updates the ledger doc in-place.

Idempotent — re-running is safe (it only overwrites existing fields
with the computed values, which are deterministic).
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from modules.balance_confirmation.classifier import (
    build_group_index, compute_head_subhead,
)


async def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    total_runs = 0
    total_updated = 0
    skipped_no_books = 0

    async for run in db.bc_runs.find({}, {"_id": 0, "id": 1}):
        rid = run.get("id")
        if not rid:
            continue
        total_runs += 1

        raw = await db.bc_books_raw.find_one({"run_id": rid}, {"_id": 0, "content_b64": 1})
        if not raw:
            skipped_no_books += 1
            continue

        try:
            content = gzip.decompress(base64.b64decode(raw["content_b64"]))
            j = json.loads(content.decode("utf-8", errors="replace"))
        except Exception as e:
            print(f"[{rid}] failed to decode books: {e}")
            skipped_no_books += 1
            continue

        groups = j.get("groups") or []
        g_idx = build_group_index(groups)

        # Fetch all ledgers for this run and update in a tight loop.
        async for L in db.bc_ledgers.find({"run_id": rid}, {"_id": 1, "parent_group": 1}):
            parent = (L.get("parent_group") or "").strip()
            head, subhead = compute_head_subhead(parent, g_idx)
            await db.bc_ledgers.update_one(
                {"_id": L["_id"]},
                {"$set": {"head": head, "subhead": subhead}},
            )
            total_updated += 1

        print(f"[{rid}] backfilled {total_updated} ledgers (cumulative)")

    print(
        f"\n✔ done · runs visited={total_runs} "
        f"ledgers backfilled={total_updated} "
        f"skipped_no_books={skipped_no_books}"
    )


if __name__ == "__main__":
    asyncio.run(main())
