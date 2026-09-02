import { describe, expect, it } from "vitest";
import { Briefcase, LayoutDashboard } from "lucide-react";
import { NAV, resolveActiveId, type AppNavItem } from "./nav";

describe("resolveActiveId", () => {
  it("matches the root only exactly", () => {
    expect(resolveActiveId("/")).toBe("/");
    expect(resolveActiveId("/catalog")).not.toBe("/");
  });

  it("matches prefix entries, including nested paths", () => {
    expect(resolveActiveId("/catalog")).toBe("/catalog");
    expect(resolveActiveId("/universities/42")).toBe("/universities");
    expect(resolveActiveId("/experience/edit")).toBe("/experience");
  });

  it("uses matchPrefix when set", () => {
    expect(resolveActiveId("/settings/ai")).toBe("/settings/ai");
    expect(resolveActiveId("/settings/users")).toBe("/settings/ai");
    expect(resolveActiveId("/settings/anything/nested")).toBe("/settings/ai");
  });

  it("prefers the longest prefix", () => {
    const nav: AppNavItem[] = [
      { to: "/a", label: "A", icon: LayoutDashboard, studentOnly: false },
      { to: "/a/b", label: "B", icon: Briefcase, studentOnly: false },
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
    expect(NAV).toHaveLength(12);
    expect(NAV.filter((item) => item.studentOnly).map((item) => item.to)).toEqual([
      "/universities",
    ]);
    expect(NAV.filter((item) => item.section).length).toBeGreaterThan(0);
    expect(NAV[NAV.length - 1].to).toBe("/settings/ai");
  });
});
