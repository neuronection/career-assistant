import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useRef } from "react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { BasicsCard } from "@/components/profile/sections/BasicsCard";
import { AcademicsCard } from "@/components/profile/sections/AcademicsCard";
import { ConstraintsCard } from "@/components/profile/sections/ConstraintsCard";
import { InterestsCard } from "@/components/profile/sections/InterestsCard";
import { TastesCard } from "@/components/profile/sections/TastesCard";
import { AspirationsCard } from "@/components/profile/sections/AspirationsCard";
import { WorkStyleCard } from "@/components/profile/sections/WorkStyleCard";
import { WeightsCard } from "@/components/profile/sections/WeightsCard";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { ProfileEdit } from "@/pages/ProfileEdit";
import { useProfileStore } from "@/stores/profileStore";
import { fetchProfile } from "@/api/profile";
import { fetchMySkills, saveMySkills, fetchSkillOntology } from "@/api/skills";
import { SkillsCard } from "@/components/profile/sections/SkillsCard";
import type { SectionCardHandle } from "@/components/profile/sections/shared";
import type { Profile } from "@/types";

vi.mock("@/api/profile", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/profile")>();
  return {
    ...mod,
    fetchProfile: vi.fn<typeof mod.fetchProfile>(),
    saveProfileSection: vi.fn<typeof mod.saveProfileSection>(),
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
  };
});

