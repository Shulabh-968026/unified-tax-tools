/* eslint-env jest */
/**
 * FY helper unit tests — verify that:
 *   1. currentAuditFy returns the most-recently-concluded FY for any
 *      Indian calendar date.
 *   2. fyOptions is newest-first and includes 1 lookahead FY (so users
 *      can pre-stage data for the next FY).
 *   3. Validation + parser behave correctly on edge inputs.
 */
import { currentAuditFy, fyOptions, isValidFy, parseFy } from "../fy";

describe("currentAuditFy", () => {
  test("after 1-Apr-2026 returns 2025-26", () => {
    expect(currentAuditFy(new Date("2026-04-01T00:00:00Z"))).toBe("2025-26");
    expect(currentAuditFy(new Date("2026-05-07T12:00:00Z"))).toBe("2025-26");
    expect(currentAuditFy(new Date("2027-03-31T23:59:00Z"))).toBe("2025-26");
  });
  test("on 1-Apr-2027 flips to 2026-27", () => {
    expect(currentAuditFy(new Date("2027-04-01T00:00:00Z"))).toBe("2026-27");
  });
  test("Jan-Mar of any year still belongs to the prior FY", () => {
    expect(currentAuditFy(new Date("2026-01-15T00:00:00Z"))).toBe("2024-25");
    expect(currentAuditFy(new Date("2026-03-31T23:00:00Z"))).toBe("2024-25");
  });
});

describe("fyOptions", () => {
  test("newest-first, includes lookahead and current", () => {
    const opts = fyOptions(new Date("2026-05-07T12:00:00Z"));
    expect(opts[0]).toBe("2026-27");        // lookahead
    expect(opts[1]).toBe("2025-26");        // current audit FY
    expect(opts[2]).toBe("2024-25");
    expect(opts).toContain("2020-21");      // baseline
    expect(opts.length).toBeGreaterThanOrEqual(7);
  });
});

describe("isValidFy", () => {
  test("accepts valid FY strings", () => {
    ["2020-21", "2024-25", "2025-26", "2026-27"].forEach(s =>
      expect(isValidFy(s)).toBe(true)
    );
  });
  test("rejects malformed / impossible strings", () => {
    ["", "2025", "25-26", "2025-27", "2025/26", "2025-2026", "abcd-ef"]
      .forEach(s => expect(isValidFy(s)).toBe(false));
  });
});

describe("parseFy", () => {
  test("returns canonical date range for valid FY", () => {
    expect(parseFy("2025-26")).toEqual({
      start: "2025-04-01",
      end:   "2026-03-31",
      startYear: 2025,
      endYear:   2026,
      label: "2025-26",
    });
  });
  test("returns null for invalid FY", () => {
    expect(parseFy("2025-27")).toBeNull();
    expect(parseFy("garbage")).toBeNull();
  });
});
