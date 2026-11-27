import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as filters from "@neuronection/assistant-ui/filters";
import { FilterRail, FilterSection, FacetChip } from "@neuronection/assistant-ui/filters";

import { FilterRailSearch } from "@/components/filters/FilterRailSearch";
import { expectNoA11yViolations } from "@/tests/a11y";
import { facetOptions, multiValue, railLayout } from "@/lib/filterFacets";

describe("@neuronection/assistant-ui/filters", () => {
  it("resolves the subpath and exports the four adopted components", () => {
    expect(filters.FilterRail).toBeDefined();
    expect(filters.FilterSection).toBeDefined();
    expect(filters.FacetChip).toBeDefined();
    expect(filters.FilterPills).toBeDefined();
  });
});

describe("railLayout", () => {
  it("maps the wide page band to the rail and every narrower band to compact", () => {
    expect(railLayout("wide")).toBe("rail");
    expect(railLayout("medium")).toBe("compact");
    expect(railLayout("compact")).toBe("compact");
    expect(railLayout()).toBe("rail");
  });
});

describe("FilterRail", () => {
  it("renders the shared rail with a title, active count and clear action", () => {
    const onClear = vi.fn();
    render(
      <FilterRail
        layout="rail"
        title="Filters"
        activeCount={2}
        onClear={onClear}
        className="ca-stats-rail"
        data-testid="rail-aside"
      >
        <p>body</p>
      </FilterRail>
    );

    const aside = screen.getByTestId("rail-aside");
    expect(aside.tagName).toBe("ASIDE");
    expect(aside).toHaveClass("ca-stats-rail");
    expect(aside).toHaveAttribute("data-layout", "rail");
    expect(screen.getByRole("heading", { name: "Filters" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();

    const count = aside.querySelector('[data-as="filter-rail-count"]');
    expect(count).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: /Clear all/ }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("hides the count and clear action when no filter is active", () => {
    render(
      <FilterRail layout="rail" title="Filters" data-testid="rail-aside">
        <p>body</p>
      </FilterRail>
    );

    const aside = screen.getByTestId("rail-aside");
    expect(aside.querySelector('[data-as="filter-rail-count"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /Clear all/ })).not.toBeInTheDocument();
  });

  it("never renders a zero badge", () => {
    render(
      <FilterRail layout="rail" title="Filters" data-testid="rail-aside">
        <p>body</p>
      </FilterRail>
    );
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders the shared search field", () => {
    const onChange = vi.fn();
    render(
      <FilterRailSearch
        label="Search"
        value=""
        onChange={onChange}
        placeholder="Search jobs…"
        testId="rail-search"
      />
    );

    expect(screen.getByText("Search")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("rail-search"), { target: { value: "nurse" } });
    expect(onChange).toHaveBeenCalledWith("nurse");
  });

  it("keeps the inline rail and never renders a trigger at the wide band", () => {
    render(
      <FilterRail
        layout={railLayout("wide")}
        title="Filters"
        search={<input data-testid="rail-search" />}
      >
        <p>body</p>
      </FilterRail>
    );

    expect(screen.getByText("body")).toBeInTheDocument();
    expect(screen.getByTestId("rail-search")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Filters/ })).not.toBeInTheDocument();
  });

  it("collapses below the wide band into a Filters button and a sheet", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(
      <FilterRail
        layout={railLayout("compact")}
        title="Filters"
        activeCount={2}
        onClear={onClear}
        data-testid="rail-aside"
        search={<input data-testid="rail-search" />}
      >
        <FilterSection title="Sections">
          <p>sections</p>
        </FilterSection>
      </FilterRail>
    );

    expect(screen.getByTestId("rail-aside")).toHaveAttribute("data-layout", "compact");
    expect(screen.getByTestId("rail-search")).toBeInTheDocument();
    expect(screen.queryByText("sections")).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: "Filters (2)" });
    await user.click(trigger);

    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    expect(within(sheet).getByText("sections")).toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Filters" })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(
      within(await screen.findByRole("dialog", { name: "Filters" })).getByRole("button", {
        name: /Clear all/,
      })
    );
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("hides the compact badge and clear action when nothing is filtered", async () => {
    const user = userEvent.setup();
    render(
      <FilterRail layout="compact" title="Filters">
        <p>sections</p>
      </FilterRail>
    );

    const trigger = screen.getByRole("button", { name: "Filters" });
    await user.click(trigger);
    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    expect(within(sheet).getByRole("button", { name: "Done" })).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: /Clear all/ })).not.toBeInTheDocument();
  });

  it("closes the compact sheet from a function footer and returns focus", async () => {
    const user = userEvent.setup();
    render(
      <FilterRail
        layout="compact"
        title="Filters"
        activeCount={1}
        onClear={() => {}}
        footer={(close) => (
          <button type="button" onClick={close}>
            Show 3 jobs
          </button>
        )}
      >
        <p>sections</p>
      </FilterRail>
    );

    const trigger = screen.getByRole("button", { name: "Filters (1)" });
    await user.click(trigger);

    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    await user.click(within(sheet).getByRole("button", { name: "Show 3 jobs" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Filters" })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();
  });
});

describe("FilterSection", () => {

  it("collapses an active section without forcing it open", async () => {
    const user = userEvent.setup();
    render(
      <FilterSection title="Seniority" active>
        <p>body</p>
      </FilterSection>
    );

    const header = screen.getByRole("button", { name: /Seniority/ });
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("body")).not.toBeVisible();

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("body")).toBeVisible();
  });

  it("renders a real zero and no badge when the count is unknown", () => {
    const { rerender } = render(<FilterSection title="Industries" count={0} />);
    expect(
      document.querySelector('[data-as="filter-section-count"]')
    ).toHaveTextContent("0");

    rerender(<FilterSection title="Industries" />);
    expect(document.querySelector('[data-as="filter-section-count"]')).toBeNull();
  });

  it("renders a truncated bucket as ≥N", () => {
    render(<FilterSection title="Skills" count={200} countAtLeast />);
    expect(
      document.querySelector('[data-as="filter-section-count"]')
    ).toHaveTextContent("≥200");
  });
});

