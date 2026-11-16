import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Applications } from "@/features/postings/pages/Applications";
import { ApplicationKitPage } from "@/features/postings/pages/ApplicationKitPage";
import { PostingKitPage } from "@/features/postings/pages/PostingKitPage";
import {
  fetchApplicationKit,
  fetchApplications,
  trackApplication,
  linkApplicationDocument,
} from "@/api/applications";
import { createCoverLetter } from "@/api/cv";
import { preparePostingKit } from "@/api/postings";
import { fetchPostingKit } from "@/api/postings";
import { saveAnswer } from "@/api/profileAnswers";
import type { ApplicationDetail, ApplicationList } from "@/types/application";
import type { ApplicationKit, KitPrepare, PostingKit } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostingKit: vi.fn(),
    preparePostingKit: vi.fn(),
  };
});

vi.mock("@/api/applications", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/applications")>();
  return {
    ...mod,
    fetchApplications: vi.fn(),
    fetchApplication: vi.fn(),
    fetchApplicationKit: vi.fn(),
    trackApplication: vi.fn(),
    linkApplicationDocument: vi.fn(),
  };
});

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchCvs: vi.fn().mockResolvedValue([]),
    createCoverLetter: vi.fn(),
  };
});

vi.mock("@/api/profileAnswers", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/profileAnswers")>();
  return {
    ...mod,
    saveAnswer: vi.fn(),
    deleteAnswer: vi.fn(),
  };
});

const NOW = new Date().toISOString();

function kitFixture(overrides: Partial<PostingKit> = {}): PostingKit {
  return {
    posting: {
      id: "post-1",
      ref: "P3KX9Q2A",
      title: "Backend Engineer",
      org: "ACME",
      url: "https://jobs.example/1",
      location: { city: "Athens", country: "GR", remote: true },
      posted_at: NOW,
      expires_at: null,
      extract_ready: true,
    },
    gap: {
      must_have: [
        {
          raw_label: "SQL",
          skill_key: "sql",
          label: "SQL",
          required_level: 4,
          user_level: 6,
          status: "met",
          priority: "must_have",
          kind: "skill",
          evidence_quote: "solid SQL required",
          user_evidence: [],
        },
      ],
      nice_to_have: [],
      bonus: [],
    },
    cv: {
      needs_cv: false,
      candidates: [{ id: "cv-1", title: "My CV", kind: "resume", target_posting_id: "post-1" }],
      variant: { id: "cv-1", title: "My CV", kind: "resume", target_posting_id: "post-1" },
    },
    cover_letter: { doc: null, candidates: [] },
    answers: [
      { key: "availability", prompt: "When can you start?", saved_answer: null },
      { key: "languages_posting", prompt: "Languages?", saved_answer: null },
    ],
    checklist: [
      { id: "posting_open", level: "info", label: "No closing date stated", source: "posting" },
      { id: "cv_pages", level: "pass", label: "Measured 1 page(s)", source: "pdf" },
      {
        id: "file_format",
        level: "info",
        label: "Send PDF",
        source: "guidance",
      },
    ],
    application: null,
    ...overrides,
  };
}

function appKitFixture(overrides: Partial<ApplicationKit> = {}): ApplicationKit {
  return {
    ...kitFixture(),
    timeline: [
      {
        id: "ev-1",
        at: NOW,
        kind: "stage_change",
        stage_from: null,
        stage_to: "applied",
        body: "",
        actor: "user",
        meta: {},
      },
    ],
    timeline_truncated: false,
    documents: {
      cv: { id: "cv-1", title: "My CV", kind: "resume", target_posting_id: "post-1" },
      cover_letter: null,
    },
    application: {
      id: "app-1",
      stage: "applied",
      applied_at: NOW,
      cv_id: "cv-1",
      cover_letter_id: null,
    },
    ...overrides,
  };
}

function applicationRow(overrides: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    id: "app-1",
    posting_id: "post-1",
    posting_ref: "P3KX9Q2A",
    posting_title: "Backend Engineer",
    posting_org: "ACME",
    stage: "applied",
    applied_at: NOW,
    applied_via: "url",
    applied_via_url: "",
    deadline_at: null,
    next_followup_at: null,
    contact_id: null,
    offer: {},
    outcome: null,
    closed_at: null,
    cv_id: null,
    cover_letter_id: null,
    external_ref: "",
    notes: "",
    meta: {},
    created_at: NOW,
    updated_at: NOW,
    timeline: [],
    ...overrides,
  };
}

function renderKitRoutes(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/postings/:ref/kit" element={<PostingKitPage />} />
        <Route path="/applications" element={<Applications />} />
        <Route path="/applications/:id" element={<ApplicationKitPage />} />
        <Route path="/postings/:ref" element={<div data-testid="posting-page" />} />
        <Route path="*" element={<div data-testid="not-found" />} />
      </Routes>
    </MemoryRouter>,
  );
}

