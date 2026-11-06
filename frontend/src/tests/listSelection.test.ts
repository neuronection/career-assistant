import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useListSelection } from "@/features/selection/useListSelection";

const ALL = ["a", "b", "c", "d", "e", "f"];

function setup(matching: string[] = ALL, all: string[] = ALL) {
  return renderHook(
    ({ matchingIds, allIds }: { matchingIds: string[]; allIds: string[] }) =>
      useListSelection({ allIds, matchingIds }),
    { initialProps: { matchingIds: matching, allIds: all } }
  );
}

describe("useListSelection", () => {
  it("starts inactive and clears the set on exit", () => {
    const { result } = setup();
    expect(result.current.active).toBe(false);
    expect(result.current.count).toBe(0);

    act(() => result.current.enter());
    act(() => result.current.toggle("a"));
    expect(result.current.active).toBe(true);
    expect(result.current.count).toBe(1);

    act(() => result.current.exit());
    expect(result.current.active).toBe(false);
    expect(result.current.count).toBe(0);
  });

  it("toggles singles and applies set-wide changes without clearing the rest", () => {
    const { result } = setup();
    act(() => result.current.enter());

    act(() => result.current.toggle("a"));
    act(() => result.current.toggle("b"));
    expect([...result.current.ids]).toEqual(["a", "b"]);

    act(() => result.current.toggle("a"));
    expect([...result.current.ids]).toEqual(["b"]);

    act(() => result.current.setSelection(["b", "c", "d"], true));
    expect(result.current.count).toBe(3);
    act(() => result.current.setSelection(["c"], false));
    expect([...result.current.ids]).toEqual(["b", "d"]);
  });

  it("reports tri-state for a subset", () => {
    const { result } = setup();
    act(() => result.current.enter());

    expect(result.current.triState(["a", "b"])).toEqual({
      checked: false,
      mixed: false,
      count: 0,
    });

    act(() => result.current.toggle("a"));
    expect(result.current.triState(["a", "b"])).toEqual({
      checked: false,
      mixed: true,
      count: 1,
    });

    act(() => result.current.toggle("b"));
    expect(result.current.triState(["a", "b"])).toEqual({
      checked: true,
      mixed: false,
      count: 2,
    });
  });

  it("counts selections hidden by the filter and drops only those", () => {
    const { result, rerender } = setup();
    act(() => result.current.enter());
    act(() => result.current.setSelection(ALL, true));
    expect(result.current.hiddenCount).toBe(0);

    rerender({ matchingIds: ["a", "b"], allIds: ALL });
    expect(result.current.count).toBe(6);
    expect(result.current.hiddenCount).toBe(4);

    act(() => result.current.dropHidden());
    expect([...result.current.ids]).toEqual(["a", "b"]);
    expect(result.current.hiddenCount).toBe(0);
  });

  it("ignores ids that no longer exist in the listing", () => {
    const { result, rerender } = setup();
    act(() => result.current.enter());
    act(() => result.current.setSelection(["a", "gone"], true));

    rerender({ matchingIds: ["a"], allIds: ["a"] });
    expect(result.current.count).toBe(1);
    expect(result.current.isSelected("gone")).toBe(false);
  });

  it("extends a range from the last toggled row in either direction", () => {
    const { result } = setup();
    act(() => result.current.enter());

    act(() => result.current.toggle("b"));
    act(() => result.current.toggle("e", { range: true }));
    expect([...result.current.ids]).toEqual(["b", "c", "d", "e"]);

    act(() => result.current.toggle("b", { range: true }));
    expect([...result.current.ids]).toEqual([]);

    act(() => result.current.toggle("e"));
    act(() => result.current.toggle("b", { range: true }));
    expect([...result.current.ids].sort()).toEqual(["b", "c", "d", "e"]);
  });

  it("falls back to a single toggle when the anchor left the filtered view", () => {
    const { result, rerender } = setup();
    act(() => result.current.enter());
    act(() => result.current.toggle("e"));

    rerender({ matchingIds: ["a", "b"], allIds: ALL });
    act(() => result.current.toggle("a", { range: true }));
    expect([...result.current.ids]).toEqual(["e", "a"]);
  });

  it("selecting everything matching keeps hidden selections", () => {
    const { result, rerender } = setup();
    act(() => result.current.enter());
    act(() => result.current.setSelection(["e", "f"], true));

    rerender({ matchingIds: ["a", "b"], allIds: ALL });
    act(() => result.current.setSelection(["a", "b"], true));
    expect(result.current.count).toBe(4);
    expect(result.current.hiddenCount).toBe(2);
  });
});
