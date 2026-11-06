import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import * as taxonomyApi from "@/api/taxonomy";
import type { SkillRow } from "@/api/taxonomy";
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
    fetchSkillRows: vi.fn(),
    fetchTaxonomyStats: vi.fn().mockResolvedValue(null),
    bulkSkillAction: vi.fn(),
  };
});

vi.mock("@/components/settings/TranslationsBoard", () => ({
  TranslationsBoard: () => null,
}));

const mocked = vi.mocked(taxonomyApi);

function skill(partial: Partial<SkillRow> & { id: string; key: string; label: string }): SkillRow {
  return {
    category: "tech",
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
  skill({ id: "s-pytorch", key: "pytorch", label: "PyTorch", status: "proposed", origin: "ai" }),
  skill({
    id: "s-langchain",
    key: "langchain",
    label: "LangChain",
    status: "proposed",
    origin: "ai",
  }),
  skill({
    id: "s-excel",
    key: "ms-excel-2016",
    label: "MS Excel 2016",
    status: "deprecated",
    origin: "ai",
  }),
];

async function openSkillsTab() {
  render(
    <MemoryRouter initialEntries={["/settings/taxonomy"]}>
      <Taxonomy />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "Skills" }));
  await screen.findByText("python");
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchInterests.mockResolvedValue([]);
  mocked.fetchSkillRows.mockResolvedValue(SKILLS);
  mocked.bulkSkillAction.mockResolvedValue({ affected: [], failed: [] });
});

describe("Taxonomy bulk actions", () => {
  it("promotes only the applicable selected ids and reports the count", async () => {
    await openSkillsTab();
    fireEvent.click(await screen.findByTestId("taxonomy-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select PyTorch" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select MS Excel 2016" }));
    mocked.bulkSkillAction.mockResolvedValue({ affected: ["s-pytorch"], failed: [] });

    fireEvent.click(screen.getByTestId("taxonomy-bulk-promote"));

    await waitFor(() =>
      expect(mocked.bulkSkillAction).toHaveBeenCalledWith(["s-pytorch"], "promote", undefined),
    );
    expect(await screen.findByText("1 skill updated.")).toBeTruthy();
    await waitFor(() => expect(mocked.fetchSkillRows).toHaveBeenCalledTimes(2));
  });

  it("the proposed scope in the select-all menu seeds the selection (plural count too)", async () => {
    const user = userEvent.setup();
    await openSkillsTab();
    await user.click(await screen.findByTestId("taxonomy-select"));
    await user.click(screen.getByTestId("taxonomy-bulk-scope"));
    await user.click(screen.getByTestId("taxonomy-bulk-scope-proposed"));
    mocked.bulkSkillAction.mockResolvedValue({
      affected: ["s-pytorch", "s-langchain"],
      failed: [],
    });

    fireEvent.click(screen.getByTestId("taxonomy-bulk-promote"));

    await waitFor(() =>
      expect(mocked.bulkSkillAction).toHaveBeenCalledWith(
        ["s-pytorch", "s-langchain"],
        "promote",
        undefined,
      ),
    );
    expect(await screen.findByText("2 skills updated.")).toBeTruthy();
  });

  it("merge sends the non-active sources plus the chosen target", async () => {
    await openSkillsTab();
    fireEvent.click(await screen.findByTestId("taxonomy-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select PyTorch" }));
    fireEvent.change(screen.getByTestId("taxonomy-bulk-merge-target"), {
      target: { value: "s-python" },
    });

    fireEvent.click(screen.getByTestId("taxonomy-bulk-merge"));

    await waitFor(() =>
      expect(mocked.bulkSkillAction).toHaveBeenCalledWith(
        ["s-pytorch"],
        "merge",
        "s-python",
      ),
    );
  });

  it("delete confirms first and lists per-item failures", async () => {
    await openSkillsTab();
    fireEvent.click(await screen.findByTestId("taxonomy-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Python" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select PyTorch" }));
    mocked.bulkSkillAction.mockResolvedValue({
      affected: ["s-python"],
      failed: [
        {
          id: "s-pytorch",
          key: "pytorch",
          reason: "Tag is referenced by 2 job(s) and 1 profile entries",
        },
      ],
    });

    fireEvent.click(screen.getByTestId("taxonomy-bulk-delete"));
    const confirm = await screen.findByRole("button", { name: "Delete" });
    expect(mocked.bulkSkillAction).not.toHaveBeenCalled();
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(mocked.bulkSkillAction).toHaveBeenCalledWith(
        ["s-python", "s-pytorch"],
        "delete",
        undefined,
      ),
    );
    expect(await screen.findByText("1 skill deleted.")).toBeTruthy();
    expect(
      await screen.findByText(/Tag is referenced by 2 job\(s\)/),
    ).toBeTruthy();
  });

  it("leaving select mode clears the selection", async () => {
    await openSkillsTab();
    fireEvent.click(await screen.findByTestId("taxonomy-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select PyTorch" }));
    fireEvent.click(screen.getByTestId("taxonomy-select"));

    expect(screen.queryByTestId("taxonomy-bulk-bar")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Select PyTorch" })).toBeNull();
  });
});
