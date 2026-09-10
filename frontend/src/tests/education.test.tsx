import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Education } from "@/pages/Education";
import {
  createAchievement,
  createCertification,
  createEducationItem,
  deleteCertification,
  deleteEducationItem,
  fetchAchievements,
  fetchCertifications,
  fetchEducation,
  updateAchievement,
  updateCertification,
  updateEducationItem,
} from "@/api/education";
import {
  addDepartment,
  createUniversity,
  fetchUniversities,
  fetchUniversity,
} from "@/api/universities";

vi.mock("@/api/education", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/education")>();
  return {
    ...mod,
    fetchEducation: vi.fn(),
    fetchCertifications: vi.fn(),
    fetchAchievements: vi.fn(),
    createEducationItem: vi.fn(),
    updateEducationItem: vi.fn(),
    deleteEducationItem: vi.fn().mockResolvedValue(undefined),
    createCertification: vi.fn(),
    updateCertification: vi.fn(),
    deleteCertification: vi.fn().mockResolvedValue(undefined),
    createAchievement: vi.fn(),
    updateAchievement: vi.fn(),
    deleteAchievement: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    fetchUniversities: vi.fn(),
    fetchUniversity: vi.fn(),
    createUniversity: vi.fn(),
    addDepartment: vi.fn(),
  };
});

const UNI = {
  id: "u1",
  name: "TU Sample",
  country: "NL",
  city: "Utrecht",
  university_type: "public",
  website: "",
  notes: "",
  source: "manual",
  department_count: 1,
};

const DEPT = {
  id: "d1",
  university_id: "u1",
  name: "Computer Science",
  field_key: "computer-science",
  degree: "master",
  duration_years: 2,
  language: "en",
  application_deadline: null,
  description: "",
  admissions: [],
  job_links: [],
};

const EDU1 = {
  id: "ed1",
  institution: "TU Sample",
  org_name: "",
  program: "MSc Computer Science",
  level: "master",
  start: "2025-09-01",
  end: null,
  in_progress: true,
  grade_band: null,
  focus_subjects: ["algorithms"],
  description: "",
  source: "self_report" as const,
  status: "active" as const,
  university_id: "u1",
  department_id: "d1",
  created_at: "2026-09-07T00:00:00Z",
};

const EDU2 = {
  ...EDU1,
  id: "ed2",
  institution: "Sample High",
  program: "",
  level: "high_school",
  start: "2021-09-01",
  end: "2025-06-30",
  in_progress: false,
  focus_subjects: [],
  source: "cv_parse" as const,
  university_id: null,
  department_id: null,
};

const CERT1 = {
  id: "c1",
  name: "AWS Solutions Architect",
  issuer: "Amazon Web Services",
  issued: "2025-03-15",
  expires: null,
  credential_id: "AWS-1",
  link: "",
  source: "self_report" as const,
  status: "active" as const,
  created_at: "2026-09-07T00:00:00Z",
};

const ACH1 = {
  id: "a1",
  kind: "award",
  title: "National Physics Olympiad — 2nd place",
  issuer: "Ministry of Education",
  date: "2024-05-20",
  detail: "",
  link: "",
  source: "self_report" as const,
  status: "active" as const,
  created_at: "2026-09-07T00:00:00Z",
};

