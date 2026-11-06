import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";

import { Companies } from "@/features/companies/pages/Companies";
import {
  rememberCompaniesList,
  peekCompaniesList,
  resetCompaniesListCache,
} from "@/features/companies/companiesListCache";
import { fetchCompanies } from "@/api/companies";
import type { Company } from "@/types/wire";

vi.mock("@/api/companies", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/companies")>();
  return {
    ...mod,
    fetchCompanies: vi.fn(),
  };
});

vi.mock("@/api/stats", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/stats")>();
  return {
    ...actual,
    fetchCompanyStatsSummary: vi.fn().mockResolvedValue({
      as_of: "2026-10-31T12:00:00Z",
      window: "30d",
      status_basis: "open",
      start: null,
      end: "2026-10-31T12:00:00Z",
      companies_hiring: 0,
      new_companies: { count: 0, prev: 0, delta_pct: null, trend: "flat" as const },
    }),
    fetchCompanyStatsOverview: vi.fn().mockResolvedValue({
      as_of: "2026-10-31T12:00:00Z",
      window: "30d",
      status_basis: "open",
      start: null,
      end: "2026-10-31T12:00:00Z",
      top_hiring: [],
      industry_mix: [],
      openings_histogram: [],
    }),
  };
});

const mockFetch = vi.mocked(fetchCompanies);

const COMPANY: Company = {
  key: "acme-cloud",
  name: "Acme Cloud",
  domain: "acme.example",
  status: "active",
  open_postings: 3,
  has_profile: false,
};

function renderCompanies(entry = "/companies") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Companies />
    </MemoryRouter>
  );
}

function PushProbe() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/companies")}>open-companies</button>;
}

describe("Companies list restore (plan 172)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetCompaniesListCache();
    mockFetch.mockResolvedValue({ items: [COMPANY], facets: null });
  });

  it("restores the rendered companies without refetching on return", async () => {
    const firstView = renderCompanies();
    expect(await screen.findByTestId("company-card-acme-cloud")).toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(1);

    firstView.unmount();
    const callsBeforeReturn = mockFetch.mock.calls.length;

    renderCompanies();
    expect(screen.getByTestId("company-card-acme-cloud")).toBeInTheDocument();
    expect(mockFetch.mock.calls.length).toBe(callsBeforeReturn);

    await waitFor(() => {
      expect(mockFetch.mock.calls.length).toBe(callsBeforeReturn);
    });
  });

  it("a filter change refetches after the debounce", async () => {
    const firstView = renderCompanies();
    expect(await screen.findByTestId("company-card-acme-cloud")).toBeInTheDocument();
    firstView.unmount();

    renderCompanies();
    expect(screen.getByTestId("company-card-acme-cloud")).toBeInTheDocument();
    const calls = mockFetch.mock.calls.length;

    mockFetch.mockResolvedValue({
      items: [{ ...COMPANY, key: "beta-works", name: "Beta Works" }],
      facets: null,
    });
    fireEvent.change(screen.getByTestId("company-search"), {
      target: { value: "beta" },
    });

    await waitFor(() => {
      expect(mockFetch.mock.calls.length).toBeGreaterThan(calls);
    });
    expect(await screen.findByTestId("company-card-beta-works")).toBeInTheDocument();
  });

  it("a fresh navigation refetches instead of serving the session snapshot", async () => {
    rememberCompaniesList("0|", {
      companies: [{ ...COMPANY, key: "stale-co", name: "Stale Co" }],
      facets: null,
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<PushProbe />} />
          <Route path="/companies" element={<Companies />} />
        </Routes>
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("open-companies"));

    expect(await screen.findByTestId("company-card-acme-cloud")).toBeInTheDocument();
    expect(screen.queryByTestId("company-card-stale-co")).not.toBeInTheDocument();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("a profile-scoped snapshot key restores only its own epoch", () => {
    rememberCompaniesList("7|status=new", {
      companies: [{ ...COMPANY, key: "epoch-seven" }],
      facets: null,
    });
    expect(peekCompaniesList("7|status=new")?.companies[0].key).toBe(
      "epoch-seven"
    );
    expect(peekCompaniesList("0|status=new")).toBeNull();
  });
});
