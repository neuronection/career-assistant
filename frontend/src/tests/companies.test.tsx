import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import * as companiesApi from "@/api/companies";
import * as postingsApi from "@/api/postings";
import { CompanyDetail } from "@/features/companies/pages/CompanyDetail";
import { Companies } from "@/features/companies/pages/Companies";
import type { Company, CompanyDetail as CompanyDetailType } from "@/types/wire";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/companies", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/companies")>();
  return {
    ...actual,
    fetchCompanies: vi.fn(),
    fetchCompany: vi.fn(),
  };
});

vi.mock("@/api/postings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...actual,
    fetchPostings: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    markApplied: vi.fn().mockResolvedValue({}),
    savePosting: vi.fn().mockResolvedValue({}),
    hidePosting: vi.fn().mockResolvedValue({}),
  };
});

const mocked = vi.mocked(companiesApi);
const mockedPostings = vi.mocked(postingsApi);

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
  id: "p1",
  ref: "P3KX9Q2A",
  title: "Backend Engineer",
  location: { city: "Athens", country: "GR", remote: true },
  url: "https://jobs.example/1",
  posted_at: "2026-08-20T00:00:00Z",
  status: "mapped",
  saved: false,
  seen: false,
  needs_review: false,
  skills: [],
} as unknown as PostingOut;

function mockCompanyPostings(items: PostingOut[]) {
  mockedPostings.fetchPostings.mockResolvedValue({
    items,
    total: items.length,
    unseen: 0,
  } as unknown as Awaited<ReturnType<typeof postingsApi.fetchPostings>>);
}

describe("Companies browsing (plan 135)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the proposed badge for posting-born companies", async () => {
    mocked.fetchCompanies.mockResolvedValue({ items: [COMPANY, PROPOSED], facets: null });
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
    mockCompanyPostings([POSTING]);
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
    mockCompanyPostings([]);
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

  it("the New filter shows only posting-born companies", async () => {
    mocked.fetchCompanies.mockResolvedValue({ items: [COMPANY, PROPOSED], facets: null });
    render(
      <MemoryRouter>
        <Companies />
      </MemoryRouter>
    );
    await screen.findByTestId("company-card-acme-cloud");
    fireEvent.click(screen.getByTestId("company-filter-new"));
    expect(screen.queryByTestId("company-card-acme-cloud")).not.toBeInTheDocument();
    expect(screen.getByTestId("company-card-newborn-works")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("company-filter-all"));
    expect(screen.getByTestId("company-card-acme-cloud")).toBeInTheDocument();
  });

  it("company postings render the /postings card: in-app open + source link", async () => {
    mocked.fetchCompany.mockResolvedValue(DETAIL);
    mockCompanyPostings([POSTING]);
    render(
      <MemoryRouter initialEntries={["/companies/acme-cloud"]}>
        <Routes>
          <Route path="/companies/:key" element={<CompanyDetail />} />
          <Route
            path="/postings/:ref"
            element={<div data-testid="posting-page-stub" />}
          />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByTestId("posting-card")).toBeInTheDocument();
    expect(mockedPostings.fetchPostings).toHaveBeenCalledWith(
      expect.objectContaining({ company: "acme-cloud", sort: "fresh" })
    );
    const apply = screen.getByTestId("posting-apply");
    expect(apply).toHaveAttribute("href", "https://jobs.example/1");
    expect(apply).toHaveAttribute("target", "_blank");
    expect(apply).toHaveAttribute("rel", "noopener noreferrer");
    fireEvent.click(screen.getByTestId("posting-details"));
    expect(await screen.findByTestId("posting-page-stub")).toBeInTheDocument();
  });

  it("a closed company posting renders in the closed state", async () => {
    mocked.fetchCompany.mockResolvedValue(DETAIL);
    mockCompanyPostings([
      { ...POSTING, status: "mapped", expires_at: "2020-01-01T00:00:00Z" } as PostingOut,
    ]);
    render(
      <MemoryRouter initialEntries={["/companies/acme-cloud"]}>
        <Routes>
          <Route path="/companies/:key" element={<CompanyDetail />} />
        </Routes>
      </MemoryRouter>
    );
    const card = await screen.findByTestId("posting-card");
    expect(card).toHaveAttribute("data-state", "closed");
    expect(screen.getByTestId("posting-closed")).toBeInTheDocument();
  });

  it("sorts the directory and keeps the sort in the URL", async () => {
    mocked.fetchCompanies.mockResolvedValue({ items: [COMPANY], facets: null });
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/companies"]}>
        <Companies />
        <LocationProbe />
      </MemoryRouter>
    );
    await screen.findByTestId("company-card-acme-cloud");
    // the default order is omitted (the endpoint's own default)
    const calls = mocked.fetchCompanies.mock.calls;
    expect(calls[calls.length - 1]?.[0]?.sort).toBeUndefined();

    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    await user.click(await screen.findByRole("option", { name: "Recently hiring" }));
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("sort=recent")
    );
    await waitFor(() =>
      expect(mocked.fetchCompanies).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "recent" })
      )
    );
  });

  it("restores the directory sort from the URL", async () => {
    mocked.fetchCompanies.mockResolvedValue({ items: [COMPANY], facets: null });
    render(
      <MemoryRouter initialEntries={["/companies?sort=name"]}>
        <Companies />
      </MemoryRouter>
    );
    await screen.findByTestId("company-card-acme-cloud");
    await waitFor(() =>
      expect(mocked.fetchCompanies).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "name" })
      )
    );
  });

  it("keeps the directory filters in the URL", async () => {
    mocked.fetchCompanies.mockResolvedValue({ items: [COMPANY], facets: null });
    render(
      <MemoryRouter initialEntries={["/companies"]}>
        <Companies />
        <LocationProbe />
      </MemoryRouter>
    );
    await screen.findByTestId("company-card-acme-cloud");

    fireEvent.change(screen.getByTestId("company-search"), { target: { value: "acme" } });
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("q=acme")
    );
    fireEvent.change(screen.getByTestId("company-filter-location"), {
      target: { value: "Athens" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("location=Athens")
    );
    fireEvent.change(screen.getByTestId("company-filter-min-open"), {
      target: { value: "5" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("min_open=5")
    );
    fireEvent.click(screen.getByTestId("company-filter-new"));
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("status=new")
    );

    fireEvent.click(screen.getByTestId("company-filters-clear"));
    await waitFor(() => expect(screen.getByTestId("location-search").textContent).toBe(""));
  });

  it("restores directory filters from the URL", async () => {
    mocked.fetchCompanies.mockResolvedValue({
      items: [COMPANY, PROPOSED],
      facets: null,
    });
    render(
      <MemoryRouter
        initialEntries={["/companies?q=acme&location=Athens&min_open=5&work_mode=remote&status=new"]}
      >
        <Companies />
      </MemoryRouter>
    );
    await screen.findByTestId("company-card-newborn-works");
    expect(screen.queryByTestId("company-card-acme-cloud")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mocked.fetchCompanies).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "acme",
          location: "Athens",
          min_open: 5,
          work_mode: ["remote"],
        })
      )
    );
    expect(screen.getByTestId("company-filter-new")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("company-search")).toHaveValue("acme");
  });
});

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}
