import { describe, expect, it } from "vitest";

import { formatAbsolute, formatRelativeTime } from "@/lib/time";

const NOW = new Date("2026-10-27T12:00:00Z");

function iso(secondsAgo: number): string {
  return new Date(NOW.getTime() - secondsAgo * 1000).toISOString();
}

describe("formatRelativeTime", () => {
  it("returns just now inside the 45-second window", () => {
    expect(formatRelativeTime(iso(5), NOW)).toEqual({ key: "common.time.justNow", count: 0 });
    expect(formatRelativeTime(iso(44), NOW)).toEqual({ key: "common.time.justNow", count: 0 });
    expect(formatRelativeTime(iso(45), NOW)).toEqual({ key: "common.time.minutesAgo", count: 1 });
  });

  it("rolls minutes → hours → days → months → years", () => {
    expect(formatRelativeTime(iso(5 * 60), NOW)).toEqual({
      key: "common.time.minutesAgo",
      count: 5,
    });
    expect(formatRelativeTime(iso(3 * 3600), NOW)).toEqual({
      key: "common.time.hoursAgo",
      count: 3,
    });
    expect(formatRelativeTime(iso(3 * 86400), NOW)).toEqual({
      key: "common.time.daysAgo",
      count: 3,
    });
    expect(formatRelativeTime(iso(60 * 86400), NOW)).toEqual({
      key: "common.time.monthsAgo",
      count: 2,
    });
    expect(formatRelativeTime(iso(400 * 86400), NOW)).toEqual({
      key: "common.time.yearsAgo",
      count: 1,
    });
  });

  it("renders future timestamps with the in-forms", () => {
    const inThreeDays = new Date(NOW.getTime() + 3 * 86400 * 1000).toISOString();
    expect(formatRelativeTime(inThreeDays, NOW)).toEqual({
      key: "common.time.inDays",
      count: 3,
    });
    const soon = new Date(NOW.getTime() + 10 * 1000).toISOString();
    expect(formatRelativeTime(soon, NOW)).toEqual({
      key: "common.time.inAMoment",
      count: 0,
    });
  });

  it("returns null for missing or malformed input", () => {
    expect(formatRelativeTime(null, NOW)).toBeNull();
    expect(formatRelativeTime(undefined, NOW)).toBeNull();
    expect(formatRelativeTime("not a date", NOW)).toBeNull();
  });
});

describe("formatAbsolute", () => {
  it("formats a timestamp and tolerates bad input", () => {
    expect(formatAbsolute("2026-10-27T12:00:00Z")).not.toBe("");
    expect(formatAbsolute(undefined)).toBe("");
    expect(formatAbsolute("not a date")).toBe("");
  });
});
