import { useState } from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FacetChip } from "@neuronection/assistant-ui/filters";

import {
  countsState,
  facetLabels,
  facetOptions,
  multiValue,
  triStateToggle,
  type CountsState,
  type FacetValue,
} from "@/lib/filterFacets";

const STRINGS: Record<string, string> = {
  "filters.excluded": "excluded",
  "filters.noneMatch": "none match now",
  "filters.notRecorded": "Not recorded",
  "filters.include": "Include",
  "filters.exclude": "Exclude",
  "filters.clickToClear": "Click to clear",
};

const t = (key: string, options?: Record<string, unknown>) => {
  if (key === "filters.removeValue") return `Remove ${String(options?.value)}`;
  if (key === "filters.optionMenu") return `${String(options?.value)} options`;
  return STRINGS[key] ?? key;
};

const VALUES: FacetValue[] = [
  { value: "remote", label: "Remote", count: 3 },
  { value: "onsite", label: "On-site", count: 1 },
];

/** One career rail row: include/exclude state on the shared inline chip. */
function Row({
  allowExclude = true,
  values = VALUES,
  initialInclude = [],
  initialExclude = [],
  counts = "ready",
}: {
  allowExclude?: boolean;
  values?: FacetValue[];
  initialInclude?: string[];
  initialExclude?: string[];
  counts?: CountsState;
}) {
  const [include, setInclude] = useState<string[]>(initialInclude);
  const [exclude, setExclude] = useState<string[]>(initialExclude);
  return (
    <FacetChip
      facet={{
        id: "mode",
        label: "Work mode",
        kind: "multi",
        allowExclude,
        countsState: counts,
        options: facetOptions(values, { include, exclude }),
      }}
      value={multiValue(include, exclude)}
      variant="inline"
      showActivePills={false}
      labels={facetLabels(t)}
      onToggleOption={(value, action) => {
        if (value === null) return;
        const next = triStateToggle(include, exclude, value, action);
        setInclude(next.include);
        setExclude(next.exclude);
      }}
      testId="mode"
      optionTestId={(value) => `mode-${value ?? "not-recorded"}`}
    />
  );
}