const mockFetchKit = vi.mocked(fetchPostingKit);
const mockPrepare = vi.mocked(preparePostingKit);
const mockFetchAppKit = vi.mocked(fetchApplicationKit);
const mockTrack = vi.mocked(trackApplication);
const mockLink = vi.mocked(linkApplicationDocument);

beforeEach(() => {
  mockFetchKit.mockReset().mockResolvedValue(kitFixture());
  mockPrepare.mockReset();
  mockFetchAppKit.mockReset().mockResolvedValue(appKitFixture());
  mockTrack.mockReset().mockResolvedValue(applicationRow());
  mockLink.mockReset().mockResolvedValue(applicationRow());
  vi.mocked(fetchApplications).mockReset().mockResolvedValue({
    items: [applicationRow()],
    total: 1,
    funnel: { saved: 0, applied: 1, interviewing: 0, offers: 0, closed: 0 },
    next_followup_at: null,
  } as unknown as ApplicationList);
});

describe("PostingKitPage", () => {
  it("renders the five tabs and preserves the open-original link", async () => {
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    expect(await screen.findByTestId("kit-title")).toHaveTextContent("Backend Engineer");
    const tablist = screen.getByRole("tablist", { name: /kit sections/i });
    const tabs = within(tablist).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "CV variant",
      "Cover letter",
      "Answers",
      "Checklist",
      "Timeline",
    ]);
    expect(screen.getByTestId("kit-open-original")).toHaveAttribute(
      "href",
      "https://jobs.example/1",
    );
    expect(screen.getByTestId("kit-open-original")).toHaveAttribute("target", "_blank");
    expect(screen.getByTestId("kit-cv-working")).toHaveTextContent("My CV");
    expect(screen.getByTestId("kit-cv-variant-badge")).toBeInTheDocument();
  });

  it("links to the application when a tracked posting has no timeline", async () => {
    mockFetchKit.mockResolvedValue(
      kitFixture({
        application: {
          id: "app-1",
          stage: "applied",
          applied_at: NOW,
          cv_id: "cv-1",
          cover_letter_id: null,
        },
      }),
    );
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-timeline"));
    const tracked = screen.getByTestId("kit-timeline-tracked");
    expect(tracked).toBeInTheDocument();
    expect(within(tracked).getByRole("link", { name: "Open application" })).toHaveAttribute(
      "href",
      "/applications/app-1",
    );
  });

  it("saves a screening answer explicitly", async () => {
    mockFetchKit.mockResolvedValue(kitFixture());
    vi.mocked(saveAnswer).mockResolvedValue({
      id: "ans-1",
      question_key: "availability",
      question_text: "When can you start?",
      answer_text: "Immediately.",
      evidence_refs: [],
      created_at: NOW,
      updated_at: NOW,
    });
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-answers"));
    fireEvent.change(screen.getByTestId("kit-answer-input-availability"), {
      target: { value: "Immediately." },
    });
    fireEvent.click(screen.getByTestId("kit-answer-save-availability"));
    await waitFor(() =>
      expect(saveAnswer).toHaveBeenCalledWith({
        question_key: "availability",
        question_text: "When can you start?",
        answer_text: "Immediately.",
      }),
    );
    expect(await screen.findByTestId("kit-answer-state-availability")).toHaveTextContent(
      "Saved",
    );
  });

  it("shows the needs_cv state with a CV Studio link when there is no CV", async () => {
    mockFetchKit.mockResolvedValue(
      kitFixture({
        cv: { needs_cv: true, candidates: [], variant: null },
        gap: null,
        posting: {
          id: "post-1",
          ref: "P3KX9Q2A",
          title: "Backend Engineer",
          org: "ACME",
          url: "https://jobs.example/1",
          extract_ready: false,
        },
      }),
    );
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    expect(await screen.findByTestId("kit-cv-needs-cv")).toBeInTheDocument();
    expect(screen.getByTestId("kit-cv-studio-cta")).toHaveAttribute("href", "/cv");
  });

  it("keeps the checklist read-only and sourced with the honesty note", async () => {
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-checklist"));
    const panel = screen.getByTestId("kit-checklist-tab");
    expect(within(panel).getByTestId("kit-check-posting_open")).toHaveTextContent(/info/i);
    expect(within(panel).getByTestId("kit-check-file_format")).toHaveTextContent(/info/i);
    expect(screen.getByTestId("kit-checklist-note").textContent).toMatch(
      /not a simulation of any ATS product/i,
    );
    expect(panel.querySelector("input, textarea, select")).toBeNull();
  });

  it("renders deterministic answers as unsaved with a write-your-own note", async () => {
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-answers"));
    expect(screen.getByTestId("kit-answer-availability")).toHaveTextContent(
      /when can you start/i,
    );
    expect(screen.getByTestId("kit-answer-state-availability")).toHaveTextContent(/not saved/i);
    expect(screen.getByTestId("kit-answer-state-languages_posting")).toHaveTextContent(
      /not saved/i,
    );
  });

  it("prepare shows review cards that apply or dismiss, and never writes", async () => {
    mockPrepare.mockResolvedValue({
      posting_id: "post-1",
      ref: "P3KX9Q2A",
      needs_cv: false,
      extract_ready: true,
      cv_id: "cv-1",
      coverage: { covered: [], missing: [] },
      section_gaps: [
        {
          source_key: "experience",
          label: "Experience",
          message: "No Experience section in the blocks — 2 item(s) available from your profile.",
          candidate_count: 2,
        },
      ],
      cover_letter: { doc: null, candidates: [] },
    } as KitPrepare);
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-cv-prepare"));
    const card = await screen.findByTestId("kit-section-gap-experience");
    expect(card.textContent).toContain("Experience");
    const apply = screen.getByTestId("kit-section-apply-experience");
    expect(apply.getAttribute("href")).toBe("/cv/cv-1");
    fireEvent.click(screen.getByTestId("kit-section-dismiss-experience"));
    expect(screen.queryByTestId("kit-section-gap-experience")).toBeNull();
    // Nothing auto-applies: the only calls were reads.
    expect(mockTrack).not.toHaveBeenCalled();
    expect(mockLink).not.toHaveBeenCalled();
  });

  it("mark as applied records the tracker row with the chosen documents", async () => {
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-mark-applied"));
    const dialog = await screen.findByTestId("kit-mark-applied-dialog");
    expect(within(dialog).getByTestId("kit-mark-cv")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("kit-mark-submit"));
    await waitFor(() => expect(mockTrack).toHaveBeenCalledTimes(1));
    expect(mockTrack).toHaveBeenCalledWith({
      posting_id: "post-1",
      applied_via: "url",
      applied_via_url: "https://jobs.example/1",
      cv_id: "cv-1",
      cover_letter_id: null,
    });
    expect(await screen.findByTestId("application-kit-page")).toBeInTheDocument();
  });

  it("shows the untracked timeline state before an application exists", async () => {
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-timeline"));
    expect(screen.getByTestId("kit-timeline-untracked")).toBeInTheDocument();
    expect(screen.getByTestId("kit-timeline-mark")).toBeInTheDocument();
  });
});

