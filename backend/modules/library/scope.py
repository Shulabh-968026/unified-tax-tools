"""Shared scope helpers — Multi-Division Phase C.1.

Every module's working document now carries a structured scope:

  * ``scope_kind``    — ``"consolidation" | "division" | "gstin_group"``
  * ``division_ids``  — list of division ids the run applies to (sorted, deduped).
                        Empty list for ``consolidation``; single-item for ``division``;
                        the ids covered by the group for ``gstin_group``.
  * ``scope_label``   — human-readable label (``"Consolidation"``, division name,
                        or GSTIN-group label).
  * ``scope_key``     — deterministic string used for the unique compound index.
                        ``"consolidation"`` / ``"div_<id>"`` / ``"divs_<id1>_<id2>...`` /
                        ``"gstin_<group_id>"``.
  * ``gstin_group_id`` — optional, only for ``scope_kind == "gstin_group"``.

This module is the single source of truth for scope semantics — every
controller (clause44, BC, FA, GST, FS, MSME) and the migration script
import the same helpers so the storage shape can never drift.
"""
from __future__ import annotations

from typing import Iterable, Optional

VALID_SCOPE_KINDS = {"consolidation", "division", "gstin_group"}


def normalise_division_ids(division_ids: Optional[Iterable[str]]) -> list[str]:
    """Strip blanks, dedupe, and return a sorted list."""
    if not division_ids:
        return []
    return sorted({(d or "").strip() for d in division_ids if (d or "").strip()})


def compute_scope_key(
    scope_kind: str,
    division_ids: Optional[Iterable[str]] = None,
    gstin_group_id: Optional[str] = None,
) -> str:
    """Deterministic string used in the unique compound index."""
    if scope_kind == "consolidation":
        return "consolidation"
    if scope_kind == "gstin_group":
        if not gstin_group_id:
            raise ValueError("gstin_group scope requires gstin_group_id")
        return f"gstin_{gstin_group_id}"
    if scope_kind == "division":
        ids = normalise_division_ids(division_ids)
        if not ids:
            raise ValueError("division scope requires at least one division_id")
        if len(ids) == 1:
            return f"div_{ids[0]}"
        return "divs_" + "_".join(ids)
    raise ValueError(f"Unknown scope_kind: {scope_kind!r}")


def resolve_scope(
    *,
    client_doc: dict,
    scope_kind: Optional[str] = None,
    division_ids: Optional[Iterable[str]] = None,
    gstin_group_id: Optional[str] = None,
    legacy_division_id: Optional[str] = None,
    division_label_lookup: Optional[dict[str, str]] = None,
) -> dict:
    """Build the canonical scope payload for a run.

    Resolution rules (in order):

    1. Explicit ``scope_kind`` provided → use it as-is, validating
       ``division_ids`` / ``gstin_group_id`` per kind.
    2. ``legacy_division_id`` provided → ``scope_kind = "division"`` with
       that id (back-compat for callers that haven't been migrated yet).
    3. Single-entity client → ``scope_kind = "consolidation"`` (a single
       div is functionally the same as the whole entity).
    4. Multi-div client without an explicit scope → fall back to
       ``"consolidation"`` (engagement-wide working doc).

    Returns ``{scope_kind, division_ids, scope_label, scope_key,
    gstin_group_id}``.
    """
    label_lookup = division_label_lookup or {
        d.get("division_id"): d.get("name") or d.get("division_id")
        for d in (client_doc.get("divisions") or [])
        if d.get("division_id")
    }

    # ── 1. Explicit ─────────────────────────────────────────────────────
    if scope_kind:
        if scope_kind not in VALID_SCOPE_KINDS:
            raise ValueError(f"Invalid scope_kind {scope_kind!r}")
        ids = normalise_division_ids(division_ids)
        if scope_kind == "division":
            if not ids:
                raise ValueError("division scope needs at least one division_id")
            if len(ids) == 1:
                label = label_lookup.get(ids[0], ids[0])
            else:
                label = ", ".join(label_lookup.get(i, i) for i in ids)
            key = compute_scope_key("division", ids)
            return {
                "scope_kind": "division",
                "division_ids": ids,
                "scope_label": label,
                "scope_key": key,
                "gstin_group_id": None,
            }
        if scope_kind == "gstin_group":
            if not gstin_group_id:
                raise ValueError("gstin_group scope requires gstin_group_id")
            return {
                "scope_kind": "gstin_group",
                "division_ids": ids,
                "scope_label": (gstin_group_id or "GSTIN Group"),
                "scope_key": compute_scope_key("gstin_group", ids, gstin_group_id),
                "gstin_group_id": gstin_group_id,
            }
        # consolidation
        return {
            "scope_kind": "consolidation",
            "division_ids": [],
            "scope_label": "Consolidation",
            "scope_key": "consolidation",
            "gstin_group_id": None,
        }

    # ── 2. Legacy single division id ────────────────────────────────────
    if legacy_division_id:
        ids = [legacy_division_id]
        return {
            "scope_kind": "division",
            "division_ids": ids,
            "scope_label": label_lookup.get(legacy_division_id, legacy_division_id),
            "scope_key": compute_scope_key("division", ids),
            "gstin_group_id": None,
        }

    # ── 3 + 4. No scope provided → consolidation (engagement-wide) ──────
    return {
        "scope_kind": "consolidation",
        "division_ids": [],
        "scope_label": "Consolidation",
        "scope_key": "consolidation",
        "gstin_group_id": None,
    }


def parse_division_ids_form(value: Optional[str]) -> list[str]:
    """Parse a comma- or pipe-separated form value into a sorted, deduped list."""
    if not value:
        return []
    return normalise_division_ids(value.replace("|", ",").split(","))


async def resolve_scope_for_request(
    db,
    *,
    client_id: str,
    scope_kind: Optional[str] = None,
    division_ids: Optional[Iterable[str]] = None,
    gstin_group_id: Optional[str] = None,
    legacy_division_id: Optional[str] = None,
) -> dict:
    """Async wrapper that loads the client doc and calls ``resolve_scope``.

    Used by every module's POST /runs (and equivalents) so the storage
    shape is identical across controllers.
    """
    cli = await db.clients.find_one(
        {"client_id": client_id},
        {"_id": 0, "client_id": 1, "type": 1, "divisions": 1},
    ) or {}
    return resolve_scope(
        client_doc=cli,
        scope_kind=scope_kind,
        division_ids=division_ids,
        gstin_group_id=gstin_group_id,
        legacy_division_id=legacy_division_id,
    )
