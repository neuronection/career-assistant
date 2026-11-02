import { beforeEach, describe, expect, it, vi } from "vitest";

import { csvCell, csvSafeCell, downloadStatsCsv, toCsv } from "@/components/stats/statsExport";

describe("stats CSV export", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("neutralizes spreadsheet-formula leaders with a quote guard", () => {
    for (const hostile of ["=1+1", "+2", "-3", "@ Goals", "=cmd|' /C calc'!A0"]) {
      expect(csvSafeCell(hostile)).toMatch(/^'/);
    }
    expect(csvSafeCell("-3")).toBe("'-3");
    expect(csvSafeCell("python-3")).toBe("python-3");
    expect(csvSafeCell(null)).toBe("");
    expect(csvSafeCell(undefined)).toBe("");
    expect(csvSafeCell(42)).toBe("42");
  });

  it("quotes cells containing separators, quotes or newlines", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("line1\nline2")).toBe('"line1\nline2"');
  });

  it("joins rows with CRLF including a trailing one", () => {
    expect(toCsv([["a", "b"], ["c", "d"]])).toBe("a,b\r\nc,d\r\n");
  });

  it("downloads under the market-stats name prefix via the blob funnel", () => {
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:export-test");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    downloadStatsCsv("skills-30d", [["key", "count"], ["python", 42]]);

    expect(createObjectURL).toHaveBeenCalledWith(
      expect.objectContaining({ type: "text/csv;charset=utf-8" })
    );
    expect(click.mock.instances[0]).toBeInstanceOf(HTMLAnchorElement);
    const anchor = click.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(anchor.download).toMatch(/^market-stats-skills-30d-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(revoke).toHaveBeenCalledWith("blob:export-test");
  });
});
