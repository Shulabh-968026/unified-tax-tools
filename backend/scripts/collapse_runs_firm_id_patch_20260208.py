"""Release 4.5 · Patch — firm_id normalisation + re-collapse.

The initial `collapse_runs_20260207.py` keyed the canonical group on raw
`firm_id`.  Pre-4.5 rows without a `firm_id` (legacy migrations) therefore
failed to collapse with their post-4.5 siblings that carry
`firm_id='firm_mss_001'`.

This patch runs idempotently:
  1. Scan each module's collection for non-archived rows.
  2. Re-group using NORMALISED key `(firm_id or 'firm_mss_001', client_id,
     period, division, module)`.
  3. Archive the loser(s) with `collapsed_into=<winner>` and unpin their
     Library pins.
  4. Finally, normalise `firm_id` to the default on remaining active rows so
     future writes land in the same canonical bucket.

The winner is chosen by: `(has_firm_id, generated, created_at)` — newest
canonical firm-stamped generated run wins.

Safe to re-run.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

DEFAULT_FIRM = "firm_mss_001"

MODULES = [
    # (collection,          period_field, id_field,  module_tag)
    ("runs",                "period",     "run_id",  "clause44"),
    ("bc_runs",             "fy",         "id",      "balance_confirmation"),
    ("fa_runs",             "fy",         "id",      "fixed_assets"),
    ("gst_recon_runs",      "fy",         "id",      "gst_recon"),
    ("fs_runs",             "fy",         "id",      "fin_statement"),
    ("msme_sessions",       "fy",         "id",      "msme43bh"),
]


async def _collapse_module(db, coll: str, period_field: str, id_field: str, module: str) -> int:
    rows = await db[coll].find({"archived": {"$ne": True}}, {"_id": 0}).to_list(length=5000)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        k = (
            (r.get("firm_id") or DEFAULT_FIRM),
            r.get("client_id") or "",
            r.get(period_field) or "",
            r.get("division_id") or r.get("division") or None,
            module,
        )
        groups.setdefault(k, []).append(r)

    now = datetime.now(timezone.utc).isoformat()
    archived = 0
    for key, grp in groups.items():
        if len(grp) <= 1:
            continue

        def score(d):
            return (
                1 if d.get("firm_id") else 0,       # canonical firm_id first
                1 if d.get("generated") is True else 0,
                d.get("created_at") or "",
            )

        winner = sorted(grp, key=score, reverse=True)[0]
        wid = winner.get(id_field)
        print(f"{coll}: key={key} -> winner={wid} (group={len(grp)})")
        for loser in grp:
            lid = loser.get(id_field)
            if lid == wid:
                continue
            await db[coll].update_one(
                {id_field: lid},
                {"$set": {
                    "archived":         True,
                    "archived_at":      now,
                    "archived_reason":  "collapsed_into_canonical_run",
                    "collapsed_into":   wid,
                }},
            )
            for fid in (loser.get("pinned_files") or {}).values():
                if fid:
                    await db.client_files.update_one(
                        {"file_id": fid},
                        {"$pull": {"pinned_by_runs": lid}},
                    )
            archived += 1
            print(f"  archived {lid}")
    return archived


async def _normalise_firm_id(db, coll: str) -> int:
    """After collapse, set firm_id=DEFAULT_FIRM on remaining non-archived rows."""
    res = await db[coll].update_many(
        {
            "archived": {"$ne": True},
            "$or": [
                {"firm_id": {"$exists": False}},
                {"firm_id": None},
                {"firm_id": ""},
            ],
        },
        {"$set": {"firm_id": DEFAULT_FIRM}},
    )
    if res.modified_count:
        print(f"{coll}: firm_id normalised on {res.modified_count} active rows")
    return res.modified_count


async def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    total_archived = 0
    for coll, period_field, id_field, module in MODULES:
        total_archived += await _collapse_module(db, coll, period_field, id_field, module)

    for coll, *_ in MODULES:
        await _normalise_firm_id(db, coll)

    print(f"\n✔ done · {total_archived} stray runs archived by re-collapse")


if __name__ == "__main__":
    asyncio.run(main())
