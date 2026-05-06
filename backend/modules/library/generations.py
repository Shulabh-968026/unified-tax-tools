"""Release 4.5 — Append-only `run_generations` log.

A single MongoDB collection (`db.run_generations`) records one row per
"Generate" action across every module.  Used by the History drawer on each
module's working-document landing page.

Schema:
    gen_id                  str  — gen_<YYYYMMDDHHMMSS>_<run_id_prefix>
    run_id                  str  — canonical run/session id
    module                  str  — clause44 | balance_confirmation | ...
    client_id               str
    period                  str  — fy or accounting period
    division_id             str | None
    generated_by_email      str
    generated_at            ISO-8601 string
    pinned_files_snapshot   dict — {file_type → file_id}
    summary_snapshot        dict — small per-module totals object
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.db import db


async def append_generation(
    *,
    run_id: str,
    module: str,
    client_id: Optional[str],
    period: Optional[str],
    division_id: Optional[str] = None,
    generated_by_email: Optional[str],
    pinned_files_snapshot: Optional[Dict[str, Any]] = None,
    summary_snapshot: Optional[Dict[str, Any]] = None,
) -> str:
    """Insert one append-only row.  Best-effort — failures are swallowed by
    callers (the generation itself must not be aborted by a logging hiccup)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    gen_id = f"gen_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{(run_id or 'na')[:8]}"
    await db.run_generations.insert_one({
        "gen_id": gen_id,
        "run_id": run_id,
        "module": module,
        "client_id": client_id,
        "period": period,
        "division_id": division_id,
        "generated_by_email": generated_by_email or "",
        "generated_at": now_iso,
        "pinned_files_snapshot": pinned_files_snapshot or {},
        "summary_snapshot": summary_snapshot or {},
    })
    return gen_id


async def list_generations(run_id: str, *, limit: int = 200) -> list[Dict[str, Any]]:
    """Return generations for a run, newest first."""
    return await db.run_generations.find(
        {"run_id": run_id}, {"_id": 0},
    ).sort("generated_at", -1).to_list(length=limit)