describe("rail accessibility", () => {
  const FACET = { id: "seniority", label: "Seniority", kind: "multi" as const };

  function Rail({ layout }: { layout: "rail" | "compact" }) {
    return (
      <FilterRail layout={layout} title="Filters" activeCount={1} onClear={() => {}}>
        <FilterSection title="Seniority" active>
          <FacetChip
            facet={{ ...FACET, options: facetOptions([{ value: "mid", label: "Mid", count: 2 }]) }}
            value={multiValue(["mid"])}
            variant="inline"
            showActivePills={false}
            onToggleOption={() => {}}
            optionTestId={(value) => `seniority-${value}`}
          />
        </FilterSection>
      </FilterRail>
    );
  }

  it("has no axe violations in the rail", async () => {
    const { container } = render(<Rail layout="rail" />);
    await expectNoA11yViolations(container);
  });

  it("has no axe violations in the open compact sheet", async () => {
    const user = userEvent.setup();
    const { container } = render(<Rail layout="compact" />);
    await user.click(screen.getByRole("button", { name: "Filters (1)" }));
    await screen.findByRole("dialog", { name: "Filters" });
    await expectNoA11yViolations(container, {
      rules: { "aria-hidden-focus": { enabled: true } },
    });
  });

  it("opens the sheet from the keyboard and returns focus on Escape", async () => {
    const user = userEvent.setup();
    render(<Rail layout="compact" />);

    const trigger = screen.getByRole("button", { name: "Filters (1)" });
    await user.tab();
    expect(trigger).toHaveFocus();

    await user.keyboard("{Enter}");
    const sheet = await screen.findByRole("dialog", { name: "Filters" });
    expect(sheet).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Filters" })).not.toBeInTheDocument()
    );
    expect(trigger).toHaveFocus();
  });

  it("keeps 44px targets in both layouts (390px contract)", () => {
    render(<Rail layout="rail" />);
    const header = screen.getByRole("button", { name: /Seniority/ });
    expect(header.className).toContain("min-h-[44px]");
    expect(screen.getByTestId("seniority-mid").className).toContain("max-sm:min-h-11");
  });
});
