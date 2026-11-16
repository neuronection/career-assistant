import { describe, expect, it } from "vitest";

import { formatMoney } from "@/lib/money";

describe("formatMoney", () => {
  it("formats an amount in its currency and locale", () => {
    expect(formatMoney(60000, "EUR", "en-US")).toBe("€60,000");
    expect(formatMoney(60000, "EUR", "de-DE")).toMatch(/60\.000/);
  });

  it("renders an em dash instead of undefined or NaN", () => {
    expect(formatMoney(null, "EUR", "en-US")).toBe("—");
    expect(formatMoney(undefined, "EUR", "en-US")).toBe("—");
    expect(formatMoney(Number.NaN, "EUR", "en-US")).toBe("—");
  });
});
