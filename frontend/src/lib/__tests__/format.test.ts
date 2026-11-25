import { describe, expect, it } from "vitest";
import {
  formatCurrencyCents,
  formatDateTime,
  formatMoneyMinor,
  formatShortDate,
} from "../format";

describe("format utilities", () => {
  it("formats currency minor units according to ISO-4217 precision", () => {
    expect(formatMoneyMinor(100000, "INR")).toBe("₹1,000.00");
    expect(formatMoneyMinor(10000, "USD")).toBe("$100.00");
    expect(formatMoneyMinor(1000, "JPY")).toBe("¥1,000");
    expect(formatMoneyMinor(1500, "KWD")).toBe("KWD 1.500");
    expect(formatCurrencyCents(23000, "USD")).toBe("$230.00");
    expect(formatCurrencyCents(0, "USD")).toBe("$0.00");
  });

  it("never assumes USD when currency is missing or unknown", () => {
    const out = formatMoneyMinor(100000, null);
    expect(out).toContain("100,000");
    expect(out).not.toContain("$");
    expect(formatMoneyMinor(5000, "UNKNOWN")).not.toContain("$");
  });

  it("formats short UTC dates and handles null datetimes", () => {
    expect(formatShortDate("2026-11-25")).toContain("Nov");
    expect(formatDateTime(null)).toBe("Never");
  });
});
