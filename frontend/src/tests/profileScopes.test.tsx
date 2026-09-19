import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProfileEdit } from "@/pages/ProfileEdit";
import { useProfileStore } from "@/stores/profileStore";
import { fetchProfile } from "@/api/profile";
import { fetchMySkills } from "@/api/skills";
import type { Profile } from "@/types";

vi.mock("@/api/profile", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/profile")>();
  return {
    ...mod,
    fetchProfile: vi.fn<typeof mod.fetchProfile>(),
    saveProfileSection: vi.fn<typeof mod.saveProfileSection>(),
  };
});

vi.mock("@/api/cvIntake", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvIntake")>();
  return {
    ...mod,
    listCvDraftHistory: vi.fn<typeof mod.listCvDraftHistory>(),
  };
});

vi.mock("@/api/auth", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...mod,
    revokeSessions: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/skills", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...mod,
    fetchMySkills: vi.fn<typeof mod.fetchMySkills>(),
    fetchSkillOntology: vi.fn<typeof mod.fetchSkillOntology>(),
    saveMySkills: vi.fn<typeof mod.saveMySkills>(),
    setSkillDeriveEnabled: vi.fn<typeof mod.setSkillDeriveEnabled>(),
    deleteMySkill: vi.fn<typeof mod.deleteMySkill>(),
  };
});

vi.mock("@/api/backgroundJobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/backgroundJobs")>();
  return {
    ...mod,
    requestExport: vi.fn().mockResolvedValue("job-1"),
    downloadExport: vi.fn().mockResolvedValue(undefined),
    deleteAccount: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/experience", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/experience")>();
  return {
    ...mod,
    fetchExperience: vi.fn(),
    fetchDerivation: vi.fn().mockResolvedValue({ skills: [], years_of_experience: 0 }),
  };
});

vi.mock("@/api/education", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/education")>();
  return {
    ...mod,
    fetchEducation: vi.fn(),
  };
});

vi.mock("@/api/assessments", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/assessments")>();
  return {
    ...mod,
    fetchAssessments: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/api/mePhoto", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/mePhoto")>();
  return {
    ...mod,
    fetchPhotoGallery: vi.fn().mockResolvedValue([]),
    fetchPhotoState: vi.fn().mockResolvedValue({ photo_document_id: null }),
    fetchPhotoBlobUrl: vi.fn().mockResolvedValue("blob:x"),
    uploadPhoto: vi.fn().mockResolvedValue(undefined),
    deleteGalleryPhoto: vi.fn().mockResolvedValue(undefined),
    setDefaultPhoto: vi.fn().mockResolvedValue(undefined),
  };
});

function makeProfile(): Profile {
  return {
    basics: {
      birth_year: 2008,
      education_level: "high_school",
      grade: null,
      country: "GR",
      city: "Athens",
      full_name: "Test User",
      email: "",
      phone: "",
      headline: "",
    },
    academics: { favorite_subjects: [], languages: [] },
    interests: [{ tag_key: "technology-software", weight: 3, source: "self" }],
    hobbies: [],
    likes: [],
    dislikes: [],
    aspirations: [{ label: "Build robots", tag_keys: [], notes: "" }],
    work_preferences: {
      teamwork: 3,
      environment: 3,
      structure: 3,
      pace: 3,
      leadership: 3,
      remote_ok: true,
      focus_areas: ["ideas"],
      salary_priority: 3,
      stability_priority: 3,
      physical_activity: "light",
      creativity_priority: 3,
    },
    preferences: {
      scoring_weights: { skills: 3, location: 3, experience: 3, education: 3, interests: 3, values: 3 },
    },
    constraints: {
      physical_conditions: [],
      max_education_years: null,
      willing_to_relocate: true,
      hours_available_per_week: null,
      salary_min: null,
      salary_negotiable: false,
      travel_days_per_month: null,
      shift_tolerance: null,
      commute_radius_km: null,
    },
    ai_summary: null,
    completeness: {
      percent: 62,
      sections: {
        basics: true,
        academics: false,
        interests: true,
        hobbies: false,
        likes: false,
        aspirations: true,
        work_preferences: true,
        constraints: false,
      },
    },
  };
}

