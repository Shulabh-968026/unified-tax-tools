/**
 * Scope helpers — Phase B · Multi-division support.
 *
 * The page-level Scope selector on `/dashboard/clients/:id` lets the
 * auditor pick:
 *   - A specific division (Tally books-of-accounts grain)
 *   - A GSTIN group (defined in Library)
 *   - "Consolidation" (all divisions, sum)
 *
 * Each module declares which scopes it supports (its "grain").  Tiles
 * grey out with a one-line hint when the selected scope is incompatible.
 */

/**
 * Module grain registry — what scopes each module's reports support.
 * Keys match `module_key` in `lib/utilities.jsx`.
 */
export const MODULE_GRAIN = {
  // Books-driven modules — division OR consolidation roll-up.
  clause44:             ["division", "consolidation"],
  msme43bh:             ["division", "consolidation"],
  balance_confirmation: ["division", "consolidation"],
  // GSTIN-keyed module.
  gst_recon:            ["gstin_group"],
  // PAN-level only.
  fixed_assets:         ["consolidation"],
  fin_statement:        ["consolidation"],
};

/** Encode a chosen scope into a stable URL string. */
export function encodeScope(scope) {
  if (!scope) return null;
  if (scope.kind === "consolidation") return "consolidation";
  if (scope.kind === "division")      return `div_${scope.id}`;
  if (scope.kind === "gstin_group")   return `gstin_${scope.id}`;
  return null;
}

/** Decode a URL scope string into a structured scope object. */
export function decodeScope(s, { divisions = [], gstinGroups = [] } = {}) {
  if (!s || s === "consolidation") return { kind: "consolidation", id: null, label: "Consolidation" };
  if (s.startsWith("div_")) {
    const id = s.slice(4);
    const d = divisions.find((x) => x.division_id === id);
    return d ? { kind: "division", id, label: d.name, divisions: [id] } : null;
  }
  if (s.startsWith("gstin_")) {
    const id = s.slice(6);
    const g = gstinGroups.find((x) => x.group_id === id);
    return g ? { kind: "gstin_group", id, label: g.label, gstin: g.gstin || "", divisions: g.division_ids } : null;
  }
  return null;
}

/**
 * Returns true if the given module supports the chosen scope.
 * For multi-grain modules (clause44, BC, MSME), gstin-group scope
 * roll-up is implicitly supported via consolidation sum-logic.
 */
export function moduleSupportsScope(moduleKey, scope) {
  if (!moduleKey || !scope) return true;   // unknown / soon utilities — treat as compatible
  const grains = MODULE_GRAIN[moduleKey];
  if (!grains) return true;
  if (grains.includes(scope.kind)) return true;
  // gstin-group is a kind of mini-consolidation — books-driven modules
  // can still produce a roll-up across the divisions in the group.
  if (scope.kind === "gstin_group" && grains.includes("consolidation") && grains.includes("division")) {
    return true;
  }
  return false;
}

/** Friendly hint shown on incompatible tiles. */
export function incompatScopeHint(moduleKey, scope) {
  if (!moduleKey || !scope) return "";
  const grains = MODULE_GRAIN[moduleKey] || [];
  if (grains.length === 1 && grains[0] === "consolidation") {
    return "Consolidation-only — switch to Consolidation";
  }
  if (grains.length === 1 && grains[0] === "gstin_group") {
    return "Pick a GSTIN group in the Working Period bar";
  }
  return "Switch scope to use this utility";
}

/** Is this a multi-division client? */
export function isMultiDiv(divisions) {
  return Array.isArray(divisions) && divisions.length >= 2;
}

/**
 * Read scope+fy from the current URL search params.  Used by every
 * module's Landing page so a single-source-of-truth scope flows from
 * `ClientUtilities` page → module without prop-drilling.
 *
 * Returns ``{ fy, scopeKind, divisionIds, gstinGroupId, scopeKey,
 * scopeLabel }`` — values usable directly in a POST /runs payload.  The
 * defaults are FY=DEFAULT_FY and scope=consolidation (matches the
 * backend's resolve_scope fallback).
 */
export function readScopeFromUrl(search) {
  const sp = typeof search === "string"
    ? new URLSearchParams(search.startsWith("?") ? search.slice(1) : search)
    : (search || new URLSearchParams());
  const fy = sp.get("fy") || "";
  const enc = sp.get("scope") || "consolidation";
  if (enc === "consolidation") {
    return {
      fy, scopeKind: "consolidation", divisionIds: [],
      gstinGroupId: null, scopeKey: "consolidation",
      scopeLabel: "Consolidation",
    };
  }
  if (enc.startsWith("div_")) {
    const id = enc.slice(4);
    return {
      fy, scopeKind: "division", divisionIds: [id],
      gstinGroupId: null, scopeKey: `div_${id}`,
      scopeLabel: "",
    };
  }
  if (enc.startsWith("gstin_")) {
    const id = enc.slice(6);
    return {
      fy, scopeKind: "gstin_group", divisionIds: [],
      gstinGroupId: id, scopeKey: `gstin_${id}`,
      scopeLabel: "",
    };
  }
  return {
    fy, scopeKind: "consolidation", divisionIds: [],
    gstinGroupId: null, scopeKey: "consolidation",
    scopeLabel: "Consolidation",
  };
}

/**
 * Build the scope payload object to send on POST /runs requests.  Only
 * includes keys the backend expects, and drops nulls/undefined so the
 * existing single-scope callers (no params) get default behaviour.
 */
export function scopeRequestPayload(scope) {
  if (!scope) return {};
  const out = {};
  if (scope.scopeKind && scope.scopeKind !== "consolidation") {
    out.scope_kind = scope.scopeKind;
  } else if (scope.scopeKind === "consolidation") {
    out.scope_kind = "consolidation";
  }
  if (Array.isArray(scope.divisionIds) && scope.divisionIds.length > 0) {
    out.division_ids = scope.divisionIds;
  }
  if (scope.gstinGroupId) {
    out.gstin_group_id = scope.gstinGroupId;
  }
  return out;
}
