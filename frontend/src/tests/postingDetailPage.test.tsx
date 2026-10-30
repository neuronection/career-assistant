import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { PostingDetailPage } from "@/features/postings/pages/PostingDetailPage";
import {
  fetchPostingDetail,
  hidePosting,
  markApplied,
  markPostingsSeen,
  savePosting,
} from "@/api/postings";
import type { PostingDetailOut } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostingDetail: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    savePosting: vi.fn().mockResolvedValue(undefined),
    hidePosting: vi.fn().mockResolvedValue(undefined),
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

const NOW = Date.now();
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const ahead = (ms: number) => new Date(NOW + ms).toISOString();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function detail(overrides: Partial<PostingDetailOut> = {}): PostingDetailOut {
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
    updated_at: ago(2 * HOUR),
    expires_at: ahead(12 * DAY),
    status: "mapped",
    mapping_reason: "",
    notes: "",
    seen: false,
    saved: false,
    source_key: "synth",
    source_title: "Synthetic test connector",
    source_connector: "synth",
    source_synced_at: ago(2 * HOUR),
    catalog_job: {
      id: "job-1",
      code: "backend-engineer",
      title: "Backend Engineer",
      family_key: "software",
      family_label: "Software & Data",
      short_description: "Builds backend services",
      status: "published",
      source: "seed",
      attributes: {},
      interests: [{ key: "data", label: "Data" }],
      skills: [],
      links: [],
      created_at: ago(30 * DAY),
    },
    description: "We build things.\nSecond line of the description.",
    extract_version: 1,
    needs_review: true,
    coverage: 8.2,
    match: {
      score: 7.8,
      breakdown: {
        freshness: { score: 6.0, weight: 1, detail: "posted 2 weeks ago" },
      },
      extracted: true,
      estimate: false,
      inputs_hash: "abc",
    },
    similar: [{ ref: "AAAA2222", title: "Data Analyst", org: "BetaCo", score: 0.72 }],
    extract: {
      skills: [
        {
          skill_key: "programming",
          required_level: 5,
          priority: "must_have",
          evidence_quote: "strong programming required",
          confidence: 0.95,
        },
      ],
      benefits: [
        { kind: "healthcare", raw: "private health cover", confidence: 0.9 },
      ],
      prerequisites: [
        {
          kind: "certificate",
          label: "PMP certificate",
          evidence_quote: "PMP certification required",
          confidence: 0.9,
        },
        {
          kind: "apprenticeship",
          label: "Completed apprenticeship",
          evidence_quote: "completed apprenticeship preferred",
          confidence: 0.9,
        },
      ],
      responsibilities: [{ text: "Build dashboards", time_pct: 40, optional: false }],
      languages: ["English (C1)", "German (B2)"],
      contract_type: {
        contract_type: "permanent",
        evidence_quote: "permanent role",
        confidence: 0.8,
      },
      onsite_policy: {
        policy: "hybrid",
        office_days_per_week: 2,
        evidence_quote: "2 days office",
        confidence: 0.9,
      },
      travel_required: {
        level: "occasional",
        days_per_month: 2,
        evidence_quote: "some travel",
        confidence: 0.5,
      },
      schedule_cues: [{ cue: "shift_work", "evidence_quote": "two shifts", confidence: 0.6 }],
    },
    ...overrides,
  };
}

function renderPage(entry = "/postings/P3KX9Q2A") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/postings/:ref" element={<PostingDetailPage />} />
        <Route path="/postings" element={<div data-testid="list-page" />} />
        <Route path="/applications" element={<div data-testid="applications-page" />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockFetchDetail.mockReset();
  mockFetchDetail.mockResolvedValue(detail());
});

