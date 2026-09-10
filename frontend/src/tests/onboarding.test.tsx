import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Onboarding } from "@/pages/Onboarding";
import { useProfileStore } from "@/stores/profileStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { fetchProfile, saveProfileSection, analyzeProfile } from "@/api/profile";
import { setOnboardingPath } from "@/api/onboarding";
import {
  createEducationItem,
  fetchEducation,
} from "@/api/education";
import type { Bootstrap, OnboardingPath, Profile } from "@/types";

vi.mock("@/api/profile", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/profile")>();
  return {
    ...mod,
    fetchProfile: vi.fn<typeof mod.fetchProfile>(),
    saveProfileSection: vi.fn<typeof mod.saveProfileSection>(),
    analyzeProfile: vi.fn<typeof mod.analyzeProfile>(),
    fetchInterests: vi.fn().mockResolvedValue([]),
    fetchSkills: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/api/onboarding", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/onboarding")>();
  return {
    ...mod,
    setOnboardingPath: vi.fn<typeof mod.setOnboardingPath>(),
  };
});

vi.mock("@/api/education", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/education")>();
  return {
    ...mod,
    fetchEducation: vi.fn().mockResolvedValue([]),
    createEducationItem: vi.fn(),
    updateEducationItem: vi.fn(),
  };
});

function makeBootstrap(
  overrides: Partial<Bootstrap["features"]> = {},
  path: OnboardingPath | null = "explore"
): Bootstrap {
  const weights = {
    skills: 3,
    location: 3,
    experience: 1,
    education: 5,
    interests: 4,
    values: 2,
  };
  return {
    career_stage: "student",
    stage_source: "derived",
    onboarding_path: path,
    features: {
      universities: true,
      grade_fields: true,
      education_step: true,
      ...overrides,
    },
    suggested_scoring_weights: weights,
    effective_scoring_weights: weights,
    weights_overridden: false,
  };
}

function makeProfile(): Profile {
  return {
    basics: {
      birth_year: 2008,
      education_level: "high_school",
      grade: null,
      career_stage: "student",
      country: "GR",
      city: "Athens",
      email: "",
      phone: "",
      headline: "",
    },
    academics: {
      favorite_subjects: [{ key: "physics", weight: 4 }],
      languages: [{ code: "en", level: "advanced" }],
    },
    interests: [{ tag_key: "technology-software", weight: 3, source: "self" }],
    hobbies: [],
    likes: [{ tag_key: null, label: "building PCs", weight: 3 }],
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
    completeness: { percent: 50, sections: {} },
  };
}

async function advance() {
  fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/onboarding"]}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route
          path="/onboarding/express"
          element={<div data-testid="express-page" />}
        />
        <Route path="/" element={<div data-testid="home" />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Onboarding hero picker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProfileStore.setState({ profile: null, interests: [], skills: [], loading: false });
    vi.mocked(fetchProfile).mockResolvedValue(makeProfile());
    vi.mocked(saveProfileSection).mockImplementation(
      async (section) => ({ ...makeProfile(), ...section }) as Profile
    );
  });

  it("renders the four start-path tiles for a user without a path", () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, null),
      loaded: true,
    });
    renderAt();
    expect(screen.getByTestId("path-picker")).toBeInTheDocument();
    expect(screen.getByTestId("path-hero")).toBeInTheDocument();
    for (const key of ["explore", "target", "cv_import", "browse"]) {
      expect(screen.getByTestId(`path-${key}`)).toBeInTheDocument();
    }
  });

  it("choosing explore stores the path and enters the explore wizard", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, null),
      loaded: true,
    });
    vi.mocked(setOnboardingPath).mockResolvedValue(makeBootstrap({}, "explore"));
    renderAt();
    fireEvent.click(screen.getByTestId("path-explore"));
    await waitFor(() =>
      expect(setOnboardingPath).toHaveBeenCalledWith("explore")
    );
    expect(await screen.findByTestId("onboarding")).toBeInTheDocument();
    expect(screen.getByTestId("stage-question")).toBeInTheDocument();
  });

  it("choosing browse skips setup and lands on the app", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, null),
      loaded: true,
    });
    vi.mocked(setOnboardingPath).mockResolvedValue(makeBootstrap({}, "browse"));
    renderAt();
    fireEvent.click(screen.getByTestId("path-browse"));
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(setOnboardingPath).toHaveBeenCalledWith("browse");
  });

  it("choosing target hands over to the express page", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, null),
      loaded: true,
    });
    vi.mocked(setOnboardingPath).mockResolvedValue(makeBootstrap({}, "target"));
    renderAt();
    fireEvent.click(screen.getByTestId("path-target"));
    expect(await screen.findByTestId("express-page")).toBeInTheDocument();
  });
});

