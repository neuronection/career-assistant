import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { EntityEditorModal } from "@/components/profile/EntityEditorModal";
import {
  createExperienceItem,
  fetchExperience,
  updateExperienceItem,
} from "@/api/experience";
import { fetchSkillOntology } from "@/api/skills";
import {
  fetchAchievements,
  fetchCertifications,
  fetchEducation,
  updateCertification,
  updateEducationItem,
} from "@/api/education";
import { fetchUniversities } from "@/api/universities";

vi.mock("@/api/experience", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/experience")>();
  return {
    ...mod,
    fetchExperience: vi.fn(),
    fetchDerivation: vi.fn().mockResolvedValue({
      skills: [],
      years_of_experience: 0,
    }),
    createExperienceItem: vi.fn(),
    updateExperienceItem: vi.fn(),
  };
});

vi.mock("@/api/skills", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...mod,
    fetchMySkills: vi.fn().mockResolvedValue([]),
    fetchSkillOntology: vi.fn(),
    saveMySkills: vi.fn().mockResolvedValue([]),
    setSkillDeriveEnabled: vi.fn(),
    deleteMySkill: vi.fn(),
  };
});

vi.mock("@/api/education", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/education")>();
  return {
    ...mod,
    fetchEducation: vi.fn(),
    fetchCertifications: vi.fn(),
    fetchAchievements: vi.fn(),
    createEducationItem: vi.fn(),
    updateEducationItem: vi.fn(),
    createCertification: vi.fn(),
    updateCertification: vi.fn(),
    createAchievement: vi.fn(),
    updateAchievement: vi.fn(),
  };
});

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    fetchUniversities: vi.fn(),
    fetchUniversity: vi.fn(),
  };
});

const EXP_ITEM = {
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
  skills: [],
  achievements: [],
};

const CERT = {
  id: "c1",
  name: "AWS Solutions Architect",
  issuer: "Amazon Web Services",
  issued: "2025-03-15",
  expires: null,
  credential_id: "AWS-1",
  link: "",
  language_code: null,
  source: "self_report" as const,
  status: "active" as const,
  created_at: "2026-09-07T00:00:00Z",
};

const EDU = {
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
  source: "self_report" as const,
  status: "active" as const,
  university_id: null,
  department_id: null,
  created_at: "2026-09-07T00:00:00Z",
};

function mount(props: Partial<Parameters<typeof EntityEditorModal>[0]>) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(
    <MemoryRouter>
      <EntityEditorModal
        sourceKey="experience"
        itemId="e1"
        onSaved={onSaved}
        onClose={onClose}
        {...props}
      />
    </MemoryRouter>
  );
  return { onSaved, onClose };
}

describe("EntityEditorModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchExperience).mockResolvedValue({
      items: [EXP_ITEM],
      years_of_experience: 0.9,
    });
    vi.mocked(fetchSkillOntology).mockResolvedValue([
      { key: "python", label: "Python" },
    ] as never);
    vi.mocked(fetchCertifications).mockResolvedValue([CERT] as never);
    vi.mocked(fetchEducation).mockResolvedValue([EDU] as never);
    vi.mocked(fetchAchievements).mockResolvedValue([] as never);
    vi.mocked(fetchUniversities).mockResolvedValue([] as never);
    vi.mocked(updateExperienceItem).mockImplementation(
      async (_id, body) => ({ ...EXP_ITEM, ...body }) as never
    );
    vi.mocked(createExperienceItem).mockImplementation(
      async (body) => ({ ...EXP_ITEM, id: "new-1", ...body }) as never
    );
    vi.mocked(updateCertification).mockImplementation(
      async (_id, body) => ({ ...CERT, ...body }) as never
    );
    vi.mocked(updateEducationItem).mockImplementation(
      async (_id, body) => ({ ...EDU, ...body }) as never
    );
  });

  it("edits an experience entry through the workspace editor", async () => {
    const user = userEvent.setup();
    const { onSaved } = mount({ sourceKey: "experience", itemId: "e1" });
    const title = await screen.findByTestId("experience-title");
    expect(title).toHaveValue("DevOps intern");
    await user.clear(title);
    await user.type(title, "Platform intern");
    await user.click(screen.getByTestId("save-experience"));
    await waitFor(() =>
      expect(updateExperienceItem).toHaveBeenCalledWith(
        "e1",
        expect.objectContaining({
          title: "Platform intern",
          source: "self_report",
        })
      )
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("creates a project-kind entry from the projects source", async () => {
    const user = userEvent.setup();
    const { onSaved } = mount({ sourceKey: "projects", itemId: null });
    const title = await screen.findByTestId("experience-title");
    expect(
      screen.getByRole("button", { name: "Project", pressed: true })
    ).toBeInTheDocument();
    await user.type(title, "Portfolio site");
    await user.click(screen.getByTestId("save-experience"));
    await waitFor(() =>
      expect(createExperienceItem).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "project", title: "Portfolio site" })
      )
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("blocks saving an invalid new entry", async () => {
    const user = userEvent.setup();
    const { onSaved } = mount({ sourceKey: "volunteer", itemId: null });
    await screen.findByTestId("experience-title");
    await user.click(screen.getByTestId("save-experience"));
    expect(createExperienceItem).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("edits a certification through the certification editor", async () => {
    const user = userEvent.setup();
    const { onSaved } = mount({ sourceKey: "certifications", itemId: "c1" });
    await screen.findByTestId("certification-editor");
    const name = screen.getByDisplayValue("AWS Solutions Architect");
    await user.clear(name);
    await user.type(name, "AWS SA Associate");
    await user.click(screen.getByTestId("save-certification"));
    await waitFor(() =>
      expect(updateCertification).toHaveBeenCalledWith(
        "c1",
        expect.objectContaining({ name: "AWS SA Associate" })
      )
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("edits an education entry with the catalog picker wired", async () => {
    const user = userEvent.setup();
    const { onSaved } = mount({ sourceKey: "education", itemId: "ed1" });
    await screen.findByTestId("education-editor");
    expect(fetchUniversities).toHaveBeenCalled();
    await user.click(screen.getByTestId("save-education"));
    await waitFor(() =>
      expect(updateEducationItem).toHaveBeenCalledWith(
        "ed1",
        expect.objectContaining({ institution: "TU Sample" })
      )
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it("hosts the skills card and reports its saves", async () => {
    mount({ sourceKey: "skills", itemId: null });
    expect(
      await screen.findByTestId("profile-section-skills")
    ).toBeInTheDocument();
  });

  it("guards closing with unsaved changes behind a discard confirm", async () => {
    const user = userEvent.setup();
    const { onClose } = mount({ sourceKey: "experience", itemId: "e1" });
    const title = await screen.findByTestId("experience-title");
    await user.type(title, "!");
    await user.click(screen.getByTestId("cancel-experience"));
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows a not-found state when the item is gone", async () => {
    mount({ sourceKey: "certifications", itemId: "ghost" });
    expect(await screen.findByTestId("entity-editor-missing")).toHaveTextContent(
      "This entry no longer exists."
    );
  });
});
