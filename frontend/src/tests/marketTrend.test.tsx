import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { MarketTrendStrip } from "@/components/MarketTrendStrip";
import type { MarketTrendPoint } from "@/api/growth";

vi.mock("recharts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("recharts")>();
  return {
    ...mod,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div>{children}</div>
    ),
  };
});

function point(date: string, p25: number, p75: number): MarketTrendPoint {
  return {
    capture_date: date,
    sample_size: 12,
    thin_sample: false,
    salary_band: { p25, p75 },
  };
}

function renderStrip(history: MarketTrendPoint[]) {
  return render(
    <MemoryRouter>
      <MarketTrendStrip history={history} />
    </MemoryRouter>
  );
}

describe("MarketTrendStrip", () => {
  it("renders with two or more snapshots", () => {
    renderStrip([point("2026-09-01", 40000, 60000), point("2026-09-08", 42000, 63000)]);
    expect(screen.getByTestId("market-trend")).toBeTruthy();
    expect(screen.getByText(/2 daily snapshots/)).toBeTruthy();
  });

  it("renders nothing below two snapshots", () => {
    const { container } = renderStrip([point("2026-09-01", 40000, 60000)]);
    expect(container.querySelector('[data-testid="market-trend"]')).toBeNull();
  });
});