describe("Education workspace", () => {
  let extraDepts: Record<string, unknown>[];

  beforeEach(() => {
    vi.clearAllMocks();
    extraDepts = [];
    vi.mocked(fetchEducation).mockResolvedValue([EDU1, EDU2]);
    vi.mocked(fetchCertifications).mockResolvedValue([CERT1]);
    vi.mocked(fetchAchievements).mockResolvedValue([ACH1]);
    vi.mocked(fetchUniversities).mockResolvedValue([UNI] as never);
    vi.mocked(fetchUniversity).mockImplementation(async (id) =>
      ({
        ...UNI,
        id,
        departments: [...(id === "u1" ? [DEPT] : []), ...extraDepts],
      }) as never
    );
    vi.mocked(createEducationItem).mockImplementation(
      async (body) => ({ ...EDU1, id: "new-1", ...body }) as never
    );
    vi.mocked(updateEducationItem).mockImplementation(
      async (id, body) =>
        ({ ...(id === "ed1" ? EDU1 : EDU2), ...body }) as never
    );
    vi.mocked(createCertification).mockImplementation(
      async (body) => ({ ...CERT1, id: "new-2", ...body }) as never
    );
    vi.mocked(updateCertification).mockImplementation(
      async (_id, body) => ({ ...CERT1, ...body }) as never
    );
    vi.mocked(createAchievement).mockImplementation(
      async (body) => ({ ...ACH1, id: "new-3", ...body }) as never
    );
    vi.mocked(updateAchievement).mockImplementation(
      async (_id, body) => ({ ...ACH1, ...body }) as never
    );
    vi.mocked(createUniversity).mockImplementation(
      async (body) =>
        ({
          id: "u-new",
          department_count: 0,
          notes: "",
          source: "manual",
          ...body,
        }) as never
    );
    vi.mocked(addDepartment).mockImplementation(
      async (universityId, body) => {
        const dept = {
          id: "d-new",
          university_id: universityId,
          admissions: [],
          job_links: [],
          ...body,
        };
        extraDepts.push(dept);
        return dept as never;
      }
    );
  });

  async function openItem(id: string) {
    const card = await screen.findByTestId(`education-item-${id}`);
    fireEvent.click(within(card).getByTestId("education-item"));
    return card;
  }

  function renderPage() {
    return render(
      <MemoryRouter>
        <Education />
      </MemoryRouter>
    );
  }

  it("renders the workspace shell with rail, derived chip and empty editor", async () => {    renderPage();
    expect(await screen.findByTestId("education-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("education-back")).toHaveAttribute(
      "href",
      "/profile"
    );
    expect(screen.getByTestId("education-derived")).toHaveTextContent(
      "Master · 1 in progress"
    );
    expect(screen.getByTestId("pane-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("education-item-ed1")).toHaveTextContent(
      "MSc Computer Science"
    );
    expect(screen.getByTestId("education-item-ed2")).toHaveTextContent(
      "From CV"
    );
    expect(screen.getByTestId("education-editor-empty")).toHaveTextContent(
      "Nothing selected"
    );
    expect(screen.getByTestId("education-overview")).toHaveTextContent(
      "2 entries"
    );
  });

  it("opens an item in the editor pane and saves edits in place", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("ed1");
    const editor = screen.getByTestId("education-editor");
    const program = within(editor).getByTestId("education-program");
    expect(program).toHaveValue("MSc Computer Science");
    expect(
      within(editor).getByRole("combobox", { name: "Institution" })
    ).toHaveTextContent("TU Sample");
    await user.clear(program);
    await user.type(program, "MSc Computer Science (AI track)");
    await user.click(within(editor).getByTestId("save-education"));
    await waitFor(() =>
      expect(updateEducationItem).toHaveBeenCalledWith(
        "ed1",
        expect.objectContaining({ program: "MSc Computer Science (AI track)" })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("education-item-ed1")).toHaveTextContent(
        "MSc Computer Science (AI track)"
      )
    );
  });

  it("creates a new entry through the catalog institution picker", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("add-education"));
    const editor = screen.getByTestId("education-editor");
    await user.click(
      within(editor).getByRole("combobox", { name: "Institution" })
    );
    await user.click(await screen.findByRole("option", { name: "TU Sample" }));
    await user.type(
      within(editor).getByTestId("education-program"),
      "BSc Physics"
    );
    await user.click(within(editor).getByTestId("save-education"));
    await waitFor(() =>
      expect(createEducationItem).toHaveBeenCalledWith(
        expect.objectContaining({
          institution: "TU Sample",
          program: "BSc Physics",
          level: "bachelor",
          university_id: "u1",
          department_id: null,
          in_progress: true,
        })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("education-item-new-1")).toBeInTheDocument()
    );
  });

  it("deletes optimistically and restores through undo (POST of the snapshot)", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("education-item-ed1");
    await user.click(screen.getByTestId("delete-education-ed1"));
    await waitFor(() =>
      expect(screen.queryByTestId("education-item-ed1")).not.toBeInTheDocument()
    );
    const notice = screen.getByTestId("undo-education");
    expect(notice).toHaveTextContent("Deleted “MSc Computer Science”");
    await user.click(within(notice).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(createEducationItem).toHaveBeenCalledWith(
        expect.objectContaining({
          institution: "TU Sample",
          level: "master",
          in_progress: true,
        })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("education-item-new-1")).toBeInTheDocument()
    );
  });

  it("guards dirty editor switches with a confirmation", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("ed1");
    const editor = screen.getByTestId("education-editor");
    await user.type(within(editor).getByTestId("education-program"), "!");
    const card2 = await screen.findByTestId("education-item-ed2");
    fireEvent.click(within(card2).getByTestId("education-item"));
    expect(await screen.findByText("Discard changes?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() =>
      expect(
        within(screen.getByTestId("education-editor")).getByRole("combobox", {
          name: "Institution",
        })
      ).toHaveTextContent("Sample High")
    );
    expect(updateEducationItem).not.toHaveBeenCalled();
  });

  it("cancelling a clean edit just closes the editor", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("ed1");
    const editor = screen.getByTestId("education-editor");
    await user.click(within(editor).getByTestId("cancel-education"));
    expect(await screen.findByText("Nothing selected")).toBeInTheDocument();
  });

  it("switches to certifications and manages them on the same skeleton", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("education-item-ed1");
    await user.click(screen.getByTestId("education-entity-certifications"));
    expect(await screen.findByTestId("education-item-c1")).toHaveTextContent(
      "AWS Solutions Architect"
    );
    await openItem("c1");
    const editor = screen.getByTestId("certification-editor");
    await user.type(
      within(editor).getByTestId("certification-issuer"),
      " (updated)"
    );
    await user.click(within(editor).getByTestId("save-certification"));
    await waitFor(() =>
      expect(updateCertification).toHaveBeenCalledWith(
        "c1",
        expect.objectContaining({ issuer: "Amazon Web Services (updated)" })
      )
    );
  });

  it("creating a certification from the certifications tab works", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("education-item-ed1");
    await user.click(screen.getByTestId("education-entity-certifications"));
    await user.click(await screen.findByTestId("add-education"));
    const editor = screen.getByTestId("certification-editor");
    await user.type(within(editor).getByTestId("certification-name"), "CEH");
    await user.click(within(editor).getByTestId("save-certification"));
    await waitFor(() =>
      expect(createCertification).toHaveBeenCalledWith(
        expect.objectContaining({ name: "CEH" })
      )
    );
    expect(deleteCertification).not.toHaveBeenCalled();
    expect(deleteEducationItem).not.toHaveBeenCalled();
  });

  it("switches to achievements and edits one on the same skeleton", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("education-item-ed1");
    await user.click(screen.getByTestId("education-entity-achievements"));
    expect(await screen.findByTestId("education-item-a1")).toHaveTextContent(
      "National Physics Olympiad — 2nd place"
    );
    await openItem("a1");
    const editor = screen.getByTestId("achievement-editor");
    expect(within(editor).getByTestId("achievement-title")).toHaveValue(
      "National Physics Olympiad — 2nd place"
    );
    await user.type(within(editor).getByTestId("achievement-issuer"), " (committee)");
    await user.click(within(editor).getByTestId("save-achievement"));
    await waitFor(() =>
      expect(updateAchievement).toHaveBeenCalledWith(
        "a1",
        expect.objectContaining({
          issuer: "Ministry of Education (committee)",
        })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("education-item-a1")).toHaveTextContent(
        "Ministry of Education (committee)"
      )
    );
  });

  it("creates and deletes an achievement with undo restore", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("education-item-ed1");
    await user.click(screen.getByTestId("education-entity-achievements"));
    await user.click(await screen.findByTestId("add-education"));
    const editor = screen.getByTestId("achievement-editor");
    await user.type(
      within(editor).getByTestId("achievement-title"),
      "Hackathon winner"
    );
    await user.click(within(editor).getByTestId("save-achievement"));
    await waitFor(() =>
      expect(createAchievement).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Hackathon winner", kind: "award" })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("education-item-new-3")).toBeInTheDocument()
    );

    await user.click(screen.getByTestId("delete-education-a1"));
    await waitFor(() =>
      expect(screen.queryByTestId("education-item-a1")).not.toBeInTheDocument()
    );
    const notice = screen.getByTestId("undo-education");
    expect(notice).toHaveTextContent(
      "Deleted “National Physics Olympiad — 2nd place”"
    );
    await user.click(within(notice).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(createAchievement).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "National Physics Olympiad — 2nd place",
          kind: "award",
        })
      )
    );
  });

  it("creates a new university from the typed name and selects it", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("add-education"));
    const editor = screen.getByTestId("education-editor");
    await user.click(
      within(editor).getByRole("combobox", { name: "Institution" })
    );
    await user.type(
      screen.getByRole("combobox", { name: "Search options" }),
      "New Institute"
    );
    await user.click(
      await screen.findByRole("option", { name: 'Add "New Institute"' })
    );
    const nameInput = await screen.findByTestId("university-name");
    expect(nameInput).toHaveValue("New Institute");
    const modal = nameInput.closest("[role='dialog']") as HTMLElement;
    await user.type(within(modal).getByTestId("university-country"), "GR");
    await user.type(within(modal).getByTestId("university-city"), "Athens");
    await user.click(within(modal).getByTestId("save-university"));
    await waitFor(() =>
      expect(createUniversity).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "New Institute",
          country: "GR",
          city: "Athens",
          university_type: "public",
        })
      )
    );
    await waitFor(() =>
      expect(
        within(screen.getByTestId("education-editor")).getByRole("combobox", {
          name: "Institution",
        })
      ).toHaveTextContent("New Institute")
    );
    await user.type(
      within(screen.getByTestId("education-editor")).getByTestId(
        "education-program"
      ),
      "BSc CS"
    );
    await user.click(
      within(screen.getByTestId("education-editor")).getByTestId(
        "save-education"
      )
    );
    await waitFor(() =>
      expect(createEducationItem).toHaveBeenCalledWith(
        expect.objectContaining({
          institution: "New Institute",
          university_id: "u-new",
        })
      )
    );
  });

  it("creates a new department from the typed name with the popup prefilled", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("ed1");
    const editor = screen.getByTestId("education-editor");
    await user.click(
      within(editor).getByRole("combobox", { name: "Department" })
    );
    await user.type(
      screen.getByRole("combobox", { name: "Search options" }),
      "School of AI"
    );
    await user.click(
      await screen.findByRole("option", { name: 'Add "School of AI"' })
    );
    const nameInput = await screen.findByTestId("department-name");
    expect(nameInput).toHaveValue("School of AI");
    await user.click(screen.getByTestId("save-department"));
    await waitFor(() =>
      expect(addDepartment).toHaveBeenCalledWith(
        "u1",
        expect.objectContaining({
          name: "School of AI",
          degree: "bachelor",
          duration_years: 4,
        })
      )
    );
    await waitFor(() =>
      expect(
        within(screen.getByTestId("education-editor")).getByTestId(
          "education-department"
        )
      ).toHaveTextContent("School of AI")
    );
    await user.type(
      within(screen.getByTestId("education-editor")).getByTestId(
        "education-program"
      ),
      " track"
    );
    await user.click(
      within(screen.getByTestId("education-editor")).getByTestId(
        "save-education"
      )
    );
    await waitFor(() =>
      expect(updateEducationItem).toHaveBeenCalledWith(
        "ed1",
        expect.objectContaining({ department_id: "d-new" })
      )
    );
  });
});