vi.mock("@/api/education", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/education")>();
  return {
    ...mod,
    fetchEducation: vi.fn(),
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

function makeBasics(): Profile["basics"] {
  return {
    birth_year: 2008,
    education_level: "high_school",
    grade: null,
    career_stage: null,
    country: "GR",
    city: "Athens",
    email: "",
    phone: "",
    headline: "",
  };
}

function makeAcademics(): Profile["academics"] {
  return {
    favorite_subjects: [{ key: "mathematics", weight: 4 }],
    languages: [{ code: "en", level: "advanced" }],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ProfileSectionCard", () => {
  it("maps completeness to a dot (filled / hollow / none)", () => {
    render(
      <>
        <ProfileSectionCard name="basics" title="Basics" complete>
          <p>content</p>
        </ProfileSectionCard>
        <ProfileSectionCard name="academics" title="Academics" complete={false}>
          <p>content</p>
        </ProfileSectionCard>
        <ProfileSectionCard name="account" title="Account">
          <p>content</p>
        </ProfileSectionCard>
      </>
    );
    expect(screen.getByTestId("profile-section-basics")).toHaveAttribute(
      "data-complete",
      "true"
    );
    expect(screen.getByTestId("section-dot-basics")).toBeInTheDocument();
    expect(screen.getByTestId("profile-section-academics")).toHaveAttribute(
      "data-complete",
      "false"
    );
    expect(screen.queryByTestId("section-dot-account")).not.toBeInTheDocument();
  });

  it("shows the save-state indicator only when active", () => {
    const { rerender } = render(
      <ProfileSectionCard name="basics" title="Basics" saveState="idle">
        <p>content</p>
      </ProfileSectionCard>
    );
    expect(screen.queryByTestId("section-save-state")).not.toBeInTheDocument();
    rerender(
      <ProfileSectionCard name="basics" title="Basics" saveState="saving">
        <p>content</p>
      </ProfileSectionCard>
    );
    expect(screen.getByTestId("section-save-state")).toHaveTextContent(
      "Saving…"
    );
    rerender(
      <ProfileSectionCard
        name="basics"
        title="Basics"
        saveState="error"
        error="Boom"
      >
        <p>content</p>
      </ProfileSectionCard>
    );
    expect(screen.getByTestId("section-save-state")).toHaveTextContent(
      "Couldn't save"
    );
  });
});

describe("BasicsCard", () => {
  it("renders structured fields instead of a JSON textarea", async () => {
    render(
      <BasicsCard initial={makeBasics()} onSave={vi.fn().mockResolvedValue(undefined)} />
    );
    expect(screen.getByTestId("profile-section-basics")).toBeInTheDocument();
    expect(screen.getByTestId("basics-headline")).toHaveValue("");
    expect(screen.getByTestId("basics-email")).toBeInTheDocument();
    expect(screen.getByTestId("basics-phone")).toBeInTheDocument();
    expect(screen.getByTestId("basics-city")).toHaveValue("Athens");
    expect(screen.getByTestId("basics-country")).toHaveValue("GR");
    expect(screen.getByTestId("basics-education-level")).toHaveValue(
      "high_school"
    );
    expect(screen.getByTestId("stepper-birth-year")).toHaveTextContent("2008");
  });

  it("autosaves a debounced structured payload (no JSON strings)", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<BasicsCard initial={makeBasics()} onSave={onSave} />);
    fireEvent.change(screen.getByTestId("basics-headline"), {
      target: { value: "Aspiring data engineer" },
    });
    expect(screen.getByTestId("section-save-state")).toHaveTextContent(
      "Unsaved changes"
    );
    expect(onSave).not.toHaveBeenCalled();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1), {
      timeout: 1500,
    });
    expect(onSave).toHaveBeenCalledWith({
      basics: expect.objectContaining({
        headline: "Aspiring data engineer",
        city: "Athens",
        birth_year: 2008,
      }),
    });
    const payload = vi.mocked(onSave).mock.calls[0][0].basics!;
    expect(typeof payload).toBe("object");
    await waitFor(() =>
      expect(screen.getByTestId("section-save-state")).toHaveTextContent(
        "Saved ✓"
      )
    );
  });

  it("does not autosave while the email is invalid, and shows the error", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<BasicsCard initial={makeBasics()} onSave={onSave} />);
    fireEvent.change(screen.getByTestId("basics-email"), {
      target: { value: "not-an-email" },
    });
    await new Promise((r) => setTimeout(r, 700));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("basics-email"), {
      target: { value: "me@example.com" },
    });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1), {
      timeout: 1500,
    });
    expect(onSave).toHaveBeenCalledWith({
      basics: expect.objectContaining({ email: "me@example.com" }),
    });
  });

  it("adds typed profile links and autosaves them once valid", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<BasicsCard initial={makeBasics()} onSave={onSave} />);
    fireEvent.click(screen.getByTestId("add-link"));
    fireEvent.change(screen.getByTestId("link-kind-0"), {
      target: { value: "github" },
    });
    fireEvent.change(screen.getByTestId("link-url-0"), {
      target: { value: "github.com/alex" },
    });
    expect(screen.getByTestId("basics-link-0")).toHaveTextContent(
      "Use a full http(s):// URL"
    );
    fireEvent.change(screen.getByTestId("link-url-0"), {
      target: { value: "https://github.com/alex" },
    });
    fireEvent.change(screen.getByTestId("link-label-0"), {
      target: { value: "Code" },
    });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1), {
      timeout: 1500,
    });
    expect(onSave).toHaveBeenCalledWith({
      basics: expect.objectContaining({
        links: [
          { kind: "github", url: "https://github.com/alex", label: "Code" },
        ],
      }),
    });
  });

  it("birth year stepper clamps and can be unset", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<BasicsCard initial={makeBasics()} onSave={onSave} />);
    const increase = screen.getByRole("button", {
      name: "Birth year increase",
    });
    fireEvent.click(increase);
    expect(screen.getByTestId("stepper-birth-year")).toHaveTextContent("2009");
    fireEvent.click(screen.getByTestId("stepper-birth-year-clear"));
    expect(screen.getByTestId("stepper-birth-year-add")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("stepper-birth-year-add"));
    expect(screen.getByTestId("stepper-birth-year")).toHaveTextContent("2006");
    await waitFor(() => expect(onSave).toHaveBeenCalled(), { timeout: 1500 });
  });

  it("manual mode never autosaves; save() flushes the draft", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    let handle: { save: () => Promise<boolean | void> } | null = null;
    function Harness() {
      const ref = useRef<SectionCardHandle>(null);
      handle = {
        save: () => (ref.current ? ref.current.save() : Promise.resolve()),
      };
      return <BasicsCard ref={ref} initial={makeBasics()} onSave={onSave} mode="manual" />;
    }
    render(<Harness />);
    fireEvent.change(screen.getByTestId("basics-headline"), {
      target: { value: "Manual flush" },
    });
    await new Promise((r) => setTimeout(r, 700));
    expect(onSave).not.toHaveBeenCalled();
    await handle!.save();
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({
      basics: expect.objectContaining({ headline: "Manual flush" }),
    });
  });
});

