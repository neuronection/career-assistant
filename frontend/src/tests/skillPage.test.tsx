import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { useAuthStore } from "@/stores/authStore";
import type { User } from "@/api/auth";
import { SkillPage, skillTabFromParam } from "@/features/skills/pages/SkillPage";
import type {
  SkillDetail,
  SkillHistoryResponse,
  SkillPositionsResponse,
  SkillRelationsResponse,
} from "@/types/wire";

vi.mock("@/api/skills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
    fetchSkillPositions: vi.fn(),
    fetchSkillRelations: vi.fn(),
    fetchSkillHistory: vi.fn(),
    fetchMySkills: vi.fn().mockResolvedValue([]),
    fetchSkillOntology: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return { ...actual, deleteTag: vi.fn(), mergeSkill: vi.fn(), promoteSkill: vi.fn() };
});

import {
  fetchMySkills,
  fetchSkill,
  fetchSkillHistory,
  fetchSkillPositions,
  fetchSkillRelations,
} from "@/api/skills";

class MockIntersectionObserver {
  static latest: MockIntersectionObserver | null = null;
  private callback: IntersectionObserverCallback;
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    MockIntersectionObserver.latest = this;
  }
  static triggerIntersecting() {
    MockIntersectionObserver.latest?.callback(
      [{ isIntersecting: true } as unknown as IntersectionObserverEntry],
      MockIntersectionObserver.latest as unknown as IntersectionObserver
    );
  }
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

const mocked = {
  fetchSkill: vi.mocked(fetchSkill),
  fetchSkillPositions: vi.mocked(fetchSkillPositions),
  fetchSkillRelations: vi.mocked(fetchSkillRelations),
  fetchSkillHistory: vi.mocked(fetchSkillHistory),
  fetchMySkills: vi.mocked(fetchMySkills),
};

const DETAIL: SkillDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  key: "sql",
  label: "SQL",
  category: "general",
  description: "Structured query language.",
  parent_id: null,
  level_anchors: [{ level: 3, label: "Guided", description: "Writes simple queries." }],
  aliases: ["Sequel"],
  status: "active",
  children_keys: [],
  jobs: [],
  stats: {
    demand_count: 12,
    level_histogram: [
      { level: 3, n: 2 },
      { level: 7, n: 5 },
    ],
    avg_required_level: 6.5,
    user_count: 4,
    first_seen: "2026-10-01T00:00:00Z",
    last_seen: "2026-10-29T00:00:00Z",
    corroboration: null,
  },
  merged_into: null,
  origin: "bank",
  parent_key: null,
};

const RELATIONS: SkillRelationsResponse = {
  nodes: [
    { id: "1", key: "sql", label: "SQL", status: "active" },
    { id: "2", key: "query-lang", label: "Query Language", status: "active" },
  ],
  edges: [{ id: "e1", source: "2", target: "1", relation: "is_a" }],
};

