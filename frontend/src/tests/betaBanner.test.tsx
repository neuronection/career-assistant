import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { BetaBanner } from "@/components/BetaBanner";

describe("BetaBanner", () => {
  it("chips a beta surface with the shared expectation line", () => {
    render(<BetaBanner pathname="/autopilot" />);
    expect(screen.getByTestId("beta-chip")).toHaveTextContent("Beta");
    expect(screen.getByTestId("beta-banner")).toHaveTextContent(
      "expect rough edges"
    );
    expect(screen.getByTestId("beta-banner")).toHaveAttribute(
      "data-feature",
      "/autopilot"
    );
  });

  it("stays out of the way on a shipped surface", () => {
    const { container } = render(<BetaBanner pathname="/catalog" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("follows nested routes to their registered prefix", () => {
    render(<BetaBanner pathname="/paths/nested" />);
    expect(screen.getByTestId("beta-banner")).toHaveAttribute(
      "data-feature",
      "/paths"
    );
  });
});
