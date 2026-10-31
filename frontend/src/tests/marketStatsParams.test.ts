import { describe, expect, it } from "vitest";

import {
  DEFAULT_VIEW,
  parseView,
  rangeQuery,
  toSearchParams,
} from "@/features/postings/pages/marketStatsParams";

describe("market stats URL params", () => {
  it("round-trips every dimension of the view", () => {
    const params = new URLSearchParams(
      "window=custom&from=2026-10-01&to=2026-10-15&basis=open&split=source&dimension=family"
    );
    const view = parseView(params);
    expect(view).toEqual({
      window: "custom",
      from: "2026-10-01",
      to: "2026-10-15",
      basis: "open",
      split: "source",
      dimension: "family",
    });
    const back = toSearchParams(view);
    expect(back.get("basis")).toBe("open");
    expect(toSearchParams(parseView(back))).toEqual(back);
  });

  it("falls back to defaults for unknown values", () => {
    const view = parseView(
      new URLSearchParams(
        "window=4h&basis=sometimes&split=weekday&dimension=galaxy"
      )
    );
    expect(view.window).toBe("30d");
    expect(view.basis).toBe("all");
    expect(view.split).toBe("");
    expect(view.dimension).toBe("source");
  });

  it("keeps the custom window only when both dates are present", () => {
    expect(parseView(new URLSearchParams("window=custom&from=2026-10-01")).window).toBe("30d");
    expect(parseView(new URLSearchParams("window=custom&to=2026-10-01")).window).toBe("30d");
    expect(
      parseView(new URLSearchParams("window=custom&from=2026-10-01&to=2026-10-02")).window
    ).toBe("custom");
  });

  it("omits defaults from the URL", () => {
    expect(toSearchParams(DEFAULT_VIEW).toString()).toBe("");
    const view = parseView(new URLSearchParams("basis=open"));
    expect(toSearchParams(view).toString()).toBe("basis=open");
  });

  it("writes a custom range end-exclusive in UTC, like the audit RangeFilter", () => {
    const view = parseView(
      new URLSearchParams("window=custom&from=2026-10-01&to=2026-10-14")
    );
    expect(rangeQuery(view)).toEqual({
      from: "2026-10-01T00:00:00",
      to: "2026-10-15T00:00:00",
    });
  });

  it("presets pass their window through untouched", () => {
    expect(rangeQuery(parseView(new URLSearchParams("window=90d")))).toEqual({
      window: "90d",
    });
  });
});