describe("AcademicsCard", () => {
  it("saves subjects and languages as structured rows", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AcademicsCard initial={makeAcademics()} onSave={onSave} />);
    expect(screen.queryByTestId("academics-gpa-band")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-language"));
    fireEvent.change(screen.getByTestId("language-code-1"), {
      target: { value: "fr" },
    });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1), {
      timeout: 1500,
    });
    expect(onSave).toHaveBeenCalledWith({
      academics: expect.objectContaining({
        favorite_subjects: [{ key: "mathematics", weight: 4 }],
        languages: expect.arrayContaining([
          { code: "en", level: "advanced" },
          { code: "fr", level: "intermediate" },
        ]),
      }),
    });
  });

  it("adds a subject via the combobox and tunes its weight with the stepper", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AcademicsCard
        initial={{
          favorite_subjects: [],
          languages: [],
        }}
        onSave={onSave}
      />
    );
    fireEvent.click(
      screen.getByRole("combobox", { name: "Favorite subjects" })
    );
    fireEvent.click(await screen.findByRole("option", { name: "physics" }));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          academics: expect.objectContaining({
            favorite_subjects: [{ key: "physics", weight: 3 }],
          }),
        }),
      { timeout: 1500 }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "physics weight increase" })
    );
    await waitFor(
      () =>
        expect(onSave).toHaveBeenLastCalledWith({
          academics: expect.objectContaining({
            favorite_subjects: [{ key: "physics", weight: 4 }],
          }),
        }),
      { timeout: 1500 }
    );
  });

  it("language rows validate: an empty code blocks the save", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AcademicsCard initial={makeAcademics()} onSave={onSave} />);
    fireEvent.click(screen.getByTestId("add-language"));
    expect(await screen.findByText("Pick a language")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 700));
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("language-code-1"), {
      target: { value: "el" },
    });
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1), {
      timeout: 1500,
    });
    expect(onSave).toHaveBeenCalledWith({
      academics: expect.objectContaining({
        languages: [
          { code: "en", level: "advanced" },
          { code: "el", level: "intermediate" },
        ],
      }),
    });
  });

  it("removes a language row and saves the result", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AcademicsCard initial={makeAcademics()} onSave={onSave} />);
    fireEvent.click(screen.getByTestId("language-remove-0"));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          academics: expect.objectContaining({ languages: [] }),
        }),
      { timeout: 1500 }
    );
  });
});