const POSITIONS: SkillPositionsResponse = {
  items: [
    {
      id: "p1",
      ref: "DE000001",
      source_id: "s1",
      external_id: "x1",
      title: "Data Analyst",
      org: "ACME",
      org_key: "acme",
      source_key: "",
      location: { city: "Athens", country: "GR" },
      url: "https://jobs.example/1",
      status: "mapped",
      mapping_reason: "",
      needs_review: false,
      notes: "",
      saved: false,
      seen: false,
      posted_at: "2026-10-20T00:00:00Z",
      skills: [{ key: "sql", label: "SQL", required_level: 5, priority: "must_have" }],
    },
    {
      id: "p2",
      ref: "DE000002",
      source_id: "s1",
      external_id: "x2",
      title: "Reporting Lead",
      org: "ACME",
      org_key: "acme",
      source_key: "",
      location: {},
      url: "https://jobs.example/2",
      status: "expired",
      mapping_reason: "",
      needs_review: false,
      notes: "",
      saved: false,
      seen: false,
      posted_at: "2026-09-01T00:00:00Z",
      skills: [],
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

const HISTORY: SkillHistoryResponse = {
  items: [
    {
      id: "h2",
      occurred_at: "2026-10-29T10:00:00Z",
      event: "deprecated",
      actor_kind: "admin",
      actor_ref: { user_id: "u-1" },
      detail: { status: { from: "active", to: "deprecated" } },
    },
    {
      id: "h1",
      occurred_at: "2026-10-01T10:00:00Z",
      event: "created",
      actor_kind: "job",
      actor_ref: {},
      detail: {},
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
  skill_id: DETAIL.id,
  skill_key: "sql",
};

const ME: User = {
  id: "u-1",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_admin: true,
};

function renderPage(initialEntries = ["/skills/sql"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/skills/:key" element={<SkillPage />} />
        <Route path="/postings/search" element={<div data-testid="explore-page" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("skillTabFromParam", () => {
  it("maps known tabs and falls back to overview", () => {
    expect(skillTabFromParam("positions")).toBe("positions");
    expect(skillTabFromParam("graph")).toBe("graph");
    expect(skillTabFromParam("bogus")).toBe("overview");
    expect(skillTabFromParam(null)).toBe("overview");
  });
});

describe("SkillPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: ME, loading: false, status: "authenticated", error: null });
    mocked.fetchSkill.mockResolvedValue(DETAIL);
    mocked.fetchSkillRelations.mockResolvedValue(RELATIONS);
    mocked.fetchSkillPositions.mockResolvedValue(POSITIONS);
    mocked.fetchSkillHistory.mockResolvedValue(HISTORY);
    mocked.fetchMySkills.mockResolvedValue([]);
  });

  it("renders the header, stat tiles and related chips", async () => {
    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("SQL");
    await waitFor(() => expect(screen.getByTestId("stat-tiles")).toBeInTheDocument());
    expect(screen.getAllByTestId("stat-tile-value")[0]).toHaveTextContent("12");
    expect(screen.getByTestId("skill-related")).toBeInTheDocument();
    expect(screen.getByTestId("skill-aliases")).toHaveTextContent("Sequel");
  });

  it("shows the merged banner and hides it otherwise", async () => {
    const { unmount } = renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(screen.queryByTestId("merged-banner")).not.toBeInTheDocument();
    unmount();

    mocked.fetchSkill.mockResolvedValue({
      ...DETAIL,
      status: "deprecated",
      merged_into: "query-lang",
    });
    renderPage();
    expect(await screen.findByTestId("merged-banner")).toBeInTheDocument();
    expect(screen.getByTestId("merged-target-link")).toHaveAttribute("href", "/skills/query-lang");
  });

  it("gates the admin header actions on user.is_admin", async () => {
    const { unmount } = renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(screen.getByTestId("skill-deprecate")).toBeInTheDocument();
    expect(screen.getByTestId("skill-delete")).toBeInTheDocument();
    unmount();

    useAuthStore.setState({ user: { ...ME, is_admin: false } });
    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-deprecate")).not.toBeInTheDocument();
    expect(screen.queryByTestId("skill-delete")).not.toBeInTheDocument();
  });

  it("lazily loads the positions tab on the existing posting card", async () => {
    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(mocked.fetchSkillPositions).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
    await waitFor(() => expect(mocked.fetchSkillPositions).toHaveBeenCalled());
    expect(await screen.findAllByTestId("posting-card")).toHaveLength(2);
    expect(screen.getByTestId("positions-count")).toHaveTextContent("2");
    expect(screen.getByTestId("positions-explore-link")).toHaveAttribute(
      "href",
      "/postings/search?skills=sql",
    );
  });

  it("auto-loads more positions when the sentinel scrolls into view", async () => {
    const items = POSITIONS.items ?? [];
    const extra = (id: string, ref: string, title: string) => ({
      ...items[0],
      id,
      ref,
      title,
    });
    const full = [
      ...items,
      extra("p3", "DE000003", "Analytics Engineer"),
      extra("p4", "DE000004", "BI Developer"),
      extra("p5", "DE000005", "Data Engineer"),
    ];
    mocked.fetchSkillPositions.mockImplementation(async (_key, params) => ({
      items: (params?.limit ?? 20) >= 40 ? full : POSITIONS.items,
      total: full.length,
      limit: params?.limit ?? 20,
      offset: 0,
    }));

    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Positions" }));
    expect(await screen.findAllByTestId("posting-card")).toHaveLength(2);
    expect(screen.getByTestId("positions-count")).toHaveTextContent("5");

    // reaching the sentinel auto-loads the next page — no button anymore
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
    MockIntersectionObserver.triggerIntersecting();
    await waitFor(() => expect(mocked.fetchSkillPositions.mock.calls.length).toBe(2));
    expect(await screen.findAllByTestId("posting-card")).toHaveLength(5);
    expect(mocked.fetchSkillPositions).toHaveBeenLastCalledWith(
      "sql",
      expect.objectContaining({ limit: 40 })
    );
  });

  it("lazily loads the graph tab with the depth-1 subgraph", async () => {
    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(mocked.fetchSkillRelations).toHaveBeenCalledTimes(1); // overview related chips

    fireEvent.click(screen.getByRole("tab", { name: "Graph" }));
    expect(await screen.findByTestId("skill-graph")).toBeInTheDocument();
    expect(mocked.fetchSkillRelations).toHaveBeenCalledTimes(1); // one fetch serves both
  });

  it("renders the history timeline newest first with actor roles", async () => {
    renderPage();
    expect(await screen.findByTestId("skill-page")).toBeInTheDocument();
    expect(mocked.fetchSkillHistory).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    const rows = await screen.findAllByTestId("history-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-event", "deprecated");
    expect(rows[0]).toHaveTextContent("admin");
    expect(rows[1]).toHaveAttribute("data-event", "created");
    expect(screen.getByTestId("history-count")).toHaveTextContent("2");
  });

  it("shows the personal block with the user's own level", async () => {
    mocked.fetchMySkills.mockResolvedValue([
      {
        skill_id: DETAIL.id,
        key: "sql",
        label: "SQL",
        category: "general",
        level: 4,
        source: "self_report",
        confidence: 1,
        level_anchors: [],
        derive_enabled: true,
      },
    ]);
    renderPage();
    await screen.findByTestId("skill-page");
    await waitFor(() =>
      expect(screen.getByTestId("skill-personal")).toHaveTextContent("Your level: 4/10"),
    );
  });

  it("renders the 404 state for unknown keys", async () => {
    mocked.fetchSkill.mockRejectedValue(new Error("Request failed with status code 404"));
    renderPage();
    expect(await screen.findByText("Skill not found")).toBeInTheDocument();
  });
});
