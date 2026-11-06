import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Taxonomy } from "@/pages/settings/Taxonomy";
import { fetchTaxonomyStats } from "@/api/taxonomy";

vi.mock("@/api/taxonomy", () => ({
    fetchJobProposals: vi.fn().mockResolvedValue({ items: [], legacy_count: 0, next_cursor: null, total: 0 }),
    regenerateJobProposals: vi.fn(),
    fetchDuplicateJobTypes: vi.fn().mockResolvedValue({ groups: [] }),
    mergeJobTypes: vi.fn(),
  fetchInterests: vi.fn().mockResolvedValue([]),
  fetchSkillRows: vi.fn().mockResolvedValue([]),
  fetchTaxonomyStats: vi.fn(),
  createTag: vi.fn(),
  deleteTag: vi.fn(),
  updateTag: vi.fn(),
  promoteSkill: vi.fn(),
  mergeSkill: vi.fn(),
  bulkSkillAction: vi.fn(),
}));

vi.mock("@/api/skillRelations", () => ({
  fetchSkillRelations: vi.fn().mockResolvedValue([]),
  fetchSkillRelationThresholds: vi.fn().mockResolvedValue(null),
  fetchSkillRelationRuns: vi.fn().mockResolvedValue([]),
  saveSkillRelationThresholds: vi.fn(),
  acceptSkillRelation: vi.fn(),
  dismissSkillRelation: vi.fn(),
  removeSkillRelation: vi.fn(),
  saveSkillRelationAlias: vi.fn(),
  createSkillRelation: vi.fn(),
  bulkSkillRelationAction: vi.fn(),
}));

vi.mock("@/api/i18n", () => ({
  fetchOverlayQueue: vi.fn().mockResolvedValue([]),
  draftOverlays: vi.fn(),
  approveOverlay: vi.fn(),
  rejectOverlay: vi.fn(),
  updateOverlay: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({}),
  },
  apiDetail: vi.fn(() => "request failed"),
}));

const STATS = {
  skills: {
    total: 654,
    active: 32,
    proposed: 605,
    deprecated: 4,
    auto_promoted: 128,
    promoted_7d: 41,
  },
  queue: {
    relations: 12,
    enrichment: 3,
    job_proposals: 0,
    paths: 2,
    translations: 8,
    total: 25,
  },
};

function renderPage(initialEntry = "/settings/taxonomy?tab=skills") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Taxonomy />
    </MemoryRouter>,
  );
}

const mockStats = () => vi.mocked(fetchTaxonomyStats);

describe("taxonomy work-queue stats", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStats().mockResolvedValue(STATS);
  });

  it("renders both groups with server counts and totals", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId("taxonomy-stats")).toBeInTheDocument());

    expect(screen.getByText("Skills ontology · 654 total")).toBeInTheDocument();
    const skills = within(screen.getByTestId("taxonomy-stats-skills"));
    expect(skills.getByText("605")).toBeInTheDocument();
    expect(skills.getByText("32")).toBeInTheDocument();
    expect(skills.getByText("4")).toBeInTheDocument();
    expect(skills.getByText("128")).toBeInTheDocument();

    expect(screen.getByText("Review queue · 25 actionable")).toBeInTheDocument();
    const queue = within(screen.getByTestId("taxonomy-stats-queue"));
    expect(queue.getByText("12")).toBeInTheDocument();
    expect(queue.getByText("3")).toBeInTheDocument();
    expect(queue.getByText("2")).toBeInTheDocument();
    expect(queue.getByText("8")).toBeInTheDocument();
  });

  it("shows the 7-day promotion delta as the proposed hint", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("taxonomy-stats")).toBeInTheDocument());
    expect(screen.getByText("+41 promoted in 7d")).toBeInTheDocument();
  });

  it("falls back to the awaiting-review hint when nothing was promoted", async () => {
    mockStats().mockResolvedValue({
      ...STATS,
      skills: { ...STATS.skills, promoted_7d: 0 },
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("taxonomy-stats")).toBeInTheDocument());
    expect(screen.getByText("awaiting review")).toBeInTheDocument();
  });

  it("carries counts on the queue tabs only", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Relations · 12" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("tab", { name: "Proposals · 3" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Translations · 8" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Paths · 2" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Interests" })).toBeInTheDocument();
  });

  it("refetches the counts when the section changes", async () => {
    renderPage("/settings/taxonomy");
    await waitFor(() => expect(mockStats()).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("tab", { name: "Skills" }));
    await waitFor(() => expect(mockStats()).toHaveBeenCalledTimes(2));
  });

  it("hides the bar when the counts cannot be loaded", async () => {
    mockStats().mockRejectedValue(new Error("offline"));
    renderPage();
    await waitFor(() => expect(mockStats()).toHaveBeenCalled());
    expect(screen.queryByTestId("taxonomy-stats")).not.toBeInTheDocument();
  });
});