describe("ConstraintsCard", () => {
  it("toggles condition chips and saves a structured payload", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ConstraintsCard
        initial={{
          physical_conditions: [],
          max_education_years: null,
          willing_to_relocate: true,
          hours_available_per_week: null,
          salary_min: null,
          salary_negotiable: false,
          travel_days_per_month: null,
          shift_tolerance: null,
          commute_radius_km: null,
        }}
        onSave={onSave}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          constraints: expect.objectContaining({
            physical_conditions: ["none"],
          }),
        }),
      { timeout: 1500 }
    );
  });

  it("uses steppers for optional numbers (education years, hours)", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ConstraintsCard
        initial={{
          physical_conditions: [],
          max_education_years: null,
          willing_to_relocate: true,
          hours_available_per_week: null,
          salary_min: null,
          salary_negotiable: false,
          travel_days_per_month: null,
          shift_tolerance: null,
          commute_radius_km: null,
        }}
        onSave={onSave}
      />
    );
    fireEvent.click(screen.getByTestId("stepper-max-education-years-add"));
    fireEvent.click(screen.getByTestId("stepper-hours-per-week-add"));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          constraints: expect.objectContaining({
            max_education_years: 4,
            hours_available_per_week: 20,
          }),
        }),
      { timeout: 1500 }
    );
  });

  it("captures lifestyle constraints and saves them", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <ConstraintsCard
        initial={{
          physical_conditions: [],
          max_education_years: null,
          willing_to_relocate: true,
          hours_available_per_week: null,
          salary_min: null,
          salary_negotiable: false,
          travel_days_per_month: null,
          shift_tolerance: null,
          commute_radius_km: null,
        }}
        onSave={onSave}
      />
    );
    fireEvent.click(
      screen.getByTestId("stepper-salary-minimum-(monthly-take-home)-add")
    );
    fireEvent.change(screen.getByTestId("shift-tolerance-select"), {
      target: { value: "occasional" },
    });
    fireEvent.click(screen.getByTestId("toggle-this-minimum-is-negotiable-for-the-right-role"));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          constraints: expect.objectContaining({
            salary_min: 800,
            salary_negotiable: true,
            shift_tolerance: "occasional",
          }),
        }),
      { timeout: 1500 }
    );
  });
});

const TAXONOMY = [
  { key: "technology-software", label: "Software", category: "Technology", description: "" },
  { key: "technology-hardware", label: "Hardware", category: "Technology", description: "" },
  { key: "nature-animals", label: "Animals", category: "Nature", description: "" },
];

describe("InterestsCard", () => {
  beforeEach(() => {
    useProfileStore.setState({ interests: TAXONOMY, skills: [], profile: null, loading: false });
  });

  it("groups taxonomy chips by category and toggles with implied weight", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <InterestsCard
        initial={[{ tag_key: "technology-software", weight: 3, source: "self" }]}
        onSave={onSave}
      />
    );
    expect(screen.getByTestId("interest-group-Technology")).toBeInTheDocument();
    expect(screen.getByTestId("interests-count")).toHaveTextContent("1 selected");
    fireEvent.click(screen.getByTestId("interest-chip-nature-animals"));
    expect(screen.getByTestId("interests-count")).toHaveTextContent("2 selected");
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          interests: [
            { tag_key: "technology-software", weight: 3, source: "self" },
            { tag_key: "nature-animals", weight: 3, source: "self" },
          ],
        }),
      { timeout: 1500 }
    );
    fireEvent.click(screen.getByTestId("interest-chip-nature-animals"));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenLastCalledWith({
          interests: [{ tag_key: "technology-software", weight: 3, source: "self" }],
        }),
      { timeout: 1500 }
    );
  });

  it("filters chips through the search box", () => {
    render(<InterestsCard initial={[]} onSave={vi.fn().mockResolvedValue(undefined)} />);
    fireEvent.change(screen.getByTestId("interests-search"), {
      target: { value: "animals" },
    });
    expect(screen.getByTestId("interest-chip-nature-animals")).toBeInTheDocument();
    expect(screen.queryByTestId("interest-chip-technology-software")).not.toBeInTheDocument();
    expect(screen.getByTestId("interests-count")).toHaveTextContent("0 selected");
  });
});

describe("TastesCard", () => {
  beforeEach(() => {
    useProfileStore.setState({ interests: TAXONOMY, skills: [], profile: null, loading: false });
  });

  it("adds a like and links it to the taxonomy when it matches", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <TastesCard initial={{ likes: [], dislikes: [], hobbies: [] }} onSave={onSave} />
    );
    fireEvent.change(screen.getByLabelText("New like"), {
      target: { value: "Hardware" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          likes: [{ tag_key: "technology-hardware", label: "Hardware", weight: 3 }],
          dislikes: [],
          hobbies: [],
        }),
      { timeout: 1500 }
    );
  });
});

