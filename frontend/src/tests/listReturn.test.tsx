import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { CompanyDetail } from "@/features/companies/pages/CompanyDetail";
import { PostingDetailPage } from "@/features/postings/pages/PostingDetailPage";
import { rememberListSearch, resetListReturn } from "@/lib/listReturn";
import { resetExploreListCache } from "@/features/catalog/exploreListCache";
import { fetchCompany, fetchCompanies } from "@/api/companies";
import {
  fetchPostingDetail,
  fetchPostings,
  hidePosting,
} from "@/api/postings";
import type { CompanyDetail as CompanyDetailType } from "@/types/wire";
import type { PostingDetailOut, PostingOut } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostingDetail: vi.fn(),
    fetchPostings: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    savePosting: vi.fn().mockResolvedValue(undefined),
    hidePosting: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/companies", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/companies")>();
  return {
    ...mod,
    fetchCompany: vi.fn(),
    fetchCompanies: vi.fn(),
  };
});

vi.mock("@/api/applications", () => ({
  trackApplication: vi.fn().mockResolvedValue({ id: "app-1" }),
}));

vi.mock("@/api/cv", () => ({
  createCoverLetter: vi.fn().mockResolvedValue({ id: "letter-1" }),
}));

vi.mock("@/api/interview", () => ({
  createInterviewSession: vi.fn().mockResolvedValue({ id: "session-1" }),
  startInterviewSession: vi
    .fn()
    .mockResolvedValue({ id: "session-1", chat_session_id: "chat-1" }),
}));

vi.mock("@/features/chat/components/chat/interviewChatLink", () => ({
  openInterviewChat: vi.fn().mockResolvedValue(undefined),
}));

const mockFetchDetail = vi.mocked(fetchPostingDetail);
const mockFetchCompany = vi.mocked(fetchCompany);
const mockFetchPostings = vi.mocked(fetchPostings);
const mockFetchCompanies = vi.mocked(fetchCompanies);

const NOW = Date.now();
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const ahead = (ms: number) => new Date(NOW + ms).toISOString();
const DAY = 24 * 60 * 60 * 1000;

function detail(): PostingDetailOut {
  return {
    id: "p1",
    ref: "P3KX9Q2A",
    source_id: "s1",
    external_id: "ext-1",
    title: "Backend Engineer",
    org: "ACME",
    org_key: "acme",
    location: { city: "Athens", country: "GR", remote: true },
    url: "https://jobs.example/1",
    seniority: "mid",
    employment_type: "full_time",
    contract_type: "permanent",
    work_hours: "full_time",
    hours_per_week_min: 40,
    hours_per_week_max: 42,
    salary_currency: "EUR",
    salary_min: 54000,
    salary_max: 66000,
    salary_period: "year",
    salary_basis: "gross",
    salary_normalized_min: 54000,
    salary_normalized_max: 66000,
    posted_at: ago(5 * DAY),
    created_at: ago(3 * DAY),
    updated_at: ago(2 * HOUR_MS),
    expires_at: ahead(12 * DAY),
    status: "mapped",
    mapping_reason: "",
    notes: "",
    seen: false,
    saved: false,
    source_key: "synth",
    source_title: "Synthetic test connector",
    source_connector: "synth",
    source_synced_at: ago(2 * HOUR_MS),
    description: "We build things.",
    extract_version: 1,
    needs_review: false,
    coverage: 8.2,
    similar: [],
    extract: null,
  };
}

const HOUR_MS = 60 * 60 * 1000;

const COMPANY: CompanyDetailType = {
  key: "acme-cloud",
  name: "Acme Cloud",
  domain: "acme.example",
  status: "active",
  open_postings: 3,
  has_profile: false,
  aliases: [],
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

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">
      {location.pathname}
      {location.search}
    </div>
  );
}

function renderPostingDetail() {
  render(
    <MemoryRouter initialEntries={["/postings/P3KX9Q2A"]}>
      <Routes>
        <Route path="/postings/:ref" element={<PostingDetailPage />} />
        <Route path="/postings" element={<LocationProbe />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
  return screen.findByTestId("posting-detail");
}

function renderCompanyDetail() {
  render(
    <MemoryRouter initialEntries={["/companies/acme-cloud"]}>
      <Routes>
        <Route path="/companies/:key" element={<CompanyDetail />} />
        <Route path="/companies" element={<LocationProbe />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
  return screen.findByTestId("company-detail");
}

describe("list return links (plan 172)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetListReturn();
    resetExploreListCache();
    mockFetchDetail.mockResolvedValue(detail());
    mockFetchCompany.mockResolvedValue(COMPANY);
    mockFetchPostings.mockResolvedValue({
      items: [POSTING],
      total: 1,
      unseen: 0,
    } as unknown as Awaited<ReturnType<typeof fetchPostings>>);
    mockFetchCompanies.mockResolvedValue({ items: [], facets: null });
  });

  it("the posting back link returns to the remembered /postings search", async () => {
    rememberListSearch("/postings", "q=python&sort=fresh");
    await renderPostingDetail();
    const back = screen.getByText("All postings").closest("a");
    expect(back).toHaveAttribute("href", "/postings?q=python&sort=fresh");
    fireEvent.click(back!);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/postings?q=python&sort=fresh"
      )
    );
  });

  it("the back link falls back to the bare list when nothing is remembered", async () => {
    await renderPostingDetail();
    expect(screen.getByText("All postings").closest("a")).toHaveAttribute(
      "href",
      "/postings"
    );
  });

  it("hiding the posting returns to the remembered list search", async () => {
    rememberListSearch("/postings", "q=python");
    await renderPostingDetail();
    fireEvent.click(screen.getByTestId("hide-posting"));
    await waitFor(() => expect(hidePosting).toHaveBeenCalledWith("p1", true));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/postings?q=python")
    );
  });

  it("the company back link returns to the remembered /companies search", async () => {
    rememberListSearch("/companies", "status=new&sort=name");
    await renderCompanyDetail();
    const back = screen.getByText("All companies").closest("a");
    expect(back).toHaveAttribute("href", "/companies?status=new&sort=name");
    fireEvent.click(back!);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/companies?status=new&sort=name"
      )
    );
  });
});
