import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  SelectionEntry,
  SelectionToolbar,
} from "@/features/selection/SelectionToolbar";
import { useListSelection } from "@/features/selection/useListSelection";
import { expectNoA11yViolations } from "@/tests/a11y";

const ALL = ["a", "b", "c", "d", "e", "f"];

function Harness({ onShowHidden }: { onShowHidden?: () => void }) {
  const [narrowed, setNarrowed] = useState(false);
  const matchingIds = narrowed ? ["a", "b"] : ALL;
  const selection = useListSelection({ allIds: ALL, matchingIds });
  return (
    <div>
      <button type="button" data-testid="narrow" onClick={() => setNarrowed((v) => !v)}>
        narrow
      </button>
      <input aria-label="notes" />
      <SelectionEntry prefix="t" selection={selection} />
      <SelectionToolbar
        prefix="t"
        selection={selection}
        allIds={ALL}
        matchingIds={matchingIds}
        scopes={[{ key: "proposed", label: "All 3 proposed", ids: ["a", "b", "c"] }]}
        actions={
          <button type="button" data-testid="t-action" disabled={selection.count === 0}>
            Act ({selection.count})
          </button>
        }
        onShowHidden={onShowHidden}
      />
    </div>
  );
}

describe("SelectionToolbar", () => {
  it("enters the mode from the shared entry and shows the empty frame", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByTestId("t-bulk-bar")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("t-select"));
    const bar = screen.getByTestId("t-bulk-bar");
    expect(within(bar).getByText(/Selection mode — 6 available/)).toBeInTheDocument();
    expect(
      within(bar).getByRole("checkbox", { name: "Select all 6" })
    ).toBeInTheDocument();
  });

  it("names the filtered scope and selects exactly the matching rows", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("t-select"));
    await user.click(screen.getByTestId("narrow"));

    const bar = screen.getByTestId("t-bulk-bar");
    const selectAll = () =>
      within(screen.getByTestId("t-bulk-bar")).getByRole("checkbox", {
        name: "Select all 2 matching",
      });
    await user.click(selectAll());
    expect(within(bar).getByTestId("t-bulk-count")).toHaveTextContent("2 selected");
    expect(within(bar).getByTestId("t-action")).not.toBeDisabled();

    await user.click(selectAll());
    expect(within(bar).getByTestId("t-bulk-mode")).toHaveTextContent(
      "Selection mode — 2 available"
    );
  });

  it("offers named scopes and the loaded set from the scope menu", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("t-select"));
    await user.click(screen.getByTestId("narrow"));

    await user.click(screen.getByTestId("t-bulk-scope"));
    await user.click(screen.getByTestId("t-bulk-scope-proposed"));
    expect(screen.getByTestId("t-bulk-count")).toHaveTextContent("3 selected");

    await user.click(screen.getByTestId("t-bulk-scope"));
    await user.click(screen.getByTestId("t-bulk-scope-loaded"));
    expect(screen.getByTestId("t-bulk-count")).toHaveTextContent("6 selected");
  });

  it("surfaces selections hidden by the filter and can drop them", async () => {
    const user = userEvent.setup();
    const onShowHidden = vi.fn();
    render(<Harness onShowHidden={onShowHidden} />);
    await user.click(screen.getByTestId("t-select"));
    await user.click(screen.getByRole("checkbox", { name: "Select all 6" }));

    await user.click(screen.getByTestId("narrow"));
    const hidden = screen.getByTestId("t-bulk-hidden");
    expect(hidden).toHaveTextContent("4 hidden by filters");

    await user.click(screen.getByTestId("t-bulk-hidden-show"));
    expect(onShowHidden).toHaveBeenCalledTimes(1);

    await user.click(screen.getByTestId("t-bulk-hidden-drop"));
    expect(screen.getByTestId("t-bulk-count")).toHaveTextContent("2 selected");
    expect(screen.queryByTestId("t-bulk-hidden")).not.toBeInTheDocument();
  });

  it("clears through the selection bar's clear control", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("t-select"));
    await user.click(screen.getByRole("checkbox", { name: "Select all 6" }));
    expect(screen.getByTestId("t-bulk-count")).toHaveTextContent("6 selected");

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("Selection mode — 6 available")).toBeInTheDocument();
  });

  it("exits on Escape and selects matching on Ctrl/Cmd+A outside fields", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByTestId("t-select"));

    fireEvent.keyDown(screen.getByLabelText("notes"), {
      key: "a",
      ctrlKey: true,
    });
    expect(screen.getByText("Selection mode — 6 available")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "a", ctrlKey: true });
    expect(await screen.findByTestId("t-bulk-count")).toHaveTextContent("6 selected");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("t-bulk-bar")).not.toBeInTheDocument();
  });

  it("ignores Ctrl/Cmd+A until the mode is on", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    fireEvent.keyDown(document, { key: "a", ctrlKey: true });
    await user.click(screen.getByTestId("t-select"));
    expect(screen.getByTestId("t-bulk-mode")).toHaveTextContent(
      "Selection mode — 6 available"
    );
  });

  it("has no axe violations in either bar state", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await user.click(screen.getByTestId("t-select"));
    await user.click(screen.getByRole("checkbox", { name: "Select all 6" }));
    await expectNoA11yViolations(container);
  });
});