describe("ApplicationKitPage", () => {
  it("composes the kit with the timeline and linked documents", async () => {
    renderKitRoutes("/applications/app-1");
    expect(await screen.findByTestId("kit-title")).toHaveTextContent("Backend Engineer");
    fireEvent.click(screen.getByTestId("kit-tab-timeline"));
    expect(screen.getByTestId("kit-stage-chip")).toHaveTextContent(/applied/i);
    expect(screen.getByTestId("kit-event-stage_change")).toBeInTheDocument();
    expect(screen.getByTestId("kit-doc-cv").getAttribute("href")).toBe("/cv/cv-1");
  });

  it("creates a cover letter only on the explicit button, never silently", async () => {
    vi.mocked(createCoverLetter).mockReset().mockResolvedValue({
      id: "letter-1",
      title: "Cover letter — Backend Engineer",
      kind: "cover_letter",
    } as never);
    renderKitRoutes("/postings/P3KX9Q2A/kit");
    await screen.findByTestId("kit-title");
    fireEvent.click(screen.getByTestId("kit-tab-letter"));
    fireEvent.click(await screen.findByTestId("kit-letter-create"));
    await waitFor(() => expect(createCoverLetter).toHaveBeenCalledTimes(1));
    expect(createCoverLetter).toHaveBeenCalledWith({ posting_id: "post-1" });
    // The kit reloads from the read endpoint; no other write happened.
    await waitFor(() => expect(mockFetchKit).toHaveBeenCalledTimes(2));
    expect(mockTrack).not.toHaveBeenCalled();
    expect(mockLink).not.toHaveBeenCalled();
  });

  it("deep-links back to the posting and the tracker", async () => {
    renderKitRoutes("/applications/app-1");
    await screen.findByTestId("kit-title");
    expect(screen.getByTestId("kit-open-posting").getAttribute("href")).toBe(
      "/postings/P3KX9Q2A",
    );
    expect(screen.getByTestId("kit-open-original").getAttribute("href")).toBe(
      "https://jobs.example/1",
    );
  });
});

describe("Applications page kit entry", () => {
  it("the card and the list row link to the application kit", async () => {
    renderKitRoutes("/applications");
    const cardLink = await screen.findByTestId("application-kit-link-app-1");
    fireEvent.click(cardLink);
    expect(await screen.findByTestId("application-kit-page")).toBeInTheDocument();
  });
});
