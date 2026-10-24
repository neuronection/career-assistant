import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { PathExplorer } from "@/features/paths/pages/PathExplorer";
import * as pathsApi from "@/api/paths";
import * as growthApi from "@/api/growth";
import type { CareerPath, PathDetail } from "@/types/wire";

vi.mock("@/api/paths", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/paths")>();
  return {
    ...mod,
    fetchPaths: vi.fn(),
    fetchPathDetail: vi.fn(),
    setPathFlag: vi.fn(),
  };
});
vi.mock("@/api/growth", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/growth")>();
  return { ...mod, createGrowthPlan: vi.fn() };
});
vi.mock("@/api/jobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/jobs")>();
  return { ...mod, fetchFamilyTree: vi.fn().mockResolvedValue([]) };
});

const curated = {
  id: "path-curated",
  job_id: "job-1",
  title: "Curated route to Data Scientist",
  description: "Study then enter.",
  source: "seed",
  status: "published",
  job_code: "data-scientist",
  job_title: "Data Scientist",
  my_flag: null,
  steps: [
    {
      id: "step-1",
      position: 0,
      kind: "skill",
      label: "Learn Python",
      optional: false,
      skill_key: "python",
      skill_label: "Python",
      education_level: null,
      parent_step_id: null,
      edge_label: "",
    },
  ],
} as unknown as CareerPath;

const detail = {
  ...curated,
  skills_total: 1,
  skills_met: 0,
  steps: [
    {
      ...curated.steps![0]!,
      my_flag: null,
      my_note: "",
      skill: {
        skill_id: "skill-1",
        key: "python",
        label: "Python",
        user_level: 2,
        required_level: 6,
      },
    },
  ],
} as unknown as PathDetail;

function mount() {
  return render(
    <MemoryRouter>
      <PathExplorer />
    </MemoryRouter>
  );
}

describe("PathExplorer", () => {
  beforeEach(() => {
    vi.mocked(pathsApi.fetchPaths).mockResolvedValue([curated]);
    vi.mocked(pathsApi.fetchPathDetail).mockResolvedValue(detail);
    vi.mocked(pathsApi.setPathFlag).mockResolvedValue(detail);
    vi.mocked(growthApi.createGrowthPlan).mockResolvedValue({} as never);
  });

  it("renders the rail with the curated group and an honest empty state", async () => {
    vi.mocked(pathsApi.fetchPaths).mockResolvedValue([]);
    mount();
    await waitFor(() =>
      expect(screen.getByText("No paths yet")).toBeInTheDocument()
    );
  });

  it("opens a path and shows header, renderer and step panel", async () => {
    mount();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("path-item-path-curated")).toBeInTheDocument());
    await user.click(screen.getByTestId("path-item-path-curated"));
    await waitFor(() => expect(screen.getByTestId("path-header")).toBeInTheDocument());
    expect(screen.getByTestId("path-header-completeness")).toHaveTextContent(
      "0 of 1 skills already in your profile"
    );
    expect(screen.getByTestId("path-renderer")).toBeInTheDocument();
    expect(screen.getByTestId("paths-growth-add")).toBeInTheDocument();
  });

  it("roundtrips a step mark through the API", async () => {
    const marked = {
      ...detail,
      steps: [{ ...detail.steps![0]!, my_flag: "interested", my_note: "" }],
    } as unknown as PathDetail;
    vi.mocked(pathsApi.setPathFlag).mockResolvedValue(marked);
    mount();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("path-item-path-curated")).toBeInTheDocument());
    await user.click(screen.getByTestId("path-item-path-curated"));
    await waitFor(() => expect(screen.getByTestId("path-renderer")).toBeInTheDocument());
    await user.click(screen.getByTestId("path-view-tree"));
    await user.click(screen.getByTestId("path-step-tree-step-1"));
    await waitFor(() => expect(screen.getByTestId("path-step-panel")).toBeInTheDocument());
    await user.click(screen.getByTestId("path-step-mark-interested"));
    await waitFor(() =>
      expect(pathsApi.setPathFlag).toHaveBeenCalledWith("path-curated", {
        step_id: "step-1",
        flag: "interested",
        note: "",
      })
    );
  });

  it("adds the path to the growth roadmap", async () => {
    mount();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByTestId("path-item-path-curated")).toBeInTheDocument());
    await user.click(screen.getByTestId("path-item-path-curated"));
    await waitFor(() => expect(screen.getByTestId("paths-growth-add")).toBeInTheDocument());
    await user.click(screen.getByTestId("paths-growth-add"));
    await waitFor(() => expect(growthApi.createGrowthPlan).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("Added to your roadmap")).toBeInTheDocument();
  });
});
