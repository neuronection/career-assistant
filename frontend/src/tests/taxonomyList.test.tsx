import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as taxonomyApi from "@/api/taxonomy";
import type { SkillRow, Tag } from "@/api/taxonomy";
import { fetchSkill, fetchSkillHistory } from "@/api/skills";
import type { SkillDetail, SkillHistoryResponse } from "@/types/wire";
import { Taxonomy } from "@/pages/settings/Taxonomy";

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return {
    ...actual,
    fetchInterests: vi.fn(),
    fetchSkillRows: vi.fn(),
    bulkSkillAction: vi.fn(),
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    promoteSkill: vi.fn(),
    mergeSkill: vi.fn(),
  };
});

vi.mock("@/api/skills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
    fetchSkillHistory: vi.fn(),
  };
});

vi.mock("@/components/settings/TranslationsBoard", () => ({
  TranslationsBoard: () => null,
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

const mocked = vi.mocked(taxonomyApi);
const mockedSkill = {
  fetchSkill: vi.mocked(fetchSkill),
  fetchSkillHistory: vi.mocked(fetchSkillHistory),
};

function tag(partial: Partial<Tag> & { id: string; key: string; label: string }): Tag {
  return {
    category: "science",
    description: "",
    deprecated: false,
    ...partial,
  };
}

const TAGS: Tag[] = [
  tag({
    id: "i-physics",
    key: "science-physics",
    label: "Physics",
    category: "science",
    description: "Natural science of matter",
  }),
  tag({ id: "i-painting", key: "arts-painting", label: "Painting", category: "arts" }),
  tag({
    id: "i-rowing",
    key: "sports-rowing",
    label: "Rowing",
    category: "sports",
    deprecated: true,
  }),
];

function skill(
  partial: Partial<SkillRow> & { id: string; key: string; label: string },
): SkillRow {
  return {
    category: "technical",
    description: "",
    parent_id: null,
    level_anchors: [],
    aliases: [],
    status: "active",
    origin: "import",
    ...partial,
  };
}

const SKILLS: SkillRow[] = [
  skill({ id: "s-python", key: "python", label: "Python", status: "active" }),
  skill({
    id: "s-pytorch",
    key: "pytorch",
    label: "PyTorch",
    status: "proposed",
    origin: "ai",
    aliases: ["torch"],
  }),
  skill({
    id: "s-excel",
    key: "ms-excel-2016",
    label: "MS Excel 2016",
    status: "deprecated",
    origin: "ai",
  }),
];

const PROPOSED_DETAIL: SkillDetail = {
  id: "s-pytorch",
  key: "pytorch",
  label: "PyTorch",
  category: "technical",
  description: "",
  parent_id: null,
  level_anchors: [],
  aliases: ["torch"],
  status: "proposed",
  children_keys: [],
  jobs: [],
  stats: null,
  merged_into: null,
  origin: "ai",
  parent_key: null,
};

const HISTORY: SkillHistoryResponse = {
  items: [],
  total: 0,
  limit: 5,
  offset: 0,
  skill_id: "s-pytorch",
  skill_key: "pytorch",
};

function renderPage(initialEntry = "/settings/taxonomy") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/settings/taxonomy" element={<Taxonomy />} />
        <Route path="/skills/:key" element={<div data-testid="skill-page-stub" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchInterests.mockResolvedValue(TAGS);
  mocked.fetchSkillRows.mockResolvedValue(SKILLS);
  mocked.bulkSkillAction.mockResolvedValue({ affected: [], failed: [] });
  mocked.updateTag.mockResolvedValue(TAGS[0]);
  mocked.deleteTag.mockResolvedValue({});
  mocked.promoteSkill.mockResolvedValue(SKILLS[1]);
  mockedSkill.fetchSkill.mockResolvedValue(PROPOSED_DETAIL);
  mockedSkill.fetchSkillHistory.mockResolvedValue(HISTORY);
});

describe("TaxonomyList (interests)", () => {
  it("groups rows by category with a count pill and category icons", async () => {
    renderPage();

    await screen.findByTestId("taxonomy-group-science");
    expect(screen.getByTestId("taxonomy-group-count-science")).toHaveTextContent("1");
    expect(screen.getByTestId("taxonomy-group-arts")).toBeInTheDocument();
    expect(screen.getByTestId("taxonomy-group-sports")).toBeInTheDocument();
    expect(screen.getByTestId("taxonomy-row-science-physics")).toBeInTheDocument();
    expect(screen.getByTestId("taxonomy-row-arts-painting")).toBeInTheDocument();
  });

  it("collapses and re-expands a category group", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByTestId("taxonomy-row-science-physics");
    await user.click(screen.getByTestId("taxonomy-group-toggle-science"));
    expect(
      screen.queryByTestId("taxonomy-row-science-physics"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("taxonomy-group-toggle-science"));
    expect(screen.getByTestId("taxonomy-row-science-physics")).toBeInTheDocument();
  });

  it("searches across label, key and description (debounced)", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByTestId("taxonomy-row-science-physics");
    await user.type(
      screen.getByPlaceholderText("Search by name, key or alias…"),
      "physics",
    );

    await waitFor(() =>
      expect(screen.queryByTestId("taxonomy-row-arts-painting")).toBeNull(),
    );
    expect(screen.getByTestId("taxonomy-row-science-physics")).toBeInTheDocument();
  });

  it("shows the no-match empty state when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByTestId("taxonomy-row-science-physics");
    await user.type(
      screen.getByPlaceholderText("Search by name, key or alias…"),
      "zzzz",
    );

    expect(await screen.findByText("No matches")).toBeInTheDocument();
  });

  it("filters by status chips with counts", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByTestId("taxonomy-row-sports-rowing");
    expect(screen.getByTestId("taxonomy-filter-deprecated")).toHaveTextContent("1");
    await user.click(screen.getByTestId("taxonomy-filter-deprecated"));

    expect(screen.getByTestId("taxonomy-row-sports-rowing")).toBeInTheDocument();
    expect(screen.queryByTestId("taxonomy-row-science-physics")).toBeNull();
  });

  it("opens the interest drawer from a row click and toggles deprecation from it", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("taxonomy-row-science-physics"));

    const drawer = await screen.findByTestId("interest-details-drawer");
    expect(drawer).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Physics/ })).toBeInTheDocument();
    await user.click(screen.getByTestId("drawer-status-action"));

    await waitFor(() =>
      expect(mocked.updateTag).toHaveBeenCalledWith("interests", "i-physics", {
        deprecated: true,
      }),
    );
  });

  it("edits the interest inside the drawer", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("taxonomy-row-arts-painting"));
    await screen.findByTestId("interest-details-drawer");
    await user.click(screen.getByTestId("drawer-edit-toggle"));
    await user.clear(screen.getByTestId("drawer-edit-label"));
    await user.type(screen.getByTestId("drawer-edit-label"), "Oil painting");
    await user.click(screen.getByTestId("drawer-edit-save"));

    await waitFor(() =>
      expect(mocked.updateTag).toHaveBeenCalledWith("interests", "i-painting", {
        label: "Oil painting",
        category: "arts",
        description: "",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("drawer-edit-form")).toBeNull(),
    );
  });

  it("confirms before deleting from the drawer", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByTestId("taxonomy-row-arts-painting"));
    await screen.findByTestId("interest-details-drawer");
    await user.click(screen.getByTestId("drawer-delete"));
    expect(mocked.deleteTag).not.toHaveBeenCalled();

    const confirmButtons = await screen.findAllByRole("button", { name: "Delete" });
    await user.click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() =>
      expect(mocked.deleteTag).toHaveBeenCalledWith("interests", "i-painting"),
    );
  });

  it("opens the drawer with Enter on a focused row", async () => {
    const user = userEvent.setup();
    renderPage();

    const row = await screen.findByTestId("taxonomy-row-science-physics");
    row.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("interest-details-drawer")).toBeInTheDocument();
  });
});