describe("AspirationsCard", () => {
  it("adds, reorders and removes rows", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AspirationsCard
        initial={[
          { label: "First", tag_keys: [], notes: "" },
          { label: "Second", tag_keys: [], notes: "" },
        ]}
        onSave={onSave}
      />
    );
    fireEvent.click(screen.getByTestId("add-aspiration"));
    fireEvent.change(screen.getByTestId("aspiration-label-2"), {
      target: { value: "Third" },
    });
    fireEvent.click(screen.getByTestId("aspiration-up-2"));
    expect(screen.getByTestId("aspiration-label-1")).toHaveValue("Third");
    fireEvent.click(screen.getByTestId("aspiration-remove-0"));
    expect(screen.getByTestId("aspiration-label-0")).toHaveValue("Third");
    expect(screen.getByTestId("aspiration-label-1")).toHaveValue("Second");
    await waitFor(
      () =>
        expect(onSave).toHaveBeenLastCalledWith({
          aspirations: [
            { label: "Third", tag_keys: [], notes: "" },
            { label: "Second", tag_keys: [], notes: "" },
          ],
        }),
      { timeout: 1500 }
    );
  });
});

describe("WorkStyleCard", () => {
  function makeWork(): Profile["work_preferences"] {
    return {
      teamwork: 3,
      environment: 3,
      structure: 3,
      pace: 3,
      leadership: 3,
      remote_ok: true,
      focus_areas: [],
      salary_priority: 3,
      stability_priority: 3,
      physical_activity: "light",
      creativity_priority: 3,
    };
  }

  it("changes sliders, activity pills and focus areas with structured saves", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<WorkStyleCard initial={makeWork()} onSave={onSave} />);
    fireEvent.change(screen.getByRole("slider", { name: "Teamwork" }), {
      target: { value: "4" },
    });
    await waitFor(
      () =>
        expect(onSave).toHaveBeenCalledWith({
          work_preferences: expect.objectContaining({ teamwork: 4 }),
        }),
      { timeout: 1500 }
    );
    fireEvent.click(screen.getByRole("button", { name: "Active" }));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenLastCalledWith({
          work_preferences: expect.objectContaining({ physical_activity: "active" }),
        }),
      { timeout: 1500 }
    );
    fireEvent.click(screen.getByTestId("focus-area-ideas"));
    await waitFor(
      () =>
        expect(onSave).toHaveBeenLastCalledWith({
          work_preferences: expect.objectContaining({ focus_areas: ["ideas"] }),
        }),
      { timeout: 1500 }
    );
    expect(screen.getByTestId("toggle-open-to-remote-work")).toBeChecked();
  });
});

describe("WeightsCard", () => {
  it("wraps the weights editor and hides itself without weights", () => {
    const { rerender } = render(
      <WeightsCard
        initial={{ skills: 3, location: 3, experience: 3, education: 3, interests: 3, values: 3 }}
      />
    );
    expect(screen.getByTestId("profile-section-weights")).toBeInTheDocument();
    expect(screen.getByTestId("weights-editor")).toBeInTheDocument();
    rerender(<WeightsCard initial={undefined} />);
    expect(screen.queryByTestId("profile-section-weights")).not.toBeInTheDocument();
  });
});

