import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { OfferComparisonPage } from "@/features/postings/pages/OfferComparisonPage";
import { fetchOfferComparison } from "@/api/offers";

vi.mock("@/api/offers", () => ({ fetchOfferComparison: vi.fn() }));

const DATA = {
  total: 2,
  mixed_currencies: false,
  items: [
    {
      application_id: "a1",
      posting_title: "Data analyst",
      posting_org: "Alpha",
      currency: "EUR",
      amount: 60000,
      period: "year" as const,
      annual_amount: 60000,
      monthly_amount: 5000,
      cost_of_living: 1000,
      annual_cost_of_living: 12000,
      net_annual_after_col: 48000,
      benefits: ["health insurance"],
      location: "Berlin",
      deadline: "2026-12-01",
    },
    {
      application_id: "a2",
      posting_title: "BI engineer",
      posting_org: "Beta",
      currency: "EUR",
      amount: 4500,
      period: "month" as const,
      annual_amount: 54000,
      monthly_amount: 4500,
      cost_of_living: null,
      annual_cost_of_living: null,
      net_annual_after_col: null,
      benefits: [],
      location: "",
      deadline: null,
    },
  ],
};

const originalTz = process.env.TZ;

beforeAll(() => {
  process.env.TZ = "America/New_York";
});

afterAll(() => {
  process.env.TZ = originalTz;
});

describe("OfferComparisonPage", () => {
  beforeEach(() => {
    vi.mocked(fetchOfferComparison).mockResolvedValue(DATA);
  });

  it("shows a retryable error instead of the empty state when loading fails", async () => {
    vi.mocked(fetchOfferComparison).mockRejectedValueOnce(
      new Error("network down")
    );
    render(
      <MemoryRouter>
        <OfferComparisonPage />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("offers-error")).toHaveTextContent(
      "Could not load your offers"
    );
    expect(screen.queryByText("No offers to compare yet")).toBeNull();

    vi.mocked(fetchOfferComparison).mockResolvedValue(DATA);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByTestId("offers-page")).toHaveTextContent(
      "Data analyst"
    );
  });

  it("shows annualized pay, cost of living, benefits and missing values", async () => {
    render(
      <MemoryRouter>
        <OfferComparisonPage />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("offers-page")).toHaveTextContent(
      "Compare offers"
    );
    expect(screen.getByTestId("offer-header-a1")).toHaveTextContent("Data analyst");
    expect(screen.getByTestId("offers-page")).toHaveTextContent("€60,000");
    expect(screen.getByTestId("offers-page")).toHaveTextContent("€48,000");
    expect(screen.getByTestId("offers-page")).toHaveTextContent("health insurance");
    expect(screen.getByTestId("offers-page")).toHaveTextContent("12/1/2026");
    expect(screen.getByTestId("offers-page")).not.toHaveTextContent("11/30/2026");
    expect(screen.getByTestId("offers-page")).toHaveTextContent("—");
  });

  it("renders a date-only deadline on its UTC day west of UTC", async () => {
    vi.mocked(fetchOfferComparison).mockResolvedValue({
      ...DATA,
      items: [DATA.items[0]],
      total: 1,
    });
    render(
      <MemoryRouter>
        <OfferComparisonPage />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("offers-page")).toHaveTextContent("12/1/2026");
    expect(screen.getByTestId("offers-page")).not.toHaveTextContent("11/30/2026");
  });

  it("flags mixed currencies and renders the empty state", async () => {
    vi.mocked(fetchOfferComparison).mockResolvedValue({
      ...DATA,
      mixed_currencies: true,
    });
    render(
      <MemoryRouter>
        <OfferComparisonPage />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("offers-mixed-currency")).toHaveTextContent(
      "different currencies"
    );

    vi.mocked(fetchOfferComparison).mockResolvedValue({
      items: [],
      total: 0,
      mixed_currencies: false,
    });
    render(
      <MemoryRouter>
        <OfferComparisonPage />
      </MemoryRouter>
    );
    expect(await screen.findByText("No offers to compare yet")).toBeInTheDocument();
  });
});
