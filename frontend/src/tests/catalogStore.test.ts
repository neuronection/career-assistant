import { describe, expect, it, vi, beforeEach } from "vitest";
import { useCatalogStore } from "@/stores/catalogStore";
import * as jobsApi from "@/api/jobs";
import type { Job } from "@/types";

vi.mock("@/api/jobs");

const mocked = vi.mocked(jobsApi);

function makeJob(code: string): Job {
  return {
    id: code,
    code,
    title: code,
    family_key: "technology",
    short_description: "desc",
    status: "published",
    source: "seed",
    attributes: {
      subjects: [],
      work_style: {
        teamwork: 3,
        environment: 3,
        structure: 3,
        pace: 3,
        leadership: 3,
        physical_activity: "light",
      },
      education: { level: "bachelor", fields: [] },
      physical: { activity: "light", requirements: [] },
      salary: { currency: "USD", entry: null, median: null, senior: null },
      demand: { outlook: "stable", note: "", sources: {} },
      environments: ["office"],
      typical_positives: [],
      typical_negatives: [],
    },
    interests: [{ key: "technology-software", label: "Software & Apps" }],
    skills: [],
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("catalogStore", () => {
  beforeEach(() => {
    useCatalogStore.setState({ families: [], jobs: [], total: 0, loading: false, filters: {} });
    vi.clearAllMocks();
  });

  it("loadJobs fetches and merges filters", async () => {
    mocked.fetchJobs.mockResolvedValue([makeJob("software-developer")]);
    await useCatalogStore.getState().loadJobs({ demand: "hot" });
    expect(useCatalogStore.getState().jobs).toHaveLength(1);
    expect(useCatalogStore.getState().filters.demand).toBe("hot");
    expect(mocked.fetchJobs).toHaveBeenCalledWith(expect.objectContaining({ demand: "hot", page_size: 100 }));
  });

  it("loadFamilies stores tree", async () => {
    mocked.fetchFamilyTree.mockResolvedValue([
      {
        id: "1",
        key: "technology",
        label: "Technology",
        parent_id: null,
        path: "technology",
        level: 0,
        description: "",
        job_count: 5,
        children: [],
      },
    ]);
    await useCatalogStore.getState().loadFamilies();
    expect(useCatalogStore.getState().families[0].key).toBe("technology");
  });
});
