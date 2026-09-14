import { describe, expect, it } from "vitest";
import { Briefcase, LayoutDashboard } from "lucide-react";
import { NAV, resolveActiveId, toNavItem, type AppNavItem } from "./nav";

describe("resolveActiveId", () => {
  it("matches the root only exactly", () => {
    expect(resolveActiveId("/")).toBe("/");
    expect(resolveActiveId("/catalog")).not.toBe("/");
  });

  it("matches prefix entries, including nested paths", () => {
    expect(resolveActiveId("/catalog")).toBe("/catalog");
    expect(resolveActiveId("/catalog/graph")).toBe("/catalog");
    expect(resolveActiveId("/catalog/generate")).toBe("/catalog");
    expect(resolveActiveId("/catalog/universities/42")).toBe("/catalog");
    expect(resolveActiveId("/postings/search")).toBe("/postings");
    expect(resolveActiveId("/profile/assessment")).toBe("/profile");
    expect(resolveActiveId("/profile/experience")).toBe("/profile");
    expect(resolveActiveId("/profile/education")).toBe("/profile");
  });

  it("uses matchPrefix when set", () => {
    expect(resolveActiveId("/settings/ai")).toBe("/settings/ai");
    expect(resolveActiveId("/settings/users")).toBe("/settings/ai");
    expect(resolveActiveId("/settings/anything/nested")).toBe("/settings/ai");
  });

  it("prefers the longest prefix", () => {
    const nav: AppNavItem[] = [
      { to: "/a", labelKey: "nav.a", icon: LayoutDashboard, studentOnly: false },
      { to: "/a/b", labelKey: "nav.b", icon: Briefcase, studentOnly: false },
    ];
    expect(resolveActiveId("/a/b/x", nav)).toBe("/a/b");
    expect(resolveActiveId("/a/z", nav)).toBe("/a");
  });

  it("returns null for unknown paths", () => {
    expect(resolveActiveId("/nowhere")).toBeNull();
  });

  it("resolves the Settings entry and its matchPrefix", () => {
    expect(resolveActiveId("/settings/users")).toBe("/settings/ai");
  });

  it("registry keeps its shape", () => {
    expect(NAV).toHaveLength(11);
    expect(NAV.filter((item) => item.studentOnly).map((item) => item.to)).toEqual(
      []
    );
    expect(NAV.filter((item) => item.section).length).toBeGreaterThan(0);
    expect(NAV[NAV.length - 1].to).toBe("/settings/ai");
  });

  it("flags the in-development pages", () => {
    expect(NAV.filter((item) => item.inDev).map((item) => item.to)).toEqual([
      "/postings",
      "/autopilot",
      "/interviews",
      "/growth",
    ]);
    // Hidden entries stay in the registry so deep links still resolve.
    expect(resolveActiveId("/postings/search")).toBe("/postings");
    expect(resolveActiveId("/autopilot")).toBe("/autopilot");
  });
});

describe("toNavItem", () => {
  it("badges the Profile entry only when proposals are pending", () => {
    const t = (key: string) => key;
    const profile = NAV.find((item) => item.to === "/profile")!;
    expect(toNavItem(profile, t, 0).badge).toBeUndefined();
    expect(toNavItem(profile, t, 3).badge).toBe(3);
    const chat = NAV.find((item) => item.to === "/chat")!;
    expect(toNavItem(chat, t, 3).badge).toBeUndefined();
    expect(toNavItem(chat, t).label).toBe("nav.chat");
  });
});
