import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

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
});
