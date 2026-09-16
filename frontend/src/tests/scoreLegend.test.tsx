import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ScoreLegend } from "@/components/ScoreLegend";

describe("ScoreLegend", () => {
  it("opens and explains the score layers", () => {
    render(<ScoreLegend />);
    expect(screen.queryByTestId("score-info-panel")).toBeNull();
    fireEvent.click(screen.getByTestId("score-info"));
    const panel = screen.getByTestId("score-info-panel");
    expect(panel).toHaveTextContent("How scores work");
    expect(panel).toHaveTextContent("60% fit + 40% AI");
    expect(panel).toHaveTextContent("Adjust weights");
    expect(panel).toHaveTextContent("It never changes the ranking order.");
    expect(panel).toHaveTextContent("skipped, not scored");
  });
});
