import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";

import { parseTaxonomyTab, TAXONOMY_TABS, Taxonomy } from "@/pages/settings/Taxonomy";
import {
  parseRelationSection,
  RELATION_TABS,
} from "@/components/settings/SkillRelationsPanel";

vi.mock("@/api/taxonomy", () => ({
  fetchInterests: vi.fn().mockResolvedValue([]),
  fetchSkillRows: vi.fn().mockResolvedValue([]),
  fetchTaxonomyStats: vi.fn().mockResolvedValue(null),
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

vi.mock("@/api/postingResolution", () => ({
  fetchResolutionThresholds: vi.fn().mockResolvedValue({
    candidate_trigram_floor: 0,
    candidate_cosine_floor: 0,
    candidate_top_k: 5,
    dedup_trigram_bar: 0.75,
    dedup_cosine_bar: 0.9,
    corroboration_min_postings: 2,
    corroboration_cap: 20,
  }),
  saveResolutionThresholds: vi.fn(),
  fetchResolutionStats: vi.fn().mockResolvedValue({
    last_run: {
      job_id: "job-1",
      status: "succeeded",
      created_at: "2026-11-02T00:00:00Z",
      finished_at: "2026-11-02T00:00:01Z",
      labels: 3,
      exact_hits: 2,
      pass2_matches: 1,
      new_proposals: 0,
      gate_blocks: 0,
      degraded: false,
      replay: false,
    },
    rolling: {
      window: "7d",
      runs: 4,
      replay_runs: 1,
      degraded_runs: 0,
      labels: 9,
      exact_hits: 5,
      pass2_matches: 3,
      new_proposals: 1,
      gate_blocks: 0,
      match_rate: 0.8889,
      new_rate: 0.1111,
      block_rate: 0,
      replay_rate: 0.25,
      degrade_rate: 0,
    },
    failing_schedules: 1,
  }),
  replayPostingResolution: vi.fn(),
  reconcileSkillEmbeddings: vi.fn(),
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

vi.mock("@neuronection/assistant-ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@neuronection/assistant-ui")>();
  return {
    ...actual,
    ConceptGraphView: () => <div data-testid="concept-graph-stub" />,
  };
});

function LocationProbe() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <>
      <span data-testid="location-probe">{location.pathname + location.search}</span>
      <span data-testid="navigation-type">{navigationType}</span>
    </>
  );
}

function renderPage(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Taxonomy />
      <LocationProbe />
    </MemoryRouter>,
  );
}

const probe = () => screen.getByTestId("location-probe").textContent;

describe("taxonomy tab params (pure helpers)", () => {
  it("TAXONOMY_TABS is the declared interests-first order", () => {
    expect([...TAXONOMY_TABS]).toEqual([
      "interests",
      "skills",
      "paths",
      "enrichment",
      "translations",
      "relations",
    ]);
  });

  it("parseTaxonomyTab falls back to interests on missing or unknown values", () => {
    expect(parseTaxonomyTab(null)).toBe("interests");
    expect(parseTaxonomyTab("skills")).toBe("skills");
    expect(parseTaxonomyTab("bogus")).toBe("interests");
  });

  it("RELATION_TABS covers every relations subtab", () => {
    expect([...RELATION_TABS]).toEqual([
      "queue",
      "editor",
      "graph",
      "thresholds",
      "runs",
      "resolution",
    ]);
  });

  it("parseRelationSection falls back to queue on missing or unknown values", () => {
    expect(parseRelationSection(null)).toBe("queue");
    expect(parseRelationSection("graph")).toBe("graph");
    expect(parseRelationSection("resolution")).toBe("resolution");
    expect(parseRelationSection("bogus")).toBe("queue");
  });
});

describe("taxonomy tabs (URL-synced)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("defaults to interests with a clean URL", async () => {
    renderPage("/settings/taxonomy");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Interests" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(probe()).toBe("/settings/taxonomy");
  });

  it("lands a ?tab=skills deep link on Skills", async () => {
    renderPage("/settings/taxonomy?tab=skills");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(probe()).toBe("/settings/taxonomy?tab=skills");
  });

  it("lands ?tab=translations on the review board and keeps the panel off other tabs", async () => {
    const page = renderPage("/settings/taxonomy?tab=translations");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Translations" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByTestId("translations-board")).toBeInTheDocument();
    expect(probe()).toBe("/settings/taxonomy?tab=translations");

    // The board renders ONLY inside its segment: the default tab never
    // mounts it (the old global above-the-tabs placement is gone).
    page.unmount();
    renderPage("/settings/taxonomy");
    expect(screen.queryByTestId("translations-board")).not.toBeInTheDocument();
  });

  it("strips an unknown tab param back to the canonical URL", async () => {
    renderPage("/settings/taxonomy?tab=bogus");
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy"));
    expect(
      screen.getByRole("tab", { name: "Interests" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("lands ?tab=relations&section=graph on the graph subtab", async () => {
    renderPage("/settings/taxonomy?tab=relations&section=graph");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Graph" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByRole("tab", { name: "Relations" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/taxonomy?tab=relations&section=graph");
  });

  it("lands ?tab=relations&section=resolution on the resolution section", async () => {
    renderPage("/settings/taxonomy?tab=relations&section=resolution");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Resolution" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.getByTestId("resolution-section")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("resolution-stats")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("resolution-thresholds")).toBeInTheDocument();
    expect(probe()).toBe("/settings/taxonomy?tab=relations&section=resolution");
  });

  it("canonicalizes the default subtab away", async () => {
    renderPage("/settings/taxonomy?tab=relations&section=queue");
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy?tab=relations"));
    expect(
      screen.getByRole("tab", { name: "Review queue" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("drops a stray section param on non-relations tabs", async () => {
    renderPage("/settings/taxonomy?tab=skills&section=graph");
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy?tab=skills"));
    expect(
      screen.getByRole("tab", { name: "Skills" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to the queue and strips an unknown section param", async () => {
    renderPage("/settings/taxonomy?tab=relations&section=bogus");
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy?tab=relations"));
    expect(
      screen.getByRole("tab", { name: "Review queue" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("ignores a section param on the default tab and cleans the URL", async () => {
    renderPage("/settings/taxonomy?section=graph");
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy"));
    expect(
      screen.getByRole("tab", { name: "Interests" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("writes ?tab=skills on click and enters relations without a section param", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy");
    await user.click(screen.getByRole("tab", { name: "Skills" }));
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy?tab=skills"));
    expect(screen.getByTestId("navigation-type")).toHaveTextContent("REPLACE");
    await user.click(screen.getByRole("tab", { name: "Relations" }));
    await waitFor(() => expect(probe()).toBe("/settings/taxonomy?tab=relations"));
    expect(
      screen.getByRole("tab", { name: "Review queue" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("resets bulk selection and notes when switching tabs and coming back", async () => {
    const { fetchSkillRows, bulkSkillAction } = await import("@/api/taxonomy");
    vi.mocked(fetchSkillRows).mockResolvedValue([
      {
        id: "s1",
        key: "technology-software",
        label: "Software & Apps",
        category: "technology",
        description: "",
        parent_id: null,
        level_anchors: [],
        aliases: [],
        status: "proposed",
        origin: "extraction",
      },
    ]);
    vi.mocked(bulkSkillAction).mockResolvedValue({ affected: ["s1"], failed: [] });
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    await user.click(screen.getByTestId("taxonomy-select"));
    await user.click(screen.getByTestId("taxonomy-bulk-scope"));
    await user.click(screen.getByTestId("taxonomy-bulk-scope-proposed"));
    expect(screen.getByTestId("taxonomy-bulk-bar")).toBeInTheDocument();
    await user.click(screen.getByTestId("taxonomy-bulk-promote"));
    await waitFor(() =>
      expect(screen.getByTestId("taxonomy-bulk-note")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("tab", { name: "Interests" }));
    await user.click(screen.getByRole("tab", { name: "Skills" }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Skills" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(screen.queryByTestId("taxonomy-bulk-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("taxonomy-bulk-note")).not.toBeInTheDocument();
  });
});
