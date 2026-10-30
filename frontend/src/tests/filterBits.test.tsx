import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { TriStateChips, triStateToggle } from "@/components/filters/filterBits";

const VALUES = [
  { value: "remote", label: "Remote", count: 3, testId: "mode-remote" },
  { value: "onsite", label: "On-site", count: 1, testId: "mode-onsite" },
];

describe("triStateToggle", () => {
  it("cycles off → include → exclude → off", () => {
    const empty = { include: [] as string[], exclude: [] as string[] };
    const included = triStateToggle(empty.include, empty.exclude, "remote", "include");
    expect(included).toEqual({ include: ["remote"], exclude: [] });
    const excluded = triStateToggle(included.include, included.exclude, "remote", "exclude");
    expect(excluded).toEqual({ include: [], exclude: ["remote"] });
    const cleared = triStateToggle(excluded.include, excluded.exclude, "remote", "clear");
    expect(cleared).toEqual({ include: [], exclude: [] });
  });

  it("keeps include and exclude mutually exclusive", () => {
    const next = triStateToggle(["remote"], ["remote"], "remote", "include");
    expect(next.exclude).toEqual([]);
  });
});

describe("TriStateChips", () => {
  it("cycles the chip through include, exclude and clear", () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <TriStateChips values={VALUES} include={[]} exclude={[]} onToggle={onToggle} showCounts />
    );
    fireEvent.click(screen.getByTestId("mode-remote"));
    expect(onToggle).toHaveBeenLastCalledWith("remote", "include");

    rerender(
      <TriStateChips values={VALUES} include={["remote"]} exclude={[]} onToggle={onToggle} showCounts />
    );
    expect(screen.getByTestId("mode-remote")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("mode-remote"));
    expect(onToggle).toHaveBeenLastCalledWith("remote", "exclude");

    rerender(
      <TriStateChips values={VALUES} include={[]} exclude={["remote"]} onToggle={onToggle} showCounts />
    );
    expect(screen.getByTestId("mode-remote")).toHaveTextContent("− Remote");
    fireEvent.click(screen.getByTestId("mode-remote"));
    expect(onToggle).toHaveBeenLastCalledWith("remote", "clear");
  });

  it("clears a selected value from its remove button", () => {
    const onToggle = vi.fn();
    render(
      <TriStateChips
        values={VALUES}
        include={["remote"]}
        exclude={[]}
        onToggle={onToggle}
        showCounts
      />
    );
    fireEvent.click(screen.getByTestId("mode-remote-clear"));
    expect(onToggle).toHaveBeenLastCalledWith("remote", "clear");
    expect(screen.queryByTestId("mode-onsite-clear")).not.toBeInTheDocument();
  });

  it("offers no remove button on an unselected chip and no exclude when disabled", () => {
    const onToggle = vi.fn();
    render(
      <TriStateChips
        values={VALUES}
        include={["remote"]}
        exclude={[]}
        onToggle={onToggle}
        allowExclude={false}
      />
    );
    expect(screen.queryByTestId("mode-onsite-clear")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("mode-remote"));
    expect(onToggle).toHaveBeenLastCalledWith("remote", "clear");
  });
});
