import { describe, expect, it } from "vitest";

import {
  buildListUrl,
  buildOpenTotalUrl,
  drillWindow,
  isExactDrillWindow,
} from "@/features/postings/pages/market-intelligence/buildListUrl";
import { parseView } from "@/features/postings/pages/marketStatsParams";

function url(query: string): string {
  return buildListUrl(parseView(new URLSearchParams(query)));
}

describe("market intelligence drill (plan 195)", () => {
  it("carries the preset window as posted_within", () => {
    for (const [window, expected] of [
      ["24h", "24h"],
      ["7d", "7d"],
      ["30d", "30d"],
      ["90d", "90d"],
    ] as const) {
      const target = new URL(url(`window=${window}`), "http://x");
      expect(target.searchParams.get("posted_within")).toBe(expected);
    }
  });

  it("window=all carries no time bound, like the card it came from", () => {
    const target = new URL(url("window=all&basis=all"), "http://x");
    expect(target.searchParams.has("posted_within")).toBe(false);
    expect(target.searchParams.get("basis")).toBe("all");
  });

  it("snaps a custom range to the nearest preset and flags the inexact drill", () => {
    const exact = parseView(
      new URLSearchParams("window=custom&from=2026-10-01&to=2026-10-30")
    );
    expect(drillWindow(exact)).toBe("30d");
    expect(isExactDrillWindow(exact)).toBe(true);

    const inexact = parseView(
      new URLSearchParams("window=custom&from=2026-10-01&to=2026-10-20")
    );
    expect(drillWindow(inexact)).toBe("30d");
    expect(isExactDrillWindow(inexact)).toBe(false);

    const openEnded = parseView(
      new URLSearchParams("window=custom&from=2026-01-01&to=2026-12-31")
    );
    expect(drillWindow(openEnded)).toBeNull();
  });

  it("carries the basis and every active segment", () => {
    const target = new URL(
      url(
        "window=7d&basis=all&source=synth&org=Acme%2C%20Inc.&mapped_family=tech-it" +
          "&seniority=senior&remote_policy=remote&employment_type=full_time" +
          "&contract=permanent&education_min=bachelor&city=Athens&country=Greece" +
          "&skills=python:4&skill_mode=any&salary_min=50000&q=data&hidden_include=true"
      ),
      "http://x"
    );
    const params = target.searchParams;
    expect(target.pathname).toBe("/postings");
    expect(params.get("posted_within")).toBe("7d");
    expect(params.get("basis")).toBe("all");
    expect(params.get("source")).toBe("synth");
    expect(params.getAll("org")).toEqual(["Acme, Inc."]);
    expect(params.get("mapped_family")).toBe("tech-it");
    expect(params.get("seniority")).toBe("senior");
    expect(params.get("remote_policy")).toBe("remote");
    expect(params.get("employment_type")).toBe("full_time");
    expect(params.get("contract")).toBe("permanent");
    expect(params.get("education_min")).toBe("bachelor");
    expect(params.get("city")).toBe("Athens");
    expect(params.get("country")).toBe("Greece");
    expect(params.get("skills")).toBe("python:4");
    expect(params.get("skill_mode")).toBe("any");
    expect(params.get("salary_min")).toBe("50000");
    expect(params.get("q")).toBe("data");
    expect(params.get("hidden_include")).toBe("true");
  });

  it("drills the all-time open total without a window or an all basis", () => {
    const target = new URL(
      buildOpenTotalUrl(
        parseView(
          new URLSearchParams("window=30d&basis=all&source=synth&seniority=senior"),
        ),
      ),
      "http://x",
    );
    expect(target.pathname).toBe("/postings");
    expect(target.searchParams.has("posted_within")).toBe(false);
    expect(target.searchParams.has("basis")).toBe(false);
    expect(target.searchParams.get("source")).toBe("synth");
    expect(target.searchParams.get("seniority")).toBe("senior");
  });

  it("defaults to the default window when the view is empty", () => {
    expect(url("")).toBe("/postings?posted_within=30d&basis=all");
  });
});
