import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { deleteSearch, fetchSearches, recordSearch, updateSearch } from "@/api/engagement";
import { PresetBar } from "@/features/postings/components/postings/PresetBar";
import {
  DEFAULT_FILTERS,
  parseFilters,
  type Filters,
} from "@/features/catalog/exploreParams";
import type { SearchRecord } from "@/types/wire";

vi.mock("@/api/engagement", () => ({
  fetchSearches: vi.fn(),
  recordSearch: vi.fn(),
  updateSearch: vi.fn(),
  deleteSearch: vi.fn(),
}));

const mocked = {
  fetchSearches: vi.mocked(fetchSearches),
  recordSearch: vi.mocked(recordSearch),
  updateSearch: vi.mocked(updateSearch),
  deleteSearch: vi.mocked(deleteSearch),
};

function preset(overrides: Partial<SearchRecord> = {}): SearchRecord {
  return {
    id: "s1",
    scope: "postings",
    query: "",
    filters: { seniority: "senior", seen_exclude: true },
    result_count: 7,
    saved: true,
    name: "Senior unseen",
    created_at: "2026-10-30T00:00:00Z",
    ...overrides,
  } as SearchRecord;
}

function filters(search = ""): Filters {
  return parseFilters(new URLSearchParams(search));
}

function renderBar(onApply = vi.fn(), current: Filters = filters("q=engineer")) {
  render(<PresetBar filters={current} total={12} onApply={onApply} />);
  return onApply;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchSearches.mockResolvedValue([preset()]);
  mocked.recordSearch.mockResolvedValue(preset({ id: "s2", name: "Engineer" }));
  mocked.updateSearch.mockResolvedValue(preset());
  mocked.deleteSearch.mockResolvedValue(undefined);
});

describe("PresetBar", () => {
  it("lists saved presets and applies one on click", async () => {
    const onApply = renderBar();
    expect(await screen.findByTestId("preset-s1")).toHaveTextContent("Senior unseen");
    fireEvent.click(screen.getByTestId("preset-s1"));
    expect(onApply).toHaveBeenCalledTimes(1);
    const applied = onApply.mock.calls[0][0] as Filters;
    expect(applied.seniority).toEqual(["senior"]);
    expect(applied.seenExclude).toBe(true);
  });

  it("shows the filters stored in a preset", async () => {
    const user = userEvent.setup();
    renderBar();
    await screen.findByTestId("preset-s1");
    await user.click(screen.getByTestId("preset-s1-menu"));
    const summary = await screen.findByTestId("preset-s1-summary");
    expect(summary).toHaveTextContent("Seniority: Senior");
    expect(summary).toHaveTextContent("Hide seen");
  });

  it("updates a preset to the current view from its menu", async () => {
    const user = userEvent.setup();
    renderBar(vi.fn(), filters("q=engineer&seniority=lead"));
    await screen.findByTestId("preset-s1");
    await user.click(screen.getByTestId("preset-s1-menu"));
    await user.click(await screen.findByRole("menuitem", { name: "Update with current filters" }));
    await waitFor(() =>
      expect(mocked.updateSearch).toHaveBeenCalledWith(
        "s1",
        expect.objectContaining({
          query: "engineer",
          result_count: 12,
          filters: expect.objectContaining({ q: "engineer", seniority: "lead" }),
        })
      )
    );
  });

  it("renames a preset", async () => {
    const user = userEvent.setup();
    renderBar();
    await screen.findByTestId("preset-s1");
    await user.click(screen.getByTestId("preset-s1-menu"));
    await user.click(await screen.findByRole("menuitem", { name: "Rename" }));
    fireEvent.change(await screen.findByTestId("preset-rename-input"), {
      target: { value: "Senior only" },
    });
    fireEvent.click(screen.getByTestId("preset-rename-confirm"));
    await waitFor(() =>
      expect(mocked.updateSearch).toHaveBeenCalledWith("s1", { name: "Senior only" })
    );
  });

  it("deletes a preset after confirmation", async () => {
    const user = userEvent.setup();
    renderBar();
    await screen.findByTestId("preset-s1");
    await user.click(screen.getByTestId("preset-s1-menu"));
    await user.click(await screen.findByRole("menuitem", { name: "Delete preset" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete preset" }));
    await waitFor(() => expect(mocked.deleteSearch).toHaveBeenCalledWith("s1"));
  });

  it("saves the current view as a named preset", async () => {
    renderBar();
    await screen.findByTestId("preset-bar");
    const save = screen.getByTestId("preset-save");
    await waitFor(() => expect(save).not.toBeDisabled());
    expect(save).toHaveTextContent("Save current view");
    fireEvent.click(save);
    const nameInput = await screen.findByTestId("preset-name-input");
    expect(nameInput).toHaveValue("engineer");
    fireEvent.change(nameInput, { target: { value: "Backend search" } });
    fireEvent.click(screen.getByTestId("preset-save-confirm"));
    await waitFor(() =>
      expect(mocked.recordSearch).toHaveBeenCalledWith(
        expect.objectContaining({
          scope: "postings",
          name: "Backend search",
          saved: true,
          query: "engineer",
          filters: expect.objectContaining({ q: "engineer" }),
        })
      )
    );
  });

  it("offers to update the active preset instead of duplicating it", async () => {
    mocked.fetchSearches.mockResolvedValue([
      preset({ filters: { q: "engineer" }, name: "Engineer" }),
    ]);
    renderBar(vi.fn(), filters("q=engineer"));
    const save = await screen.findByTestId("preset-save");
    await waitFor(() => expect(save).toHaveTextContent("Update Engineer"));
    fireEvent.click(save);
    fireEvent.click(await screen.findByTestId("preset-save-confirm"));
    await waitFor(() =>
      expect(mocked.updateSearch).toHaveBeenCalledWith(
        "s1",
        expect.objectContaining({ query: "engineer", result_count: 12 })
      )
    );
    expect(mocked.recordSearch).not.toHaveBeenCalled();
  });

  it("disables saving an empty filter set", async () => {
    renderBar(vi.fn(), DEFAULT_FILTERS);
    await screen.findByTestId("preset-bar");
    await waitFor(() => expect(screen.getByTestId("preset-save")).toBeDisabled());
  });
});
