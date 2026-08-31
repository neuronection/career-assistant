import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProfileEdit } from "@/pages/ProfileEdit";
import { useProfileStore } from "@/stores/profileStore";
import type { Profile } from "@/types";

const fetchProfile = vi.fn();

vi.mock("@/api/profile", () => ({
  fetchProfile: (...args: unknown[]) => fetchProfile(...args),
  saveProfileSection: vi.fn(),
  analyzeProfile: vi.fn(),
  fetchInterests: vi.fn().mockResolvedValue([]),
  fetchSkills: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/skills", () => ({
  fetchMySkills: vi.fn().mockResolvedValue([]),
  fetchSkillOntology: vi.fn().mockResolvedValue([]),
  saveMySkills: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { setState: vi.fn() },
}));

function makeProfile(): Profile {
  return {
    basics: { birth_year: 2008, education_level: "high_school", grade: null, country: "GR", city: "Athens" },
    academics: { favorite_subjects: [], gpa_band: "unknown", languages: [] },
    interests: [{ tag_key: "technology-software", weight: 3, source: "self" }],
    hobbies: [],
    likes: [],
    dislikes: [],
    aspirations: [],
    work_preferences: {
      teamwork: 3, environment: 3, structure: 3, pace: 3, leadership: 3,
      remote_ok: true, focus_areas: ["ideas"], salary_priority: 3,
      stability_priority: 3, physical_activity: "light", creativity_priority: 3,
    },
    experience: [],
    preferences: { scoring_weights: { skills: 3, location: 3, experience: 3, education: 3, interests: 3 } },
    constraints: { physical_conditions: [], max_education_years: null, willing_to_relocate: true, hours_available_per_week: null },
    ai_summary: null,
    completeness: { percent: 50, sections: {} },
  };
}

describe("ProfileEdit fetch loop regression", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProfileStore.setState({ profile: null, interests: [], skills: [], loading: false });
    fetchProfile.mockResolvedValue(makeProfile());
  });

  it("calls GET /profile exactly once on mount (no render loop)", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("profile-edit")).toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchProfile).toHaveBeenCalledTimes(1);
  });

  it("does not refetch when the profile is already in the store", async () => {
    useProfileStore.setState({ profile: makeProfile() });
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchProfile).not.toHaveBeenCalled();
  });
});
