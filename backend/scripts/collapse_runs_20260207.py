"""
Release 4.5 · Phase A — Collapse multi-run model into one working doc per
(firm_id, client_id, period, division, module) per module.

For each module collection, group active (non-archived) docs by canonical
key.  Pick the BEST winner (most-recent non-archived `generated` run; if
none, most-recent non-archived); archive the rest with
`collapsed_into=<winner_id>`.  Append a synthetic `run_generations` row
for each previously-generated run we know about (one per winner + losers
where applicable) so the history drawer has a baseline.

Idempotent: a doc with `collapse_processed_at` set is left alone.

Run with:
    python -m scripts.collapse_runs_20260207

Add `--dry` to print a plan without writing.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Repo bootstrap so we can import the same modules the API uses (Library
# unpin, etc.).  Script lives at /app/backend/scripts/.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Module map: collection name → (period_field, id_field, kind label)
# ---------------------------------------------------------------------------
MODULES: List[Tuple[str, str, str, str]] = [
    # collection,        period field, id field,  module label
    ("runs",             "period", "run_id", "clause44"),
    ("bc_runs",          "fy",     "id",     "balance_confirmation"),
    ("fa_runs",          "fy",     "id",     "fixed_assets"),
    ("gst_recon_runs",   "fy",     "id",     "gst_recon"),
    ("fs_runs",          "fy",     "id",     "fin_statement"),
    ("msme_sessions",    "fy",     "id",     "msme43bh"),
]


def canonical_key(doc: dict, period_field: str, module: str) -> Tuple[str, str, str, str | None, str]:
    return (
        doc.get("firm_id") or "_default_firm",
        doc.get("client_id") or "",
        doc.get(period_field) or "",
        doc.get("division_id") or doc.get("division") or None,
        module,
    )


def best_winner(group: List[dict]) -> dict:
    """Pick the canonical winner from a group of docs sharing a key.

    Priority:
      1. Most-recent non-archived where `generated == True` (Clause 44) or
         `status` indicates a produced report (other modules).
      2. Otherwise: most-recent non-archived (newest created_at).
    """
    def is_report_done(d: dict) -> bool:
        if d.get("generated") is True:
            return True
        st = (d.get("status") or "").lower()
        return st in ("rendered", "summarized", "completed", "ingested", "computed")

    sorted_by_date = sorted(group, key=lambda d: d.get("created_at") or "", reverse=True)
    for d in sorted_by_date:
        if is_report_done(d):
            return d
    return sorted_by_date[0]


async def collapse_one_collection(
    db, coll_name: str, period_field: str, id_field: str, module: str, *, dry: bool,
) -> Dict[str, int]:
    rows = await db[coll_name].find(
        {"archived": {"$ne": True}, "collapse_processed_at": {"$exists": False}},
        {"_id": 0},
    ).to_list(length=None)

    groups: Dict[Tuple, List[dict]] = {}
    for r in rows:
        k = canonical_key(r, period_field, module)
        groups.setdefault(k, []).append(r)

    n_groups = len(groups)
    n_collapsed = 0
    n_unique = 0
    n_winners_marked = 0

    for key, group in groups.items():
        if len(group) == 1:
            n_unique += 1
            winner = group[0]
            winner_id = winner.get(id_field)
            if not dry and winner_id:
                await db[coll_name].update_one(
                    {id_field: winner_id},
                    {"$set": {
                        "collapse_processed_at": datetime.now(timezone.utc).isoformat(),
                        "module": module,
                    }},
                )
                n_winners_marked += 1
            continue
        winner = best_winner(group)
        winner_id = winner.get(id_field)
        losers = [d for d in group if d.get(id_field) != winner_id]
        print(f"  [{coll_name}] key={key} winners={winner_id} losers={[l.get(id_field) for l in losers]}")
        if not dry:
            await db[coll_name].update_one(
                {id_field: winner_id},
                {"$set": {
                    "collapse_processed_at": datetime.now(timezone.utc).isoformat(),
                    "module": module,
                }},
            )
            n_winners_marked += 1
            for L in losers:
                lid = L.get(id_field)
                if not lid:
                    continue
                await db[coll_name].update_one(
                    {id_field: lid},
                    {"$set": {
                        "archived": True,
                        "archived_at": datetime.now(timezone.utc).isoformat(),
                        "archived_reason": "collapsed_into_canonical_run",
                        "collapsed_into": winner_id,
                        "collapse_processed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                # Unpin Library files so prune job can reclaim storage.
                for fid in (L.get("pinned_files") or {}).values():
                    if fid:
                        await db.client_files.update_one(
                            {"file_id": fid}, {"$pull": {"pinned_by_runs": lid}},
                        )
                n_collapsed += 1
            # Synthesise a baseline `run_generations` row for the winner if
            # it appears to have been previously generated.
            if winner.get("generated") or (winner.get("results") if module == "msme43bh" else False) or winner.get("status") in ("rendered", "summarized", "completed", "computed"):
                await db.run_generations.insert_one({
                    "gen_id": f"gen_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{winner_id[:8] if winner_id else 'na'}",
                    "run_id": winner_id,
                    "module": module,
                    "client_id": winner.get("client_id"),
                    "period": winner.get(period_field),
                    "generated_by_email": winner.get("generated_by_email"),
                    "generated_at": winner.get("generated_at") or winner.get("computed_at") or winner.get("updated_at"),
                    "pinned_files_snapshot": winner.get("pinned_files") or {},
                    "summary_snapshot": _summary_for_module(winner, module),
                    "synthesised": True,
                })
    return {
        "groups": n_groups, "unique": n_unique,
        "collapsed": n_collapsed, "winners_marked": n_winners_marked,
    }


def _summary_for_module(doc: dict, module: str) -> dict:
    """Best-effort totals snapshot — null-safe; one shape per module."""
    if module == "clause44":
        s = doc.get("summary") or {}
        return {
            "col_2_total": s.get("col_2_total"),
            "col_3_total": s.get("col_3_total"),
            "col_4_total": s.get("col_4_total"),
            "col_5_total": s.get("col_5_total"),
            "col_7_total": s.get("col_7_total"),
            "col_8_total": s.get("col_8_total"),
        }
    if module == "msme43bh":
        s = ((doc.get("results") or {}).get("summary") or {})
        return {
            "final_disallowance": s.get("final_disallowance"),
            "bill_count": s.get("bill_count"),
            "disallowed_count": s.get("disallowed_count"),
        }
    if module == "balance_confirmation":
        return {"summary": doc.get("summary") or {}}
    if module == "fixed_assets":
        return {"status": doc.get("status")}
    if module == "fin_statement":
        return {
            "note_count": doc.get("note_count"),
            "detail_count": doc.get("detail_count"),
        }
    if module == "gst_recon":
        return {"summary": doc.get("summary") or {}}
    return {}


async def ensure_indexes(db, *, dry: bool):
    """Compound unique index per collection on (firm_id, client_id,
    period_field, division_id, archived).  We include `archived` so the
    constraint only fires for live (non-archived) docs."""
    plans = [
        ("runs",           [("firm_id", 1), ("client_id", 1), ("period", 1), ("division_id", 1), ("module", 1), ("archived", 1)]),
        ("bc_runs",        [("firm_id", 1), ("client_id", 1), ("fy", 1),     ("archived", 1)]),
        ("fa_runs",        [("firm_id", 1), ("client_id", 1), ("fy", 1),     ("archived", 1)]),
        ("gst_recon_runs", [("firm_id", 1), ("client_id", 1), ("fy", 1),     ("archived", 1)]),
        ("fs_runs",        [("firm_id", 1), ("client_id", 1), ("fy", 1),     ("archived", 1)]),
        ("msme_sessions",  [("firm_id", 1), ("client_id", 1), ("fy", 1),     ("archived", 1)]),
    ]
    for coll, keys in plans:
        idx_name = "canonical_run_v45"
        if dry:
            print(f"  [DRY] would create idx {idx_name} on {coll}: {keys}")
            continue
        try:
            # Mongo's partial-index expression doesn't support $ne/$not, so
            # we filter on `archived: false` directly.  Older docs that
            # have neither `archived` nor `archived: false` won't be
            # included — fine, since the API path always sets the field.
            await db[coll].create_index(
                keys, name=idx_name, unique=True,
                partialFilterExpression={"archived": False},
            )
            print(f"  ✓ idx ensured: {coll}.{idx_name}")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ idx skipped on {coll}: {e}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    load_dotenv("/app/backend/.env")
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]

    print(f"=== Release 4.5 / Phase A · run collapse — {'DRY RUN' if args.dry else 'EXECUTING'} ===")
    grand = {"groups": 0, "unique": 0, "collapsed": 0, "winners_marked": 0}
    for coll, period_field, id_field, module in MODULES:
        print(f"\n--- {coll} ({module}) ---")
        stats = await collapse_one_collection(
            db, coll, period_field, id_field, module, dry=args.dry,
        )
        for k, v in stats.items():
            grand[k] = grand[k] + v
        print(f"   stats: {stats}")

    print("\n--- Indexes ---")
    await ensure_indexes(db, dry=args.dry)

    print(f"\n=== TOTAL: {grand} ===")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