describe("PostingDetailPage", () => {
  it("renders the hero, key facts and the relative timeline", async () => {
    renderPage();
    expect(await screen.findByTestId("posting-detail")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(screen.getByTestId("posting-ref")).toHaveTextContent("P3KX9Q2A");
    expect(screen.getByTestId("provenance")).toHaveTextContent("extracted");
    expect(screen.getByTestId("needs-review")).toBeInTheDocument();
    expect(screen.getByTestId("coverage")).toHaveTextContent("coverage 8.2");

    const facts = await screen.findByTestId("posting-facts");
    expect(facts).toHaveTextContent("Athens, GR");
    expect(facts).toHaveTextContent("Permanent");
    expect(facts).toHaveTextContent("Full time");
    expect(facts).toHaveTextContent("40–42 h / week");
    expect(facts).toHaveTextContent("English (C1), German (B2)");
    expect(screen.getByTestId("salary-annualized")).toBeInTheDocument();

    const timeline = await screen.findByTestId("posting-timeline");
    expect(timeline).toHaveTextContent("5 days ago");
    expect(timeline).toHaveTextContent("in 12 days");
    // first-seen / last-updated are trivia: behind the info toggle
    expect(timeline).not.toHaveTextContent("3 days ago");
    fireEvent.click(screen.getByTestId("timeline-info"));
    const panel = await screen.findByTestId("timeline-info-panel");
    expect(panel).toHaveTextContent("3 days ago");
    expect(panel).toHaveTextContent("2 hours ago");
  });

  it("collapses long raw descriptions behind Show more", async () => {
    // the raw description is hidden behind the "Show original" toggle
    renderPage();
    await screen.findByTestId("description-raw-toggle");
    fireEvent.click(screen.getByTestId("description-raw-toggle"));
    const description = await screen.findByTestId("posting-description-raw");
    expect(description).toHaveTextContent("We build things.");
    expect(description.className).toContain("line-clamp-6");
    fireEvent.click(screen.getByTestId("description-toggle"));
    expect(description.className).not.toContain("line-clamp-6");
    expect(screen.getByTestId("description-toggle")).toHaveTextContent("Show less");
  });

  it("opens the original listing in a new tab and tracks the click", async () => {
    renderPage();
    const link = await screen.findByTestId("open-original");
    expect(link).toHaveAttribute("href", "https://jobs.example/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    fireEvent.click(link);
    await waitFor(() => expect(markPostingsSeen).toHaveBeenCalledWith(["p1"]));
    expect(markApplied).toHaveBeenCalledWith("p1", "https://jobs.example/1");
  });

  it("never renders an external button for unsafe urls", async () => {
    mockFetchDetail.mockResolvedValue(detail({ url: "javascript:alert(1)" }));
    renderPage();
    await screen.findByTestId("posting-detail");
    expect(screen.queryByTestId("open-original")).not.toBeInTheDocument();
  });

  it("renders typed benefits with their kind label as tooltip", async () => {
    renderPage();
    const benefits = await screen.findByTestId("extract-benefits");
    expect(benefits).toHaveTextContent("private health cover");
    expect(screen.getByTitle("Healthcare")).toBeInTheDocument();
  });

  it("renders schedule cues, categories and company/job links", async () => {
    renderPage();
    expect(await screen.findByTestId("posting-schedule")).toHaveTextContent("Shift work");
    expect(screen.getByTestId("mapped-job")).toHaveTextContent("Backend Engineer");
    expect(screen.getByTestId("mapped-job")).toHaveAttribute("href", "/jobs/backend-engineer");
    expect(screen.getByText("ACME")).toHaveAttribute("href", "/companies/acme");
    expect(screen.getByText("Software & Data")).toBeInTheDocument();
    expect(screen.getByText("Data")).toBeInTheDocument();
  });

  it("navigates to similar postings through the detail route", async () => {
    renderPage();
    await screen.findByTestId("similar-rail");
    fireEvent.click(screen.getByText(/Data Analyst/));
    await waitFor(() => expect(mockFetchDetail).toHaveBeenCalledWith("AAAA2222"));
  });

  it("shows the not-found state for a missing posting", async () => {
    mockFetchDetail.mockRejectedValue(new Error("Posting not found"));
    renderPage();
    expect(
      await screen.findByText("This posting is no longer available.")
    ).toBeInTheDocument();
    expect(screen.getByText("All postings")).toHaveAttribute("href", "/postings");
  });

  it("renders the structured extract sections with evidence quotes", async () => {
    renderPage();
    expect(await screen.findByTestId("provenance")).toHaveTextContent("extracted");
    expect(screen.getByText(/40% of time/)).toBeInTheDocument();
    const prereqs = await screen.findByTestId("extract-prerequisites");
    expect(prereqs).toHaveTextContent("PMP certificate");
    expect(prereqs).toHaveTextContent("Certificate");
    expect(prereqs).toHaveTextContent("apprenticeship");
    expect(prereqs).not.toHaveTextContent("prereqKind.");
    expect(screen.getByTestId("extract-responsibilities")).toHaveTextContent(
      "Build dashboards"
    );
    fireEvent.click(screen.getByRole("tab", { name: "Detailed" }));
    fireEvent.click(screen.getByLabelText("Show evidence"));
    expect(screen.getByTestId("skill-evidence")).toHaveTextContent(
      "strong programming required"
    );
  });

  it("saves and hides the posting from the detail page", async () => {
    renderPage();
    await screen.findByTestId("posting-detail");
    fireEvent.click(screen.getByTestId("save-posting"));
    await waitFor(() => expect(savePosting).toHaveBeenCalledWith("p1", true));
    fireEvent.click(screen.getByTestId("hide-posting"));
    await waitFor(() => expect(hidePosting).toHaveBeenCalledWith("p1", true));
    expect(await screen.findByTestId("list-page")).toBeInTheDocument();
  });

  it("renders the match card and flags archetype estimates", async () => {
    renderPage();
    expect(await screen.findByTestId("match-score")).toHaveTextContent("7.8");
    expect(screen.queryByTestId("match-estimate-note")).not.toBeInTheDocument();
  });

  it("flags the archetype estimate for unextracted postings", async () => {
    mockFetchDetail.mockResolvedValue(
      detail({
        extract_version: null,
        extract: null,
        match: {
          score: 6.5,
          breakdown: {},
          extracted: false,
          estimate: true,
          inputs_hash: "abc",
        },
      })
    );
    renderPage();
    expect(await screen.findByTestId("match-estimate-note")).toHaveTextContent(
      "archetype estimate"
    );
  });

  it("renders the source attribution with the original listing link", async () => {
    renderPage();
    const attribution = await screen.findByTestId("source-attribution");
    expect(attribution).toHaveTextContent("Synthetic test connector");
    expect(attribution).toHaveTextContent("original listing");
    expect(
      screen.getByRole("link", { name: /original listing/ })
    ).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });
});
