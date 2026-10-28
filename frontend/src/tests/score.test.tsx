import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ScoreBreakdown, type BreakdownDimension } from "@/components/score/ScoreBreakdown";
import { ScoreBubble } from "@/components/score/ScoreBubble";

describe("ScoreBubble", () => {
  it("bands the ring by score", () => {
    const { rerender } = render(<ScoreBubble score={8.4} />);
    expect(screen.getByTestId("score-ring")).toHaveAttribute("data-tone", "success");
    rerender(<ScoreBubble score={5.5} />);
    expect(screen.getByTestId("score-ring")).toHaveAttribute("data-tone", "warning");
    rerender(<ScoreBubble score={2.1} />);
    expect(screen.getByTestId("score-ring")).toHaveAttribute("data-tone", "danger");
  });

  it("renders a muted dash without a score", () => {
    render(<ScoreBubble score={null} />);
    const bubble = screen.getByTestId("score-ring");
    expect(bubble).toHaveAttribute("data-tone", "muted");
    expect(bubble).toHaveTextContent("–");
    expect(screen.getByRole("img", { name: /no score/i })).toBeInTheDocument();
  });
});

const DIMENSIONS: BreakdownDimension[] = [
  { key: "skills", label: "Skills", score: 8.8, weight: 3, detail: "6 of 7 covered" },
  { key: "location", label: "Location", score: 5, weight: 1, detail: "" },
];

describe("ScoreBreakdown", () => {
  it("hides the default weight and shows the rest", () => {
    render(<ScoreBreakdown dimensions={DIMENSIONS} defaultWeight={3} />);
    expect(screen.getByText("8.8")).toBeInTheDocument();
    expect(screen.queryByText("×3")).not.toBeInTheDocument();
    expect(screen.getByText("×1")).toBeInTheDocument();
  });

  it("shows every weight in alwaysShowWeight mode", () => {
    render(<ScoreBreakdown dimensions={DIMENSIONS} alwaysShowWeight />);
    expect(screen.getByText("×3")).toBeInTheDocument();
    expect(screen.getByText("×1")).toBeInTheDocument();
  });

  it("renders detail lines when asked", () => {
    render(
      <ScoreBreakdown
        dimensions={DIMENSIONS}
        defaultWeight={3}
        showDetails
        detailsLayout="inline"
        detailsTestId="fit-detail"
      />
    );
    expect(screen.getByTestId("fit-detail")).toHaveTextContent(
      "Skills: 6 of 7 covered"
    );
  });

  it("renders one detail line per dimension in lines mode", () => {
    render(
      <ScoreBreakdown
        dimensions={DIMENSIONS}
        showDetails
        detailsLayout="lines"
        detailsTestId="match-details"
      />
    );
    expect(screen.getByTestId("match-details").querySelectorAll("p")).toHaveLength(1);
  });
});
