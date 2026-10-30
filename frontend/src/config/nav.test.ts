import { describe, expect, it } from "vitest";
import { Briefcase, LayoutDashboard } from "lucide-react";
import { FEATURES, isVisible } from "@/config/features";
import { NAV, resolveActiveId, toNavItem, type AppNavItem } from "@/config/nav";

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
    expect(NAV).toHaveLength(15);
    expect(NAV.filter((item) => item.studentOnly).map((item) => item.to)).toEqual(
      []
    );
    expect(NAV.filter((item) => item.section).length).toBeGreaterThan(0);
    expect(NAV[NAV.length - 1].to).toBe("/settings/ai");
  });

  it("keeps every registry-backed page visible in navigation", () => {
    const visible = NAV.filter((item) => isVisible(item.to)).map((item) => item.to);
    expect(visible).toEqual(NAV.map((item) => item.to));
    expect(FEATURES.map((feature) => feature.key).sort()).toEqual([
      "/applications",
      "/autopilot",
      "/companies",
      "/growth",
      "/interviews",
      "/onboarding/setup",
      "/paths",
      "/postings",
      "/settings/audit",
      "/settings/companies",
      "/settings/taxonomy",
    ]);
    // Postings and Companies graduate to shipped on 2026-10-30; the
    // remaining registered surfaces stay beta (un-gated 2026-10-21)
    // except the shipped first-run AI setup step; none are hidden.
    expect(
      FEATURES.filter((feature) => feature.state === "beta")
        .map((feature) => feature.key)
        .sort()
    ).toEqual(["/autopilot", "/growth", "/interviews", "/paths"]);
    expect(FEATURES.every((feature) => feature.state !== "hidden")).toBe(true);
    // Deep links still resolve against the registry.
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

  it("graduated surfaces carry no beta pill", () => {
    const t = (key: string) => key;
    const postings = NAV.find((item) => item.to === "/postings")!;
    expect(toNavItem(postings, t).badge).toBeUndefined();
    const catalog = NAV.find((item) => item.to === "/catalog")!;
    expect(toNavItem(catalog, t).badge).toBeUndefined();
    const profile = NAV.find((item) => item.to === "/profile")!;
    expect(toNavItem(profile, t).badge).toBeUndefined();
  });
});
