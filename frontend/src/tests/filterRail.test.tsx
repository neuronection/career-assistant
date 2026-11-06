import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FilterRail, FilterRailSearch } from "@/components/filters/FilterRail";

describe("FilterRail", () => {
  it("renders the shared shell with a title, active count and clear action", () => {
    const onClear = vi.fn();
    render(
      <FilterRail
        title="Filters"
        activeCount={2}
        onClear={onClear}
        countTestId="rail-count"
        clearTestId="rail-clear"
        asideTestId="rail-aside"
        testId="rail-panel"
      >
        <p>body</p>
      </FilterRail>
    );

    const aside = screen.getByTestId("rail-aside");
    expect(aside).toHaveClass("ca-stats-rail");
    expect(aside).toHaveAttribute("aria-label", "Filters");
    expect(screen.getByTestId("rail-panel").parentElement).toBe(aside);
    expect(screen.getByTestId("rail-panel")).toHaveTextContent("body");
    expect(screen.getByTestId("rail-count")).toHaveTextContent("2 active");

    fireEvent.click(screen.getByTestId("rail-clear"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("hides the count and clear action when no filter is active", () => {
    render(
      <FilterRail title="Filters" countTestId="rail-count" clearTestId="rail-clear">
        <p>body</p>
      </FilterRail>
    );

    expect(screen.queryByTestId("rail-count")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rail-clear")).not.toBeInTheDocument();
  });

  it("passes the below-breakpoint panel state and extra aside classes", () => {
    render(
      <FilterRail
        title="Filters"
        asideTestId="rail-aside"
        asideClassName="ca-ap-filter-rail"
        asideOpen
      >
        <p>body</p>
      </FilterRail>
    );

    const aside = screen.getByTestId("rail-aside");
    expect(aside).toHaveClass("ca-stats-rail", "ca-ap-filter-rail");
    expect(aside).toHaveAttribute("data-open", "true");
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
      <FilterRail title="Filters" band="wide" search={<input data-testid="rail-search" />}>
        <p>body</p>
      </FilterRail>
    );

    expect(screen.getByText("body")).toBeInTheDocument();
    expect(screen.getByTestId("rail-search")).toBeInTheDocument();
    expect(screen.queryByTestId("filters-open")).not.toBeInTheDocument();
  });

  it("collapses below the wide band into a Filters button and a sheet", async () => {
    const user = userEvent.setup();
    const onClear = vi.fn();
    render(
      <FilterRail
        title="Filters"
        band="compact"
        activeCount={2}
        onClear={onClear}
        countTestId="rail-count"
        clearTestId="rail-clear"
        asideTestId="rail-aside"
        testId="rail-panel"
        triggerTestId="rail-open"
        sheetTestId="rail-sheet"
        resultCount={7}
        search={<input data-testid="rail-search" />}
      >
        <p>sections</p>
      </FilterRail>
    );

    expect(screen.getByTestId("rail-aside")).toHaveAttribute("data-band", "compact");
    expect(screen.getByTestId("rail-search")).toBeInTheDocument();
    expect(screen.getByTestId("rail-count")).toHaveTextContent("2");
    expect(screen.queryByText("sections")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("rail-open"));
    const sheet = await screen.findByTestId("rail-sheet");
    expect(within(sheet).getByText("sections")).toBeInTheDocument();
    expect(within(sheet).getByText("2 active")).toBeInTheDocument();
    expect(screen.getByTestId("rail-sheet-done")).toHaveTextContent("Show 7 jobs");

    await user.click(screen.getByTestId("rail-sheet-done"));
    await waitFor(() => expect(screen.queryByTestId("rail-sheet")).not.toBeInTheDocument());

    await user.click(screen.getByTestId("rail-open"));
    await user.click(await screen.findByTestId("rail-clear"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("hides the compact badge and clear action when nothing is filtered", async () => {
    const user = userEvent.setup();
    render(
      <FilterRail
        title="Filters"
        band="medium"
        onClear={vi.fn()}
        countTestId="rail-count"
        clearTestId="rail-clear"
        triggerTestId="rail-open"
        sheetTestId="rail-sheet"
      >
        <p>sections</p>
      </FilterRail>
    );

    expect(screen.queryByTestId("rail-count")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("rail-open"));
    expect(await screen.findByTestId("rail-sheet-done")).toHaveTextContent("Done");
    expect(screen.queryByTestId("rail-clear")).not.toBeInTheDocument();
  });
});
