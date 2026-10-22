import { describe, expect, test } from "vitest";

import { formatDate, formatNumber } from "@/lib/format";
import { setAppLocale } from "@/lib/i18n";

describe("locale-aware formatting", () => {
  test("numbers and dates follow the active locale", async () => {
    await setAppLocale("de");
    expect(formatNumber(1234.5)).toBe("1.234,5");
    expect(formatDate("2026-09-15")).toBe("15. Sept. 2026");

    await setAppLocale("en");
    expect(formatNumber(1234.5)).toBe("1,234.5");
    expect(formatDate("2026-09-15")).toBe("Sep 15, 2026");
  });
});
