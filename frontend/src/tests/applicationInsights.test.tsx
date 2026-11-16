import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ApplicationInsightsCard } from "@/features/postings/components/applications/ApplicationInsightsCard";
import { fetchApplicationInsights } from "@/api/applications";

vi.mock("@/api/applications", () => ({
  fetchApplicationInsights: vi.fn(),
}));

const DATA = {
  tailored: { n: 12, responses: 6, rate: 0.5 },
  untailored: { n: 20, responses: 4, rate: 0.2 },
  suppressed: false,
  floor: 10,
  caveat: "Association only.",
  next_action: "Tailor the next one.",
};

describe("ApplicationInsightsCard", () => {
  beforeEach(() => {
    vi.mocked(fetchApplicationInsights).mockResolvedValue(DATA);
  });

  it("shows rates, n and next action", async () => {
    render(<ApplicationInsightsCard />);
    const rates = await screen.findByTestId("insights-rates");
    expect(rates).toHaveTextContent("50%");
    expect(rates).toHaveTextContent("20%");
    expect(rates).toHaveTextContent("n = 12");
    expect(screen.getByTestId("insights-next")).toHaveTextContent("Tailor the next one.");
  });

  it("shows the suppression message instead of a rate", async () => {
    vi.mocked(fetchApplicationInsights).mockResolvedValue({
      ...DATA,
      suppressed: true,
      tailored: { n: 3, responses: 1, rate: null },
    });
    render(<ApplicationInsightsCard />);
    expect(await screen.findByTestId("insights-suppressed")).toHaveTextContent("at least 10");
    expect(screen.queryByTestId("insights-rates")).not.toBeInTheDocument();
  });
});
