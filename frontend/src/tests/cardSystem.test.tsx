import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { ChipRow, fitChips, rowsFor } from "@/components/cards/ChipRow";
import { ClosedMark, SeenMark } from "@/components/cards/CardState";
import { ItemCardShell } from "@/components/cards/ItemCardShell";

const ITEMS = [
  { key: "a", label: "Alpha" },
  { key: "b", label: "Beta" },
  { key: "c", label: "Gamma" },
  { key: "d", label: "Delta" },
];

describe("fitChips", () => {
  it("keeps everything when it fits in the row budget", () => {
    expect(rowsFor([100, 100], 400, 4)).toBe(1);
    expect(fitChips([100, 100], 400, 4, 40, 2)).toBe(2);
  });

  it("reserves the last slot for the overflow chip", () => {
    // only one 120px chip plus the "+N" chip fits 130px in two rows, so the
    // last slot stays free for the count.
    expect(rowsFor([120, 120, 120], 130, 4)).toBe(3);
    expect(fitChips([120, 120, 120], 130, 4, 30, 2)).toBe(1);
  });

  it("falls back to showing everything without a measurable width", () => {
    expect(fitChips([100, 100, 100], 0, 4, 30, 2)).toBe(3);
  });
});

describe("ItemCardShell", () => {
  it("opens on a card click, including the title button, but not from actions", () => {
    const onOpen = vi.fn();
    render(
      <ItemCardShell
        testId="shell"
        onOpen={onOpen}
        actions={<button data-testid="action">Act</button>}
      >
        <button data-testid="title">Title</button>
      </ItemCardShell>
    );
    fireEvent.click(screen.getByTestId("shell"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("title"));
    expect(onOpen).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByTestId("action"));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("marks seen and closed state without dimming the card", () => {
    render(
      <ItemCardShell testId="closed" state="closed" seen>
        <span>body</span>
      </ItemCardShell>
    );
    const card = screen.getByTestId("closed");
    expect(card).toHaveAttribute("data-state", "closed");
    expect(card).toHaveAttribute("data-seen", "true");
    expect(card.className).not.toContain("opacity");
  });
});

describe("ChipRow", () => {
  it("caps at max and expands from the +N chip", () => {
    render(<ChipRow testId="chips" max={2} items={ITEMS} showLessLabel="less" />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Gamma")).not.toBeInTheDocument();
    const more = screen.getByTestId("chips-more");
    expect(more).toHaveAttribute("aria-label", "+2");
    fireEvent.click(more);
    expect(screen.getByText("Gamma")).toBeInTheDocument();
    expect(screen.getByTestId("chips-less")).toBeInTheDocument();
  });

  it("clamps through the injected measurement and expands from +N", () => {
    const items = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"].map(
      (label) => ({ key: label.toLowerCase(), label })
    );
    render(
      <ChipRow
        clampRows={2}
        testId="skills"
        showLessLabel="less"
        measure={{
          widths: items.map(() => 60),
          containerWidth: 200,
          moreWidth: 30,
        }}
        items={items}
      />
    );
    const more = screen.getByTestId("skills-more");
    expect(more).toHaveTextContent("+3");
    expect(more).toHaveAttribute("title", "Foxtrot, Golf, Hotel");
    fireEvent.click(more);
    expect(within(screen.getByTestId("skills")).getByText("Hotel")).toBeInTheDocument();
    expect(screen.getByTestId("skills-less")).toBeInTheDocument();
  });

  it("keeps capped labels available to screen readers", () => {
    render(<ChipRow testId="tags" max={2} items={ITEMS} />);
    expect(screen.getByTestId("tags-more")).toHaveAttribute(
      "title",
      "Gamma, Delta"
    );
    expect(screen.getByText("Gamma, Delta")).toHaveClass("sr-only");
  });

  it("renders skill chips with heat and score", () => {
    render(
      <ChipRow
        variant="skill"
        testId="skills"
        itemTestId="skill-tag"
        items={[{ key: "ts", label: "TypeScript", score: 8 }]}
      />
    );
    const chip = screen.getByTestId("skill-tag");
    expect(chip).toHaveAttribute("data-heat", "hot");
    expect(chip).toHaveTextContent("TypeScript");
    expect(chip).toHaveTextContent("8");
  });
});

describe("state markers", () => {
  it("renders the seen mark quietly with an accessible label", () => {
    render(<SeenMark label="Seen" />);
    const mark = screen.getByTestId("card-seen");
    expect(mark).toHaveAttribute("title", "Seen");
    expect(screen.getByText("Seen")).toHaveClass("sr-only");
  });

  it("renders the closed mark with its close date tooltip", () => {
    render(<ClosedMark label="Closed" title="Closed 12 Oct 2026" />);
    expect(screen.getByTestId("posting-closed")).toHaveAttribute(
      "title",
      "Closed 12 Oct 2026"
    );
  });
});
