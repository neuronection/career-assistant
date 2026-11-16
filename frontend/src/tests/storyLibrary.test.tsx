import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { StoryLibraryModal } from "@/features/interviews/components/StoryLibraryModal";
import {
  createStory,
  deleteStory,
  fetchStories,
  fetchStorySuggestions,
  updateStory,
} from "@/api/interviewStories";

vi.mock("@/api/interviewStories", () => ({
  fetchStories: vi.fn(),
  fetchStorySuggestions: vi.fn(),
  createStory: vi.fn(),
  updateStory: vi.fn(),
  deleteStory: vi.fn(),
}));

const STORY = {
  id: "s1",
  title: "Cut deploy time",
  competency_keys: ["teamwork"],
  situation: "Slow deploys.",
  task: "Speed them up.",
  action: "Parallelized.",
  result: "40% faster.",
  experience_item_id: null,
  evidence_refs: [],
  created_at: "2026-11-11T00:00:00Z",
  updated_at: "2026-11-11T00:00:00Z",
};

describe("StoryLibraryModal", () => {
  beforeEach(() => {
    vi.mocked(fetchStories).mockResolvedValue([STORY]);
    vi.mocked(fetchStorySuggestions).mockResolvedValue([]);
    vi.mocked(createStory).mockResolvedValue(STORY);
    vi.mocked(updateStory).mockResolvedValue(STORY);
    vi.mocked(deleteStory).mockResolvedValue();
  });

  it("lists stories and creates one from an experience suggestion", async () => {
    vi.mocked(fetchStorySuggestions).mockResolvedValue([
      { experience_item_id: "exp-1", title: "DevOps intern", org: "Acme", hint: "Cut deploys." },
    ]);
    render(<StoryLibraryModal open onClose={vi.fn()} />);
    expect(await screen.findByTestId("story-row-s1")).toHaveTextContent("Cut deploy time");

    fireEvent.click(screen.getByTestId("story-suggestion-exp-1"));
    expect(screen.getByTestId("story-title")).toHaveValue("DevOps intern");
    fireEvent.change(screen.getByTestId("story-result"), {
      target: { value: "40% faster." },
    });
    fireEvent.click(screen.getByTestId("story-save"));
    await waitFor(() =>
      expect(createStory).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "DevOps intern",
          result: "40% faster.",
          experience_item_id: "exp-1",
        }),
      ),
    );
  });

  it("edits and deletes an existing story", async () => {
    render(<StoryLibraryModal open onClose={vi.fn()} />);
    await screen.findByTestId("story-row-s1");
    fireEvent.click(screen.getByTestId("story-edit-s1"));
    expect(screen.getByTestId("story-title")).toHaveValue("Cut deploy time");
    fireEvent.change(screen.getByTestId("story-title"), {
      target: { value: "Faster deploys" },
    });
    fireEvent.click(screen.getByTestId("story-save"));
    await waitFor(() =>
      expect(updateStory).toHaveBeenCalledWith(
        "s1",
        expect.objectContaining({ title: "Faster deploys" }),
      ),
    );
    fireEvent.click(screen.getByTestId("story-delete-s1"));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteStory).toHaveBeenCalledWith("s1"));
  });
});
