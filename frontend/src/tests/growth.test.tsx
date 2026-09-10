import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Growth } from "@/pages/Growth";
import {
  fetchCheckinStatus,
  fetchGrowthPlans,
  fetchRadar,
  patchGrowthStep,
  skipCheckin,
} from "@/api/growth";
import type { GrowthPlanItem, RadarEntry } from "@/types";

vi.mock("@/api/growth", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/growth")>();
  return {
    ...mod,
    fetchGrowthPlans: vi.fn(),
    fetchRadar: vi.fn(),
    fetchCheckinStatus: vi.fn(),
    patchGrowthStep: vi.fn().mockResolvedValue(undefined),
    skipCheckin: vi.fn().mockResolvedValue(undefined),
  };
});

const mockPlans = vi.mocked(fetchGrowthPlans);
const mockRadar = vi.mocked(fetchRadar);
const mockCheckin = vi.mocked(fetchCheckinStatus);

function plan(): GrowthPlanItem {
  return {
    id: "gp1",
    status: "active",
    target_job: { id: "j1", title: "Data Engineer", code: "data-engineer" },
    steps: [
      {
        id: "st1",
        position: 0,
        kind: "skill",
        label: "Raise Python to level 6",
        skill_id: "sk1",
        target_level: 6,
        status: "todo",
        resources: [
          {
            id: "r1",
            kind: "course",
            title: "Python deep dive",
            provider: "Coursera",
            url: "https://courses.example/py",
            cost: "free",
          },
        ],
      },
    ],
  };
}

function radarEntry(): RadarEntry {
  return {
    job_id: "j2",
    code: "ml-engineer",
    title: "ML Engineer",
    family_key: "technology-data",
    fit_score: 6.8,
    deficits: [
      {
        skill_id: "sk2",
        key: "python",
        label: "Python",
        current_level: 4,
        required_level: 6,
        delta: 2,
        importance: "important",
      },
    ],
    headline: "1 skill away from ML Engineer: Python +2",
  };
}

describe("Growth toolkit page", () => {
  beforeEach(() => {
    mockPlans.mockResolvedValue([plan()]);
    mockRadar.mockResolvedValue([radarEntry()]);
    mockCheckin.mockResolvedValue({
      due: false,
      next_at: "2026-11-29T00:00:00Z",
      last_at: null,
    });
  });

  it("renders roadmap steps, resources and radar cards", async () => {
    render(
      <MemoryRouter>
        <Growth />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("growth")).toBeInTheDocument();
    expect(screen.getByText(/Raise Python to level 6/)).toBeInTheDocument();
    expect(screen.getByText(/Python deep dive/)).toBeInTheDocument();
    expect(screen.getByText(/1 skill away from ML Engineer/)).toBeInTheDocument();
    expect(screen.queryByTestId("checkin-banner")).toBeNull();
  });

  it("completes a step at the target level and reloads", async () => {
    render(
      <MemoryRouter>
        <Growth />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("step-done-st1"));
    await waitFor(() =>
      expect(patchGrowthStep).toHaveBeenCalledWith("st1", {
        status: "done",
        completed_level: 6,
      })
    );
  });

  it("shows the check-in banner and skips it", async () => {
    mockCheckin.mockResolvedValue({
      due: true,
      next_at: "2026-08-01T00:00:00Z",
      last_at: null,
    });
    render(
      <MemoryRouter>
        <Growth />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("checkin-banner")).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Remind me in 3 months/));
    await waitFor(() => expect(skipCheckin).toHaveBeenCalled());
  });
});
