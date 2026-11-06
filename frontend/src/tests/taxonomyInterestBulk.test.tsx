import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import * as taxonomyApi from "@/api/taxonomy";
import type { Tag } from "@/api/taxonomy";
import { Taxonomy } from "@/pages/settings/Taxonomy";

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return {
    ...actual,
    fetchJobProposals: vi.fn().mockResolvedValue({ items: [], legacy_count: 0, next_cursor: null, total: 0 }),
    regenerateJobProposals: vi.fn(),
    fetchDuplicateJobTypes: vi.fn().mockResolvedValue({ groups: [] }),
    mergeJobTypes: vi.fn(),
    fetchInterests: vi.fn(),
    fetchSkillRows: vi.fn().mockResolvedValue([]),
    fetchTaxonomyStats: vi.fn().mockResolvedValue(null),
    bulkInterestAction: vi.fn(),
  };
});

vi.mock("@/components/settings/TranslationsBoard", () => ({
  TranslationsBoard: () => null,
}));

const mocked = vi.mocked(taxonomyApi);

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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/settings/taxonomy"]}>
      <Taxonomy />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchInterests.mockResolvedValue(TAGS);
  mocked.fetchSkillRows.mockResolvedValue([]);
  mocked.bulkInterestAction.mockResolvedValue({ affected: [], failed: [] });
});

describe("taxonomy interest bulk selection", () => {
  it("deprecates only the active selected interests and reports the count", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("taxonomy-row-science-physics");

    await user.click(screen.getByTestId("taxonomy-select"));
    await user.click(screen.getByRole("checkbox", { name: "Select Physics" }));
    await user.click(screen.getByRole("checkbox", { name: "Select Rowing" }));
    expect(screen.getByTestId("taxonomy-bulk-deprecate")).toHaveTextContent("(1)");

    mocked.bulkInterestAction.mockResolvedValue({
      affected: ["i-physics"],
      failed: [],
    });
    await user.click(screen.getByTestId("taxonomy-bulk-deprecate"));

    await waitFor(() =>
      expect(mocked.bulkInterestAction).toHaveBeenCalledWith(["i-physics"], "deprecate"),
    );
    expect(await screen.findByText("1 interest updated.")).toBeInTheDocument();
  });

  it("toasts row clicks into selection and keeps details behind the open control", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("taxonomy-row-arts-painting");

    await user.click(screen.getByTestId("taxonomy-select"));
    await user.click(screen.getByTestId("taxonomy-row-arts-painting"));

    expect(screen.queryByTestId("interest-details-drawer")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Painting" })).toBeChecked();

    await user.click(screen.getByTestId("taxonomy-row-open-arts-painting"));
    expect(await screen.findByTestId("interest-details-drawer")).toBeInTheDocument();
  });

  it("selects a whole group from its tri-state header", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("taxonomy-group-science");

    await user.click(screen.getByTestId("taxonomy-select"));
    const groupHeader = within(screen.getByTestId("taxonomy-group-science"));
    await user.click(groupHeader.getByRole("checkbox", { name: /Science/ }));

    expect(within(screen.getByTestId("taxonomy-group-science")).getByRole("checkbox", {
      name: /Science/,
    })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("taxonomy-bulk-count")).toHaveTextContent("1 selected");

    await user.click(within(screen.getByTestId("taxonomy-group-science")).getByRole("checkbox", {
      name: /Science/,
    }));
    expect(screen.getByTestId("taxonomy-bulk-mode")).toHaveTextContent("Selection mode");
  });

  it("extends the selection with a shift-click across the visible order", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("taxonomy-row-science-physics");

    await user.click(screen.getByTestId("taxonomy-select"));
    await user.click(screen.getByTestId("taxonomy-row-science-physics"));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByTestId("taxonomy-row-arts-painting"));
    await user.keyboard("{/Shift}");

    expect(screen.getByTestId("taxonomy-bulk-count")).toHaveTextContent("2 selected");
    expect(screen.getByRole("checkbox", { name: "Select Painting" })).toBeChecked();
  });

  it("names the hidden subset before a destructive batch", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("taxonomy-row-science-physics");

    await user.click(screen.getByTestId("taxonomy-select"));
    await user.click(screen.getByRole("checkbox", { name: "Select all 3" }));
    await user.click(screen.getByTestId("taxonomy-filter-deprecated"));

    expect(screen.getByTestId("taxonomy-bulk-hidden")).toHaveTextContent(
      "2 hidden by filters",
    );
    await user.click(screen.getByTestId("taxonomy-bulk-delete"));

    expect(
      await screen.findByText(/2 of them are hidden by the current filters/),
    ).toBeInTheDocument();
    mocked.bulkInterestAction.mockResolvedValue({
      affected: ["i-physics", "i-painting", "i-rowing"],
      failed: [],
    });
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(mocked.bulkInterestAction).toHaveBeenCalledWith(
        expect.arrayContaining(["i-physics", "i-painting", "i-rowing"]),
        "delete",
      ),
    );
    expect(await screen.findByText("3 interests deleted.")).toBeInTheDocument();
  });
});