describe("triStateToggle", () => {
  it("cycles off → include → exclude → off", () => {
    const included = triStateToggle([], [], "remote", "include");
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

describe("countsState", () => {
  it("is ready only when no request is in flight or failed", () => {
    expect(countsState()).toBe("ready");
    expect(countsState({ loading: true })).toBe("loading");
    expect(countsState({ failed: true })).toBe("error");
    expect(countsState({ loading: true, failed: true })).toBe("error");
  });
});

describe("facetOptions", () => {
  it("passes a facet count through, including a real zero", () => {
    const options = facetOptions([
      { value: "a", label: "A", count: 0 },
      { value: "b", label: "B" },
    ]);
    expect(options[0].count).toBe(0);
    expect("count" in options[1]).toBe(false);
  });

  it("keeps an applied value missing from the option list, with no count", () => {
    const options = facetOptions(VALUES, { include: ["hybrid"], exclude: ["overnight"] });
    expect(options.map((option) => option.value)).toEqual([
      "remote",
      "onsite",
      "hybrid",
      "overnight",
    ]);
    const hybrid = options.find((option) => option.value === "hybrid");
    expect(hybrid?.label).toBe("hybrid");
    expect(hybrid && "count" in hybrid).toBe(false);
  });

  it("marks a truncated bucket as at-least", () => {
    const [option] = facetOptions([{ value: "a", label: "A", count: 200, countAtLeast: true }]);
    expect(option.countAtLeast).toBe(true);
  });
});

describe("FacetChip (career tri-state row)", () => {
  it("cycles the chip through include, exclude and clear", async () => {
    const user = userEvent.setup();
    render(<Row />);

    const chip = screen.getByTestId("mode-remote");
    expect(chip).toHaveAttribute("role", "checkbox");
    expect(chip).toHaveAttribute("aria-checked", "false");

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "true");
    expect(chip).toHaveAccessibleName(/^Remote, 3$/);

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "true");
    expect(chip).toHaveAccessibleName(/\(excluded\)$/);
    expect(chip).toHaveTextContent("Remote");

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "false");
  });

  it("offers include and exclude by keyboard on the option row", () => {
    render(<Row />);
    const chip = screen.getByTestId("mode-remote");

    fireEvent.keyDown(chip, { key: "Enter" });
    expect(chip).toHaveAttribute("aria-checked", "true");
    expect(chip).toHaveAccessibleName(/^Remote, 3$/);

    fireEvent.keyDown(chip, { key: "Enter", shiftKey: true });
    expect(chip).toHaveAccessibleName(/\(excluded\)$/);

    fireEvent.keyDown(chip, { key: "Delete" });
    expect(chip).toHaveAttribute("aria-checked", "false");
  });

  it("keeps a zero-count value visible and selectable", async () => {
    const user = userEvent.setup();
    render(<Row values={[{ value: "hybrid", label: "Hybrid", count: 0 }]} />);

    const chip = screen.getByTestId("mode-hybrid");
    expect(chip).toHaveTextContent("0");
    expect(chip).not.toBeDisabled();
    expect(chip).not.toHaveAttribute("aria-disabled");

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "true");
  });

  it("prints no number when the facet has no count", () => {
    render(<Row values={[{ value: "remote", label: "Remote" }]} />);
    const chip = screen.getByTestId("mode-remote");
    expect(chip).not.toHaveTextContent(/\d/);
    expect(chip).toHaveAccessibleName("Remote");
  });

  it("treats the null bucket as a real value, not the string", () => {
    render(
      <Row
        values={[{ value: null, label: "Not recorded", count: 4 }]}
      />
    );
    expect(screen.getByTestId("mode-not-recorded")).toHaveTextContent("Not recorded");
    expect(screen.getByTestId("mode-not-recorded")).toHaveTextContent("4");
  });

  it("gives each option a 44px tap target at phone widths", () => {
    render(<Row />);
    expect(screen.getByTestId("mode-remote").className).toContain("max-sm:min-h-11");
  });

  it("offers no exclude affordance on an include-only axis", async () => {
    const user = userEvent.setup();
    render(<Row allowExclude={false} />);
    expect(
      screen.getByTestId("mode-remote").parentElement?.querySelector("button")
    ).toBeNull();
    fireEvent.keyDown(screen.getByTestId("mode-remote"), { key: "Enter", shiftKey: true });
    expect(screen.getByTestId("mode-remote")).toHaveAttribute("aria-checked", "false");

    // 0.93.0 fixes the plain-click cycle at the source: include → clear,
    // never an exclusion this axis' URL has no key for.
    const chip = screen.getByTestId("mode-remote");
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "true");
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-checked", "false");
  });
});

describe("FacetChip counts trust state", () => {
  it("withholds every number and sets aria-busy while counts load", () => {
    render(<Row counts="loading" />);
    const root = screen.getByTestId("mode");
    expect(root).toHaveAttribute("aria-busy", "true");
    const chip = screen.getByTestId("mode-remote");
    expect(chip).not.toHaveTextContent(/\d/);
    expect(chip).toHaveAccessibleName("Remote");
  });

  it("withholds stale numbers after a failed refetch without claiming busy", () => {
    render(<Row counts="error" />);
    const root = screen.getByTestId("mode");
    expect(root).not.toHaveAttribute("aria-busy");
    const chip = screen.getByTestId("mode-remote");
    expect(chip).not.toHaveTextContent(/\d/);
    expect(chip).toHaveAccessibleName("Remote");
  });

  it("renders the counts again once they are ready", () => {
    render(<Row counts="ready" />);
    expect(screen.getByTestId("mode-remote")).toHaveTextContent("3");
  });
});
