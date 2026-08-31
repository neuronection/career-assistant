import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Dashboard } from "@/pages/Dashboard";
import { ExpressOnboarding } from "@/pages/ExpressOnboarding";
import { useProfileStore } from "@/stores/profileStore";
import { useCatalogStore } from "@/stores/catalogStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { expressStart, resolveTarget, fetchTargetDashboard } from "@/api/onboarding";
import { fetchPostings } from "@/api/postings";
import type { JobPostingItem, TargetDashboard } from "@/types";

vi.mock("@/api/onboarding", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/onboarding")>();
  return {
    ...mod,
    resolveTarget: vi.fn(),
    expressStart: vi.fn(),
    fetchTargetDashboard: vi.fn(),
    dismissNudge: vi.fn().mockResolvedValue(undefined),
    fetchCompleteness: vi.fn(),
    fetchNudges: vi.fn(),
  };
});

vi.mock("@/api/matching", () => ({
  fetchRankings: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchCandidates: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchFeed: vi.fn().mockResolvedValue({ items: [], total: 0, unseen: 0 }),
    markSeen: vi.fn().mockResolvedValue({ marked: 0 }),
  };
});

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 0 }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    savePosting: vi.fn().mockResolvedValue(undefined),
    hidePosting: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/jobs", () => ({
  fetchFamilyTree: vi.fn().mockResolvedValue([]),
  fetchJobs: vi.fn().mockResolvedValue([]),
}));

const mockResolve = vi.mocked(resolveTarget);
const mockExpressStart = vi.mocked(expressStart);
const mockFetchTargetDashboard = vi.mocked(fetchTargetDashboard);
const mockFetchPostings = vi.mocked(fetchPostings);

function postingRow(id: string): JobPostingItem {
  return {
    id,
    source_id: "s1",
    external_id: id,
    title: "QA Automation Engineer",
    org: "SynthCo",
    location: { city: "Athens", country: "GR", remote: true },
    url: `https://jobs.example/${id}`,
    status: "mapped",
    catalog_job_id: "j1",
    fit: 7.2,
    seen: false,
    saved: false,
    notes: "",
    source_key: "synth",
    posted_at: "2026-08-20T00:00:00Z",
  };
}

function targetDashboard(): TargetDashboard {
  return {
    families: ["technology-software"],
    open_postings: {
      total: 3,
      unseen: 2,
      salary_band: { min: 40000, max: 70000 },
      top_employers: [{ org: "SynthCo", count: 2 }],
    },
    adjacent_targets: [
      { family_key: "technology-data", label: "Data & AI", sample: "Data Engineer" },
    ],
    nudges: [{ type: "skills_micro_run", message: "Answer 3 quick skill questions" }],
    completeness: {
      percent: 40,
      segments: [
        {
          key: "skills",
          label: "Your skills",
          filled: false,
          hint: "Add your skills — alerts get far more precise",
          href: "/profile",
        },
      ],
    },
  };
}

describe("Express onboarding", () => {
  beforeEach(() => {
    mockExpressStart.mockClear();
    mockResolve.mockClear();
    mockResolve.mockResolvedValue({
      query: "qa automation",
      resolved_by: "deterministic",
      families: [{ key: "technology-software", label: "Software" }],
      skill_keys: ["programming"],
      archetypes: [
        {
          code: "qa-engineer",
          title: "QA Engineer",
          family_key: "technology-software",
          score: 0.7,
        },
      ],
    });
    mockExpressStart.mockResolvedValue({
      target_families: ["technology-software"],
      target_labels: ["QA Engineer"],
      interest_tags_written: 2,
      target_mode: true,
    });
  });

  it("resolves a typed title and starts target mode", async () => {
    render(
      <MemoryRouter>
        <ExpressOnboarding />
      </MemoryRouter>
    );
    fireEvent.change(screen.getByTestId("express-query"), {
      target: { value: "qa automation" },
    });
    const suggestion = await screen.findByText(/QA Engineer · technology-software/);
    fireEvent.click(suggestion);
    fireEvent.click(screen.getByTestId("express-start"));
    await waitFor(() =>
      expect(mockExpressStart).toHaveBeenCalledWith(
        expect.objectContaining({ targets: ["qa-engineer"] })
      )
    );
  });

  it("refuses to start without a target", async () => {
    render(
      <MemoryRouter>
        <ExpressOnboarding />
      </MemoryRouter>
    );
    const startButton = screen.getByTestId("express-start");
    expect(startButton).toBeDisabled();
    fireEvent.click(startButton);
    expect(mockExpressStart).not.toHaveBeenCalled();
  });
});

describe("Dashboard target mode", () => {
  beforeEach(() => {
    useProfileStore.setState({
      profile: null,
      load: vi.fn().mockResolvedValue(undefined),
    });
    useCatalogStore.setState({
      families: [],
      jobs: [],
      loadFamilies: vi.fn().mockResolvedValue(undefined),
      loadJobs: vi.fn().mockResolvedValue(undefined),
    });
    useBootstrapStore.setState({
      bootstrap: {
        career_stage: "early_career",
        stage_source: "explicit",
        features: { universities: false, grade_fields: false },
        suggested_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 1,
          education: 5,
          interests: 4,
        },
        effective_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 1,
          education: 5,
          interests: 4,
        },
        weights_overridden: false,
        target_mode: true,
        target_families: ["technology-software"],
      },
      loaded: true,
    });
    mockFetchTargetDashboard.mockResolvedValue(targetDashboard());
    mockFetchPostings.mockImplementation(async (params) => {
      if (params?.saved) {
        return { items: [], total: 0, unseen: 0 };
      }
      return {
        items: [postingRow("p1")],
        total: 3,
        unseen: 2,
      };
    });
  });

  it("renders open jobs, market snapshot, adjacent targets and the nudge", async () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("target-mode")).toBeInTheDocument();
    expect(screen.getByText(/QA Automation Engineer/)).toBeInTheDocument();
    expect(screen.getByText("2 new")).toBeInTheDocument();
    expect(screen.getByText(/Salary band/i)).toBeInTheDocument();
    expect(screen.getByText(/Data & AI/)).toBeInTheDocument();
    expect(screen.getByTestId("nudge-banner")).toHaveTextContent(
      /3 quick skill questions/
    );
  });

  it("dismisses a nudge permanently", async () => {
    const { dismissNudge } = await import("@/api/onboarding");
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByLabelText("Dismiss nudge"));
    await waitFor(() =>
      expect(dismissNudge).toHaveBeenCalledWith("skills_micro_run")
    );
  });
});