describe("TaxonomyList (skills)", () => {
  it("groups by status, proposed first", async () => {
    renderPage("/settings/taxonomy?tab=skills");

    const proposedGroup = await screen.findByTestId("taxonomy-group-proposed");
    expect(proposedGroup).toBeInTheDocument();
    expect(screen.getByTestId("taxonomy-group-active")).toBeInTheDocument();
    expect(screen.getByTestId("taxonomy-group-deprecated")).toBeInTheDocument();
    expect(
      proposedGroup.compareDocumentPosition(screen.getByTestId("taxonomy-group-active")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByTestId("taxonomy-row-pytorch")).toBeInTheDocument();
  });

  it("opens the skills drawer from a row click and promotes a proposed skill from it", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");

    await user.click(await screen.findByTestId("taxonomy-row-pytorch"));

    const drawer = await screen.findByTestId("skill-details-drawer");
    expect(drawer).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /PyTorch/ })).toBeInTheDocument();
    await user.click(screen.getByTestId("drawer-promote"));

    await waitFor(() => expect(mocked.promoteSkill).toHaveBeenCalledWith("s-pytorch"));
  });

  it("keeps the Details affordance reachable via Enter on the row", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");

    const row = await screen.findByTestId("taxonomy-row-python");
    row.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("skill-details-drawer")).toBeInTheDocument();
  });

  it("merges a non-active skill into a chosen target from the drawer", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");

    await user.click(await screen.findByTestId("taxonomy-row-pytorch"));
    await screen.findByTestId("skill-details-drawer");
    await user.click(screen.getByTestId("drawer-merge-toggle"));
    fireEvent.change(screen.getByTestId("drawer-merge-target"), {
      target: { value: "s-python" },
    });
    await user.click(screen.getByTestId("drawer-merge-confirm"));

    await waitFor(() =>
      expect(mocked.mergeSkill).toHaveBeenCalledWith("s-pytorch", "s-python"),
    );
  });

  it("shows bulk checkboxes only while select mode is on", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");

    await screen.findByTestId("taxonomy-row-python");
    expect(
      screen.queryByRole("checkbox", { name: "Select Python" }),
    ).toBeNull();

    await user.click(screen.getByTestId("taxonomy-select-toggle"));
    expect(
      await screen.findByRole("checkbox", { name: "Select Python" }),
    ).toBeInTheDocument();
  });

  it("filters skills by the proposed chip", async () => {
    const user = userEvent.setup();
    renderPage("/settings/taxonomy?tab=skills");

    await screen.findByTestId("taxonomy-row-pytorch");
    expect(screen.getByTestId("taxonomy-filter-proposed")).toHaveTextContent("1");
    await user.click(screen.getByTestId("taxonomy-filter-proposed"));

    expect(screen.getByTestId("taxonomy-row-pytorch")).toBeInTheDocument();
    expect(screen.queryByTestId("taxonomy-row-python")).toBeNull();
  });
});
