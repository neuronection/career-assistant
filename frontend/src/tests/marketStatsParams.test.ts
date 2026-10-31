import { describe, expect, it } from "vitest";

import {
  DEFAULT_VIEW,
  addIsoDays,
  compareRange,
  parseView,
  rangeQuery,
  spanDays,
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
      compare: "previous",
      compare_from: "",
      compare_to: "",
    });
    const back = toSearchParams(view);
    expect(back.get("basis")).toBe("open");
    expect(toSearchParams(parseView(back))).toEqual(back);
  });

  it("falls back to defaults for unknown values", () => {
    const view = parseView(
      new URLSearchParams(
        "window=4h&basis=sometimes&split=weekday&dimension=galaxy&compare=always"
      )
    );
    expect(view.window).toBe("30d");
    expect(view.basis).toBe("all");
    expect(view.split).toBe("");
    expect(view.dimension).toBe("source");
    expect(view.compare).toBe("previous");
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

describe("compare params (plan 171 H9)", () => {
  it("round-trips compare off/custom with their dates, omission writes previous", () => {
    const view = parseView(
      new URLSearchParams(
        "compare=custom&compare_from=2026-01-01&compare_to=2026-01-31"
      )
    );
    expect(view.compare).toBe("custom");
    expect(view.compare_from).toBe("2026-01-01");
    expect(view.compare_to).toBe("2026-01-31");
    const back = toSearchParams(view).toString();
    expect(back).toBe("compare=custom&compare_from=2026-01-01&compare_to=2026-01-31");
    expect(toSearchParams(parseView(new URLSearchParams(back)))).toEqual(
      new URLSearchParams(back)
    );
    expect(toSearchParams(parseView(new URLSearchParams("compare=off"))).toString()).toBe(
      "compare=off"
    );
    // previous is the default-on ghost: written never, parsed always.
    expect(toSearchParams(parseView(new URLSearchParams(""))).toString()).toBe("");
  });

  it("drops dangling or impossible custom dates to previous, pending pairs stay custom", () => {
    expect(
      parseView(new URLSearchParams("compare=custom&compare_from=nonsense")).compare
    ).toBe("previous");
    expect(
      parseView(
        new URLSearchParams("compare=custom&compare_from=2026-01-01&compare_to=soon")
      ).compare
    ).toBe("previous");
    // 2026-02-30 names no real day.
    expect(
      parseView(new URLSearchParams("compare=custom&compare_from=2026-02-30")).compare
    ).toBe("previous");
    // A `to` without a `from` is dangling on itself.
    expect(
      parseView(new URLSearchParams("compare=custom&compare_to=2026-01-31")).compare
    ).toBe("previous");
    // Both pending: the pair reveals (window=all), nothing fetches.
    const pending = parseView(new URLSearchParams("compare=custom"));
    expect(pending.compare).toBe("custom");
    expect(pending.compare_from).toBe("");
    expect(pending.compare_to).toBe("");
  });

  it("seats the B end at compare_from + A's span, except window=all", () => {
    expect(
      compareRange(parseView(new URLSearchParams("window=30d&compare=custom&compare_from=2026-01-01")))
    ).toEqual({ from: "2026-01-01", to: "2026-01-30" });
    expect(
      compareRange(parseView(new URLSearchParams("window=24h&compare=custom&compare_from=2026-01-01")))
    ).toEqual({ from: "2026-01-01", to: "2026-01-01" });
    expect(
      compareRange(
        parseView(
          new URLSearchParams(
            "window=custom&from=2026-03-01&to=2026-03-10&compare=custom&compare_from=2026-01-01"
          )
        )
      )
    ).toEqual({ from: "2026-01-01", to: "2026-01-10" });
    // Set `to` wins over the mirrored span; window=all awaits both dates.
    expect(
      compareRange(
        parseView(
          new URLSearchParams(
            "window=30d&compare=custom&compare_from=2026-01-01&compare_to=2026-02-14"
          )
        )
      )
    ).toEqual({ from: "2026-01-01", to: "2026-02-14" });
    expect(
      compareRange(parseView(new URLSearchParams("window=all&compare=custom&compare_from=2026-01-01")))
    ).toBeNull();
    expect(
      compareRange(
        parseView(
          new URLSearchParams(
            "window=all&compare=custom&compare_from=2026-01-01&compare_to=2026-01-31"
          )
        )
      )
    ).toEqual({ from: "2026-01-01", to: "2026-01-31" });
  });

  it("spans whole days and moves by calendar days in UTC", () => {
    expect(spanDays(parseView(new URLSearchParams("window=90d")))).toBe(90);
    expect(spanDays(parseView(new URLSearchParams("")))).toBe(30);
    expect(spanDays(parseView(new URLSearchParams("window=all")))).toBeNull();
    expect(addIsoDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addIsoDays("2026-01-05", -59)).toBe("2025-11-07");
  });
});
