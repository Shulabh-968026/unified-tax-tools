/**
 * FY — Canonical helper for Indian Financial Year handling.
 *
 * India FY = 1-Apr → 31-Mar.  For AUDIT tooling the "current" FY is the
 * most recently concluded one (you audit a year after it ends), not the
 * calendar-current one.
 *
 *   Today              currentAuditFy()   rationale
 *   ─────────────────  ─────────────────  ──────────────────────────
 *   7-May-2026         "2025-26"          FY 2025-26 closed on 31-Mar-2026
 *   1-Mar-2027         "2025-26"          still auditing prior year
 *   1-Apr-2027         "2026-27"          new FY just closed
 *
 * All FY dropdowns in the app MUST source their list + default from this
 * module.  Do not hard-code FY strings elsewhere.
 */

const START_FY_END_YEAR = 2021;       // lowest FY we surface in dropdowns: 2020-21
const LOOKAHEAD_YEARS   = 1;          // also show next-closing FY (so preparers can pre-stage)

/** "2025-26" format. */
export function currentAuditFy(today = new Date()) {
  const y = today.getFullYear();
  // JS months are 0-indexed: Apr = 3.
  const justClosedFyEndYear = today.getMonth() >= 3 ? y : y - 1;
  const startYear = justClosedFyEndYear - 1;
  return `${startYear}-${String(justClosedFyEndYear).slice(-2)}`;
}

/** List of FY options, NEWEST FIRST. */
export function fyOptions(today = new Date()) {
  const current = currentAuditFy(today);
  // Highest FY we show = current + lookahead.  Example today → "2026-27".
  const [curStart] = current.split("-").map(Number);
  const topStart = curStart + LOOKAHEAD_YEARS;
  const out = [];
  for (let s = topStart; s >= START_FY_END_YEAR - 1; s--) {
    out.push(`${s}-${String(s + 1).slice(-2)}`);
  }
  return out;
}

/** Strict validator — accepts exactly "YYYY-YY" where the 2nd = (1st%100)+1. */
export function isValidFy(s) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(s || "").trim());
  if (!m) return false;
  const start = parseInt(m[1], 10);
  const end = parseInt(m[2], 10);
  const expected = (start + 1) % 100;
  return end === expected;
}

/** "2025-26" → { start: "2025-04-01", end: "2026-03-31", startYear: 2025, endYear: 2026 }. */
export function parseFy(s) {
  if (!isValidFy(s)) return null;
  const [startStr] = s.split("-");
  const startYear = parseInt(startStr, 10);
  const endYear = startYear + 1;
  return {
    start: `${startYear}-04-01`,
    end:   `${endYear}-03-31`,
    startYear,
    endYear,
    label: s,
  };
}

/** Default FY for all new selectors. */
export const DEFAULT_FY = currentAuditFy();

/** Memoised list — safe for module-level use in dropdowns. */
export const FY_OPTIONS = fyOptions();