describe("Explore wizard (path-scoped steps)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProfileStore.setState({ profile: null, interests: [], skills: [], loading: false });
    useBootstrapStore.setState({ bootstrap: makeBootstrap(), loaded: true });
    vi.mocked(fetchProfile).mockResolvedValue(makeProfile());
    vi.mocked(saveProfileSection).mockImplementation(
      async (section) => ({ ...makeProfile(), ...section }) as Profile
    );
    vi.mocked(createEducationItem).mockImplementation(
      async (body) =>
        ({
          id: "edu-new",
          created_at: "2026-09-07T00:00:00Z",
          ...body,
        }) as never
    );
  });

  it("pre-chosen path skips the picker and shows Basics with the explore step list", async () => {
    renderAt();
    expect(await screen.findByTestId("onboarding")).toBeInTheDocument();
    expect(screen.queryByTestId("path-picker")).not.toBeInTheDocument();
    expect(await screen.findByTestId("stage-question")).toBeInTheDocument();
    expect(screen.getByText("Basics")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("Interests")).toBeInTheDocument();
    expect(screen.getByText("Study preferences")).toBeInTheDocument();
    expect(screen.getByText("Education")).toBeInTheDocument();
    expect(
      screen.queryByText("Likes & dislikes")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Constraints" })
    ).not.toBeInTheDocument();
  });

  it("Basics saves a structured payload on Save & continue", async () => {
    renderAt();
    fireEvent.change(await screen.findByTestId("basics-headline"), {
      target: { value: "Future engineer" },
    });
    await advance();
    await waitFor(() =>
      expect(saveProfileSection).toHaveBeenCalledWith({
        basics: expect.objectContaining({
          headline: "Future engineer",
          city: "Athens",
          career_stage: "student",
        }),
      })
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-interests")).toBeInTheDocument()
    );
  });

  it("does not advance when a step is invalid (missing language code)", async () => {
    vi.mocked(fetchProfile).mockResolvedValue({
      ...makeProfile(),
      academics: {
        favorite_subjects: [],
        languages: [{ code: "", level: "intermediate" }],
      },
    });
    renderAt();
    await screen.findByTestId("stage-question");
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-interests")).toBeInTheDocument()
    );
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-academics")).toBeInTheDocument()
    );
    await advance();
    expect(
      await screen.findByText("Please fix the highlighted fields before continuing.")
    ).toBeInTheDocument();
  });

  it("walks the whole explore flow and runs the final analysis", async () => {
    vi.mocked(analyzeProfile).mockResolvedValue({
      ai_summary: null,
      completeness: { percent: 100, sections: {} },
    });
    renderAt();
    await screen.findByTestId("stage-question");
    fireEvent.change(await screen.findByTestId("basics-headline"), {
      target: { value: "Flow test" },
    });
    await advance();
    await waitFor(() => expect(saveProfileSection).toHaveBeenCalledTimes(1));
    for (const testId of [
      "profile-section-interests",
      "profile-section-academics",
      "profile-section-education",
    ]) {
      await waitFor(() =>
        expect(screen.getByTestId(testId)).toBeInTheDocument()
      );
      if (testId !== "profile-section-education") await advance();
    }
    expect(
      screen.getByRole("button", { name: /Finish & analyze/ })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Finish & analyze/ }));
    await waitFor(() => expect(analyzeProfile).toHaveBeenCalledTimes(1));
    expect(vi.mocked(saveProfileSection).mock.calls.map((c) => Object.keys(c[0]).sort().join(","))).toEqual([
      "basics",
    ]);
  });

  it("Education mini-step creates the school entry", async () => {
    renderAt();
    await screen.findByTestId("stage-question");
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-interests")).toBeInTheDocument()
    );
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-academics")).toBeInTheDocument()
    );
    await advance();
    expect(
      await screen.findByTestId("profile-section-education")
    ).toBeInTheDocument();
    expect(createEducationItem).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("education-mini-school"), {
      target: { value: "1st Lyceum of Athens" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Finish & analyze/ })
    );
    await waitFor(() =>
      expect(createEducationItem).toHaveBeenCalledWith(
        expect.objectContaining({
          institution: "1st Lyceum of Athens",
          level: "high_school",
          in_progress: true,
          status: "active",
        })
      )
    );
  });

  it("non-student path shows only Basics and Interests", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({
        universities: false,
        grade_fields: false,
        education_step: false,
      }),
      loaded: true,
    });
    renderAt();
    await screen.findByTestId("stage-question");
    await advance();
    expect(
      await screen.findByTestId("profile-section-interests")
    ).toBeInTheDocument();
    expect(screen.queryByText("Study preferences")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Finish & analyze/ })
    ).toBeInTheDocument();
    expect(createEducationItem).not.toHaveBeenCalled();
    expect(fetchEducation).not.toHaveBeenCalled();
  });

  it("cv_import path starts at the Import CV step and advances to Basics", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, "cv_import"),
      loaded: true,
    });
    renderAt();
    expect(await screen.findByTestId("cv-intake-flow")).toBeInTheDocument();
    expect(screen.getByText("Import CV")).toHaveAttribute(
      "aria-current",
      "step"
    );
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("stage-question")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("cv-intake-flow")).not.toBeInTheDocument();
  });

  it("cv_import finish shows the CTA row instead of auto-running the analysis", async () => {
    useBootstrapStore.setState({
      bootstrap: makeBootstrap({}, "cv_import"),
      loaded: true,
    });
    renderAt();
    await screen.findByTestId("cv-intake-flow");
    await advance();
    await waitFor(() =>
      expect(screen.getByTestId("stage-question")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(await screen.findByTestId("cv-import-finish")).toBeInTheDocument();
    expect(analyzeProfile).not.toHaveBeenCalled();
    expect(screen.getByTestId("finish-cv")).toHaveAttribute("href", "/cv");
    expect(screen.getByTestId("finish-generate-cv")).toHaveAttribute(
      "href",
      "/cv?generate=1"
    );
    expect(screen.getByTestId("finish-explore")).toHaveAttribute(
      "href",
      "/postings/search"
    );

    vi.mocked(analyzeProfile).mockResolvedValue({
      ai_summary: null,
      completeness: { percent: 100, sections: {} },
    });
    fireEvent.click(screen.getByTestId("finish-analyze"));
    await waitFor(() => expect(analyzeProfile).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId("home")).toBeInTheDocument();
  });

  it("Different start clears the path and shows the picker again", async () => {
    vi.mocked(setOnboardingPath).mockResolvedValue(makeBootstrap({}, null));
    renderAt();
    await screen.findByTestId("stage-question");
    fireEvent.click(screen.getByTestId("change-start"));
    expect(await screen.findByTestId("path-picker")).toBeInTheDocument();
    expect(setOnboardingPath).toHaveBeenCalledWith(null);
  });
});