async function mockApis(profile: Profile) {
  vi.mocked(fetchProfile).mockResolvedValue(profile);
  vi.mocked((await import("@/api/experience")).fetchExperience).mockResolvedValue({
    items: [
      {
        id: "e1",
        kind: "job",
        title: "Barista",
        org_name: "Cafe",
        org_id: null,
        start: "2025-01-01",
        end: null,
        open_ended: true,
        hours_per_week: 12,
        onsite_policy: null,
        description: "",
        links: [],
        source: "self_report",
        status: "active",
        created_at: "2026-09-01T00:00:00Z",
        skills: [],
        achievements: [],
      },
    ],
    years_of_experience: 0.5,
  });
  vi.mocked((await import("@/api/education")).fetchEducation).mockResolvedValue([
    {
      id: "ed1",
      institution: "Sample High",
      org_name: "",
      program: "",
      level: "high_school",
      start: "2021-09-01",
      end: null,
      in_progress: true,
      grade_band: null,
      focus_subjects: [],
      description: "",
      source: "self_report",
      status: "active",
      university_id: null,
      department_id: null,
      created_at: "2026-09-01T00:00:00Z",
    },
  ]);
  vi.mocked(fetchMySkills).mockResolvedValue([]);
}

describe("profile goal scopes", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    useProfileStore.setState({
      profile: null,
      interests: [
        { key: "technology-software", label: "Software", category: "technology", description: "" },
      ],
      skills: [],
      loading: false,
    });
    vi.mocked(
      (await import("@/api/cvIntake")).listCvDraftHistory
    ).mockResolvedValue([]);
    await mockApis(makeProfile());
  });

  afterEach(() => {
    window.history.replaceState(null, "", window.location.pathname);
  });

  it("shows cumulative scope dots on rail items and chips on section cards", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    const rail = await screen.findByTestId("section-rail");
    expect(rail).toBeInTheDocument();

    const skillsDots = await screen.findByTestId("scope-dots-skills");
    expect(skillsDots.querySelectorAll("span").length).toBe(3);
    expect(screen.getByTestId("scope-dots-basics")).toBeInTheDocument();
    expect(screen.queryByTestId("scope-dots-account")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Basics" }));
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-basics")).toBeInTheDocument()
    );
    expect(screen.getByTestId("scope-chips-basics")).toBeInTheDocument();
    expect(screen.getByTestId("scope-chip-cv")).toHaveTextContent("CV");
    expect(screen.getByTestId("scope-chip-match")).toHaveTextContent("Job matching");
    expect(screen.queryByTestId("scope-chip-guide")).not.toBeInTheDocument();
  });

  it("filters the rail to a goal via the segmented tabs and syncs ?focus=", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await screen.findByTestId("section-rail");

    const allTab = screen.getByRole("tab", { name: "Everything", selected: true });
    fireEvent.click(screen.getByRole("tab", { name: "CV" }));

    expect(
      screen.getByRole("tab", { name: "CV", selected: true })
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?focus=cv");
    const strip = screen.getByTestId("scope-focus-strip");
    expect(strip).toHaveTextContent(/sections hidden/);
    expect(screen.getByRole("button", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Languages" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Account & data" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Study preferences" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fit weights" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assessment" })).not.toBeInTheDocument();

    allTab.focus();
    fireEvent.keyDown(allTab, { key: "ArrowRight" });
    expect(window.location.search).toBe("?focus=cv");
    fireEvent.click(screen.getByTestId("scope-focus-show-all"));
    expect(window.location.search).toBe("");
    expect(
      screen.getByRole("tab", { name: "Everything", selected: true })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fit weights" })).toBeInTheDocument();
  });

  it("returns to the overview when the active tab falls out of the focused scope", async () => {
    window.history.replaceState(null, "", window.location.pathname + "#weights");
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-weights")).toBeInTheDocument()
    );

    fireEvent.click(screen.getByRole("tab", { name: "CV" }));
    await waitFor(() =>
      expect(screen.getByTestId("scope-readiness")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("profile-section-weights")).not.toBeInTheDocument();
  });

  it("renders goal readiness with per-scope progress and a continue jump", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    const cvCount = await screen.findByTestId("scope-readiness-cv-count");
    expect(cvCount).toHaveTextContent("5 of 8 sections filled");
    expect(screen.getByTestId("scope-readiness-match-count")).toHaveTextContent(
      "6 of 10 sections filled"
    );

    fireEvent.click(screen.getByTestId("scope-readiness-cv-continue"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-photo")).toBeInTheDocument()
    );
    expect(window.location.hash).toBe("#photo");
  });
});
