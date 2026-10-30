import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Taxonomy } from "@/pages/settings/Taxonomy";
import { fetchSkill, fetchSkillHistory } from "@/api/skills";
import type { SkillDetail, SkillHistoryResponse } from "@/types/wire";

vi.mock("@/api/taxonomy", () => ({
  fetchInterests: vi.fn().mockResolvedValue([]),
  fetchTaxonomyStats: vi.fn().mockResolvedValue(null),
  fetchSkillRows: vi.fn().mockResolvedValue([
    {
      id: "s-sql",
      key: "sql",
      label: "SQL",
      category: "tech",
      description: "Queries.",
      parent_id: null,
      level_anchors: [],
      aliases: ["Sequel"],
      status: "active",
      origin: "bank",
    },
  ]),
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

vi.mock("@/api/skills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
    fetchSkillHistory: vi.fn(),
    fetchMySkills: vi.fn().mockResolvedValue([]),
    fetchSkillOntology: vi.fn().mockResolvedValue([]),
  };
});

const mockedSkill = {
  fetchSkill: vi.mocked(fetchSkill),
  fetchSkillHistory: vi.mocked(fetchSkillHistory),
};

const DETAIL: SkillDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  key: "sql",
  label: "SQL",
  category: "tech",
  description: "Queries.",
  parent_id: null,
  level_anchors: [],
  aliases: ["Sequel"],
  status: "active",
  children_keys: [],
  jobs: [],
  stats: {
    demand_count: 7,
    level_histogram: [],
    avg_required_level: 5,
    user_count: 2,
    first_seen: null,
    last_seen: null,
    corroboration: null,
  },
  merged_into: null,
  origin: "bank",
  parent_key: null,
};

const HISTORY: SkillHistoryResponse = {
  items: [
    {
      id: "h1",
      occurred_at: "2026-10-29T10:00:00Z",
      event: "created",
      actor_kind: "admin",
      actor_ref: {},
      detail: {},
    },
  ],
  total: 1,
  limit: 5,
  offset: 0,
  skill_id: DETAIL.id,
  skill_key: "sql",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/settings/taxonomy?tab=skills"]}>
      <Routes>
        <Route path="/settings/taxonomy" element={<Taxonomy />} />
        <Route path="/skills/:key" element={<div data-testid="skill-page-stub" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Taxonomy skills rows → Details drawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedSkill.fetchSkill.mockResolvedValue(DETAIL);
    mockedSkill.fetchSkillHistory.mockResolvedValue(HISTORY);
  });

  it("opens the preview drawer with stats, history excerpt and an open-page link", async () => {
    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByTestId("taxonomy-row-sql"));

    const drawer = await screen.findByTestId("skill-details-drawer");
    expect(drawer).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /SQL/ })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("drawer-stat-tiles")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("drawer-history")).toHaveTextContent(/Created/);
    const open = screen.getByTestId("drawer-open-page");
    expect(open).toHaveAttribute("href", "/skills/sql");
    expect(mockedSkill.fetchSkill).toHaveBeenCalledWith("sql");
    expect(mockedSkill.fetchSkillHistory).toHaveBeenCalledWith("sql", { limit: 5 });
  });
});
