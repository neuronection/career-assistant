import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Experience } from "@/pages/Experience";
import {
  fetchExperience,
  fetchDerivation,
  applyDerivation,
  createExperienceItem,
} from "@/api/experience";
import { fetchSkillOntology } from "@/api/skills";

vi.mock("@/api/experience", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/experience")>();
  return {
    ...mod,
    fetchExperience: vi.fn(),
    fetchDerivation: vi.fn(),
    applyDerivation: vi.fn(),
    createExperienceItem: vi.fn(),
    updateExperienceItem: vi.fn(),
    deleteExperienceItem: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/skills", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...mod,
    fetchSkillOntology: vi.fn(),
  };
});

const ITEM = {
  id: "e1",
  kind: "internship" as const,
  title: "DevOps intern",
  org_name: "Acme",
  org_id: null,
  start: "2025-01-01",
  end: "2025-12-31",
  open_ended: false,
  hours_per_week: 40,
  onsite_policy: null,
  description: "",
  links: [],
  source: "self_report" as const,
  status: "active" as const,
  created_at: "2026-09-02T00:00:00Z",
  skills: [
    {
      skill_id: "s1",
      skill_key: "python",
      skill_label: "Python",
      role_in_item: "primary" as const,
      level_claim: null,
      last_used: null,
    },
  ],
  achievements: [],
};

describe("Experience page (plan 40)", () => {
  beforeEach(() => {
    vi.mocked(fetchExperience).mockResolvedValue({
      items: [ITEM],
      years_of_experience: 0.9,
    });
    vi.mocked(fetchDerivation).mockResolvedValue({
      skills: [
        {
          skill_id: "s1",
          skill_label: "Python",
          months: 7.2,
          level: 3.2,
          confidence: 0.2,
          supporting_items: ["e1"],
        },
      ],
      years_of_experience: 0.9,
    });
    vi.mocked(fetchSkillOntology).mockResolvedValue([
      { key: "python", label: "Python" },
      { key: "sql", label: "SQL" },
    ] as never);
    vi.mocked(applyDerivation).mockResolvedValue({
      applied: 1,
      conflicts: [],
      derived: [],
    });
  });

  it("renders items, derived levels and years badge", async () => {
    render(
      <MemoryRouter>
        <Experience />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("experience-item")).toHaveTextContent(
      "DevOps intern"
    );
    expect(screen.getByTestId("years-of-experience")).toHaveTextContent("0.9y");
    const panel = await screen.findByTestId("derivation-panel");
    expect(panel).toHaveTextContent("Python");
    expect(panel).toHaveTextContent("level 3.2");
  });

  it("creates an item through the guided form", async () => {
    vi.mocked(createExperienceItem).mockResolvedValue(ITEM);
    render(
      <MemoryRouter>
        <Experience />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("add-experience"));
    fireEvent.change(screen.getByTestId("experience-title"), {
      target: { value: "Backend job" },
    });
    fireEvent.change(screen.getByTestId("experience-start"), {
      target: { value: "2025-01-01" },
    });
    fireEvent.change(screen.getByTestId("experience-end"), {
      target: { value: "2025-12-31" },
    });
    fireEvent.change(screen.getByTestId("skill-select"), {
      target: { value: "python" },
    });
    fireEvent.click(screen.getByTestId("experience-save"));
    await waitFor(() =>
      expect(createExperienceItem).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Backend job",
          skills: [expect.objectContaining({ skill_key: "python" })],
        })
      )
    );
  });

  it("applies derivation and reports the outcome", async () => {
    render(
      <MemoryRouter>
        <Experience />
      </MemoryRouter>
    );
    const button = await screen.findByTestId("apply-derivation");
    fireEvent.click(button);
    expect(await screen.findByTestId("apply-state")).toHaveTextContent(
      "Applied 1 skill level(s)"
    );
  });
});