describe("SkillsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMySkills).mockResolvedValue([]);
    vi.mocked(fetchSkillOntology).mockResolvedValue([
      {
        key: "python",
        label: "Python",
        category: "programming",
        description: "",
        parent_id: null,
        level_anchors: [],
        status: "active",
      },
    ] as never);
    vi.mocked(saveMySkills).mockImplementation(async (skills) =>
      skills.map((s, i) => ({
        skill_id: `id-${i}`,
        key: s.skill_key,
        label: s.skill_key,
        category: "programming",
        level: s.level,
        source: "self_report" as const,
        confidence: 1,
        level_anchors: [],
      }))
    );
  });

  it("picking a catalog skill adds it immediately at the default level", async () => {
    const user = userEvent.setup();
    render(<SkillsCard />);
    await user.click(await screen.findByRole("combobox", { name: "Add a skill" }));
    await user.click(await screen.findByRole("option", { name: "Python (programming)" }));
    await waitFor(() =>
      expect(saveMySkills).toHaveBeenCalledWith([
        { skill_key: "python", level: 5 },
      ])
    );
    expect(await screen.findByTestId("skill-slider-python")).toBeInTheDocument();
  });

  it("typing a new skill name adds it as a slugged catalog suggestion", async () => {
    const user = userEvent.setup();
    render(<SkillsCard />);
    await user.click(await screen.findByRole("combobox", { name: "Add a skill" }));
    await user.type(
      await screen.findByRole("combobox", { name: "Search options" }),
      "Rust Embedded"
    );
    await user.click(
      await screen.findByRole("option", { name: 'Add skill "Rust Embedded"' })
    );
    await waitFor(() =>
      expect(saveMySkills).toHaveBeenCalledWith([
        { skill_key: "rust-embedded", level: 5 },
      ])
    );
  });

  it("re-picking an existing skill does not reset its level", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchMySkills).mockResolvedValue([
      {
        skill_id: "s1",
        key: "python",
        label: "Python",
        category: "programming",
        level: 8,
        source: "self_report",
        confidence: 1,
        level_anchors: [],
      },
    ]);
    render(<SkillsCard />);
    await user.click(await screen.findByRole("combobox", { name: "Add a skill" }));
    await user.click(await screen.findByRole("option", { name: "Python (programming)" }));
    await new Promise((r) => setTimeout(r, 50));
    expect(saveMySkills).not.toHaveBeenCalled();
  });
});

