import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { MarketGuide } from "@/features/career/pages/MarketGuide";
import {
  GRADE_ROWS,
  MARKETS,
  MARKET_GUIDE_REVIEWED,
} from "@/features/career/marketPacks";

describe("MarketGuide", () => {
  it("renders the sourced grade orientation and switches markets", () => {
    render(<MarketGuide />);
    expect(screen.getByTestId("market-guide")).toHaveTextContent(
      "Grade orientation: UK and DACH"
    );
    expect(screen.getByTestId("market-guide-grades")).toHaveTextContent(
      "First (70–100%)"
    );
    expect(screen.getByTestId("market-guide-cv")).toHaveTextContent(
      "Use a clear, consistent layout"
    );
    expect(screen.getByTestId("market-guide")).toHaveTextContent(
      "not legal or immigration advice"
    );
    expect(screen.getByTestId("market-guide")).toHaveTextContent(
      /Sources reviewed/
    );
    expect(
      within(screen.getByTestId("market-guide-cv")).getByRole("link", {
        name: /National Careers Service/,
      })
    ).toHaveAttribute(
      "href",
      "https://nationalcareers.service.gov.uk/careers-advice/cv-sections"
    );

    fireEvent.click(screen.getByRole("tab", { name: "Germany" }));
    expect(screen.getByTestId("market-guide-cv")).toHaveTextContent(
      "tabular CV"
    );
    expect(screen.getByTestId("market-guide-norms")).toHaveTextContent(
      "complete Bewerbung"
    );

    fireEvent.click(screen.getByRole("tab", { name: "Austria" }));
    expect(screen.getByTestId("market-guide-cv")).toHaveTextContent(
      "tabular CV"
    );
    expect(screen.getByTestId("market-guide-norms")).toHaveTextContent("AMS");

    fireEvent.click(screen.getByRole("tab", { name: "Switzerland" }));
    expect(screen.getByTestId("market-guide-grades")).toHaveTextContent(
      "Swiss grades run from 6.0"
    );
    expect(screen.getByRole("link", { name: /ch\.ch/ })).toHaveAttribute(
      "href",
      "https://www.ch.ch/en/foreign-nationals-in-switzerland/working-in-switzerland/"
    );
  });

  it("ships dated, https sources for every market", () => {
    expect(MARKET_GUIDE_REVIEWED).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(new Set(MARKETS.map((market) => market.id)).size).toBe(MARKETS.length);
    expect(GRADE_ROWS).toHaveLength(4);
    for (const market of MARKETS) {
      expect(market.sources.length).toBeGreaterThanOrEqual(2);
      expect(new Set(market.sources.map((source) => source.section))).toEqual(
        new Set(["cv", "norms", "cycle"])
      );
      for (const source of market.sources) {
        expect(source.url).toMatch(/^https:\/\//);
      }
    }
  });
});
