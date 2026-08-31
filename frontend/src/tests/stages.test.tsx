import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Dashboard } from "@/pages/Dashboard";
import { useProfileStore } from "@/stores/profileStore";
import { useCatalogStore } from "@/stores/catalogStore";
import { useBootstrapStore, } from "@/stores/bootstrapStore";
import { fetchFeed } from "@/api/engagement";
import type { Bootstrap } from "@/types";

vi.mock("@/api/matching", () => ({
  fetchRankings: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchCandidates: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchFeed: vi.fn().mockResolvedValue({ items: [], total: 0, unseen: 0 }),
    markSeen: vi.fn().mockResolvedValue({ marked: 0 }),
  };
});

vi.mock("@/api/jobs", () => ({
  fetchFamilyTree: vi.fn().mockResolvedValue([]),
  fetchJobs: vi.fn().mockResolvedValue([]),
}));

function bootstrapFor(stage: Bootstrap["career_stage"]): Bootstrap {
  return {
    career_stage: stage,
    stage_source: "explicit",
    features: { universities: stage === "student", grade_fields: stage === "student" },
    suggested_scoring_weights: {
      skills: 3,
      location: 3,
      experience: 1,
      education: 5,
      interests: 4,
    },
    effective_scoring_weights: {
      skills: 3,
      location: 3,
      experience: 1,
      education: 5,
      interests: 4,
    },
    weights_overridden: false,
  };
}

function resetStores(bootstrap: Bootstrap | null) {
  useProfileStore.setState({
    profile: null,
    load: vi.fn().mockResolvedValue(undefined),
  });
  useCatalogStore.setState({
    families: [],
    jobs: [],
    loadFamilies: vi.fn().mockResolvedValue(undefined),
    loadJobs: vi.fn().mockResolvedValue(undefined),
  });
  useBootstrapStore.setState({ bootstrap, loaded: true });
}

describe("Dashboard stage adaptation", () => {
  beforeEach(() => {
    vi.mocked(fetchFeed).mockResolvedValue({ items: [], total: 0, unseen: 0 });
  });

  it("uses the stage tagline and hides universities for a returner", async () => {
    resetStores(bootstrapFor("returning"));
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("dashboard-tagline")).toHaveTextContent(
      /re-entry is a path/i
    );
    await waitFor(() => expect(screen.getByTestId("feed-section")).toBeInTheDocument());
    expect(screen.queryByText("Add your universities")).toBeNull();
  });

  it("keeps the universities module and copy for students", async () => {
    resetStores(bootstrapFor("student"));
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("dashboard-tagline")).toHaveTextContent(
      /fewer than 30 job titles/i
    );
    expect(screen.getByText("Add your universities")).toBeInTheDocument();
  });

  it("shows the default copy when no bootstrap has loaded", async () => {
    resetStores(null);
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("dashboard-tagline")).toHaveTextContent(
      /jobs in the catalog/i
    );
  });
});

describe("stage switching API", () => {
  it("PUTs the chosen stage to /me/stage", async () => {
    const { api } = await import("@/api/client");
    const putSpy = vi
      .spyOn(api, "put")
      .mockResolvedValue({ data: bootstrapFor("switching") });
    const { setStage } = await import("@/api/stages");
    const result = await setStage("switching");
    expect(putSpy).toHaveBeenCalledWith("/me/stage", {
      career_stage: "switching",
    });
    expect(result.career_stage).toBe("switching");
    expect(result.features.universities).toBe(false);
    putSpy.mockRestore();
  });

  it("clears the stage to re-derive it", async () => {
    const { api } = await import("@/api/client");
    const putSpy = vi
      .spyOn(api, "put")
      .mockResolvedValue({ data: bootstrapFor("student") });
    const { setStage } = await import("@/api/stages");
    await setStage(null);
    expect(putSpy).toHaveBeenCalledWith("/me/stage", { career_stage: null });
    putSpy.mockRestore();
  });
});