describe("ProfileEdit (settings-shell restructure)", () => {
  function makeProfile(): Profile {
    return {
      basics: {
        birth_year: 2008,
        education_level: "high_school",
        grade: null,
        country: "GR",
        city: "Athens",
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

  beforeEach(async () => {
    vi.clearAllMocks();
    useProfileStore.setState({ profile: null, interests: TAXONOMY, skills: [], loading: false });
    vi.mocked(fetchProfile).mockResolvedValue(makeProfile());
    vi.mocked((await import("@/api/experience")).fetchExperience).mockResolvedValue({
      items: [
        {
          id: "e1",
          kind: "internship",
          title: "DevOps intern",
          org_name: "Acme",
          org_id: null,
          start: "2025-01-01",
          end: null,
          open_ended: true,
          hours_per_week: 40,
          onsite_policy: null,
          description: "",
          links: [],
          source: "self_report",
          status: "active",
          created_at: "2026-09-02T00:00:00Z",
          skills: [],
          achievements: [],
        },
        {
          id: "e0",
          kind: "project",
          title: "Capstone",
          org_name: "",
          org_id: null,
          start: "2024-01-01",
          end: "2024-06-30",
          open_ended: false,
          hours_per_week: null,
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
      years_of_experience: 1.5,
    });
    vi.mocked((await import("@/api/education")).fetchEducation).mockResolvedValue([
      {
        id: "ed1",
        institution: "TU Sample",
        org_name: "",
        program: "MSc Computer Science",
        level: "master",
        start: "2025-09-01",
        end: null,
        in_progress: true,
        grade_band: null,
        focus_subjects: [],
        description: "",
        source: "self_report",
        status: "active",
        university_id: null,
        department_id: null,
        created_at: "2026-09-07T00:00:00Z",
      },
      {
        id: "ed0",
        institution: "Sample High",
        org_name: "",
        program: "",
        level: "high_school",
        start: "2021-09-01",
        end: "2025-06-30",
        in_progress: false,
        grade_band: null,
        focus_subjects: [],
        description: "",
        source: "self_report",
        status: "active",
        university_id: null,
        department_id: null,
        created_at: "2026-09-06T00:00:00Z",
      },
    ]);
  });

  afterEach(() => {
    window.history.replaceState(null, "", window.location.pathname);
  });

  it("renders the section rail with completeness dots and hash-syncs deep links", async () => {
    window.history.replaceState(null, "", "#interests");
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    const rail = await screen.findByTestId("section-rail");
    expect(rail).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-interests")).toBeInTheDocument()
    );
    expect(screen.getByTestId("rail-dot-basics")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("rail-dot-academics")).toHaveAttribute("data-complete", "false");
    fireEvent.click(screen.getByRole("button", { name: "Constraints" }));
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-constraints")).toBeInTheDocument()
    );
    expect(window.location.hash).toBe("#constraints");
  });

  it("marks required sections on the rail and hints at the required scope", async () => {
    const profile = makeProfile();
    profile.completeness = {
      ...profile.completeness,
      percent: 37,
      required_percent: 67,
      required: {
        basics: true,
        academics: true,
        interests: true,
        hobbies: false,
        likes: false,
        aspirations: false,
        work_preferences: false,
        constraints: false,
      },
    };
    profile.completeness.sections.academics = false;
    vi.mocked(fetchProfile).mockResolvedValue(profile);
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-overview")).toBeInTheDocument()
    );
    expect(screen.getByTestId("rail-dot-basics")).toHaveAttribute(
      "data-required",
      "true"
    );
    expect(screen.getByTestId("rail-dot-academics")).toHaveAttribute(
      "data-required",
      "true"
    );
    expect(screen.getByTestId("rail-dot-constraints")).toHaveAttribute(
      "data-required",
      "false"
    );
    expect(screen.getByTestId("required-hint")).toHaveTextContent(
      "67% of the sections your start path needs are filled."
    );
    expect(screen.getByTestId("import-cv-entry")).toBeInTheDocument();
  });

  it("shows the overview by default with stage switch and completeness bar", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-section-overview")).toBeInTheDocument()
    );
    expect(screen.getByTestId("stage-switch")).toBeInTheDocument();
    expect(screen.getByText("Completeness: 62%")).toBeInTheDocument();
  });

  it("summarizes experience (years + latest entries) with a link to the workspace", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByRole("button", { name: "Experience" }));
    expect(await screen.findByTestId("experience-years")).toHaveTextContent("1.5y");
    expect(screen.getByTestId("experience-link")).toHaveAttribute(
      "href",
      "/profile/experience"
    );
    expect(screen.getByText(/DevOps intern/)).toBeInTheDocument();
    const summaries = screen.getAllByTestId(/^experience-summary-/);
    expect(summaries[0]).toHaveTextContent("DevOps intern");
    expect(summaries[1]).toHaveTextContent("Capstone");
  });

  it("summarizes education (derived level + entries) with a link to the workspace", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByRole("button", { name: "Education" }));
    const highest = await screen.findByTestId("education-highest");
    expect(highest).toHaveTextContent("2 entries");
    expect(highest).toHaveTextContent("highest: Master");
    expect(highest).toHaveTextContent("1 in progress");
    expect(screen.getByTestId("education-summary-ed1")).toHaveTextContent(
      "MSc Computer Science"
    );
    expect(screen.getByTestId("education-link")).toHaveAttribute(
      "href",
      "/profile/education"
    );
  });

  it("keeps the account & data danger zone as the last section", async () => {
    render(
      <MemoryRouter>
        <ProfileEdit />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByRole("button", { name: "Account & data" }));
    expect(await screen.findByTestId("data-privacy")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export my data (zip)" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete account…" })
    ).toBeInTheDocument();
  });
});
