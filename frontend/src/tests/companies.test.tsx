import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as companiesApi from "@/api/companies";
import { CompanyDetail } from "@/features/companies/pages/CompanyDetail";
import { Companies } from "@/features/companies/pages/Companies";
import type { Company, CompanyDetail as CompanyDetailType, CompanyPosting } from "@/types/wire";

vi.mock("@/api/companies", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/companies")>();
  return {
    ...actual,
    fetchCompanies: vi.fn(),
    fetchCompany: vi.fn(),
    fetchCompanyPostings: vi.fn(),
  };
});

const mocked = vi.mocked(companiesApi);

const COMPANY: Company = {
  key: "acme-cloud",
  name: "Acme Cloud",
  domain: "acme.example",
  status: "active",
  open_postings: 3,
  has_profile: false,
};

const PROPOSED: Company = {
  key: "newborn-works",
  name: "Newborn Works",
  domain: null,
  status: "proposed",
  open_postings: 1,
  has_profile: false,
};

const DETAIL: CompanyDetailType = {
  ...COMPANY,
  aliases: ["Acme Cloud Ltd", "ACME"],
  description: "",
  financials: [],
  links: [],
  needs_review: false,
  derived: {
    open_postings: 3,
    by_seniority: {},
    by_onsite_policy: {},
    top_locations: [],
    latest_posted_at: null,
  },
};

const POSTING = {
  ref: "P3KX9Q2A",
  title: "Backend Engineer",
  location: { city: "Athens", country: "GR", remote: true },
  url: "https://jobs.example/1",
  posted_at: "2026-08-20T00:00:00Z",
  status: "mapped",
} as unknown as CompanyPosting;

describe("Companies browsing (plan 135)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the proposed badge for posting-born companies", async () => {
    mocked.fetchCompanies.mockResolvedValue([COMPANY, PROPOSED]);
    render(
      <MemoryRouter>
        <Companies />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("company-card-acme-cloud")).toBeInTheDocument();
    expect(await screen.findByTestId("company-proposed-newborn-works")).toBeInTheDocument();
    expect(screen.queryByTestId("company-proposed-acme-cloud")).not.toBeInTheDocument();
  });

  it("lists the resolved aliases on the detail page", async () => {
    mocked.fetchCompany.mockResolvedValue(DETAIL);
    mocked.fetchCompanyPostings.mockResolvedValue([POSTING]);
    render(
      <MemoryRouter initialEntries={["/companies/acme-cloud"]}>
        <Routes>
          <Route path="/companies/:key" element={<CompanyDetail />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByTestId("company-aliases")).toHaveTextContent(
      "Acme Cloud Ltd · ACME"
    );
  });

  it("hides the aliases row and the badge when absent", async () => {
    mocked.fetchCompany.mockResolvedValue({ ...DETAIL, aliases: [] });
    mocked.fetchCompanyPostings.mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/companies/acme-cloud"]}>
        <Routes>
          <Route path="/companies/:key" element={<CompanyDetail />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByTestId("company-detail")).toBeInTheDocument();
    expect(screen.queryByTestId("company-aliases")).not.toBeInTheDocument();
    expect(screen.queryByTestId("company-proposed-badge")).not.toBeInTheDocument();
  });
});
