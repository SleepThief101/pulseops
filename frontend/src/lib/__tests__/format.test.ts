import { describe, expect, it } from "vitest";
import { formatCurrencyCents, formatDateTime, formatShortDate } from "../format";

describe("format utilities", () => {
  it("formats cents into currency strings", () => {
    expect(formatCurrencyCents(23000, "USD")).toBe("$230.00");
    expect(formatCurrencyCents(0, "USD")).toBe("$0.00");
  });

  it("formats short UTC dates and handles null datetimes", () => {
    expect(formatShortDate("2026-11-25")).toContain("Nov");
    expect(formatDateTime(null)).toBe("Never");
  });
});
