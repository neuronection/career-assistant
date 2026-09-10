import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Experience } from "@/pages/Experience";
import {
  fetchExperience,
  fetchDerivation,
  applyDerivation,
  createExperienceItem,
  updateExperienceItem,
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

const ITEM2 = {
  ...ITEM,
  id: "e2",
  kind: "project" as const,
  title: "Capstone",
  org_name: "TU",
  start: "2024-01-01",
  end: "2024-06-30",
  open_ended: false,
  hours_per_week: null,
  skills: [],
};

const DERIVED = {
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
};

describe("Experience workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchExperience).mockResolvedValue({
      items: [ITEM, ITEM2],
      years_of_experience: 0.9,
    });
    vi.mocked(fetchDerivation).mockResolvedValue(DERIVED);
    vi.mocked(fetchSkillOntology).mockResolvedValue([
      { key: "python", label: "Python" },
      { key: "sql", label: "SQL" },
    ] as never);
    vi.mocked(applyDerivation).mockResolvedValue({
      applied: 1,
      conflicts: [],
      derived: [],
    });
    vi.mocked(createExperienceItem).mockImplementation(
      async (body) =>
        ({
          ...ITEM,
          id: "new-1",
          ...body,
          start: body.start ?? "",
          skills: [],
          achievements: [],
        }) as never
    );
    vi.mocked(updateExperienceItem).mockImplementation(
      async (id, body) => ({ ...(id === "e1" ? ITEM : ITEM2), ...body }) as never
    );
  });

  async function openItem(id: string) {
    const card = await screen.findByTestId(`experience-item-${id}`);
    fireEvent.click(within(card).getByTestId("experience-item"));
    return card;
  }

  function renderPage() {
    return render(
      <MemoryRouter>
        <Experience />
      </MemoryRouter>
    );
  }

  it("renders the full-bleed workspace shell with rail and empty editor", async () => {
    renderPage();
    expect(await screen.findByTestId("experience-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("years-of-experience")).toHaveTextContent("0.9y");
    expect(screen.getByTestId("experience-back")).toHaveAttribute(
      "href",
      "/profile"
    );
    expect(screen.getByTestId("pane-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("experience-item-e1")).toHaveTextContent(
      "DevOps intern"
    );
    expect(screen.getByTestId("experience-item-e1")).toHaveTextContent("40h/wk");
    const editor = screen.getByTestId("experience-editor");
    expect(within(editor).getByText("Nothing selected")).toBeInTheDocument();
    const panel = screen.getByTestId("derivation-panel");
    expect(panel).toHaveTextContent("Python");
    expect(panel).toHaveTextContent("level 3.2");
  });

  it("opens an item in the editor pane and saves edits in place", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("e1");
    const editor = screen.getByTestId("experience-editor");
    const title = within(editor).getByTestId("experience-title");
    expect(title).toHaveValue("DevOps intern");
    await user.clear(title);
    await user.type(title, "DevOps intern (extended)");
    await user.click(within(editor).getByTestId("save-experience"));
    await waitFor(() =>
      expect(updateExperienceItem).toHaveBeenCalledWith(
        "e1",
        expect.objectContaining({ title: "DevOps intern (extended)" })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("experience-item-e1")).toHaveTextContent(
        "DevOps intern (extended)"
      )
    );
  });

  it("creates a new item through the editor with dates and skills", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("add-experience"));
    const editor = screen.getByTestId("experience-editor");
    await user.type(within(editor).getByTestId("experience-title"), "Backend job");
    await user.click(within(editor).getByRole("button", { name: "Start date" }));
    const now = new Date();
    const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-15`;
    await user.click(document.querySelector(`[data-day="${iso}"]`)!);
    await user.click(within(editor).getByTestId("toggle-currently-ongoing"));
    await user.click(
      within(editor).getByRole("combobox", { name: "Skills used" })
    );
    await user.click(await screen.findByRole("option", { name: "Python" }));
    await user.type(
      screen.getByRole("combobox", { name: "Search options" }),
      "Rust Embedded"
    );
    await user.click(
      await screen.findByRole("option", { name: 'Add skill "Rust Embedded"' })
    );
    await user.keyboard("{Escape}");
    await user.click(within(editor).getByTestId("save-experience"));
    await waitFor(() =>
      expect(createExperienceItem).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Backend job",
          start: iso,
          end: null,
          open_ended: true,
          skills: [
            expect.objectContaining({ skill_key: "python" }),
            expect.objectContaining({ skill_key: "rust-embedded" }),
          ],
        })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("experience-item-new-1")).toBeInTheDocument()
    );
  });

  it("deletes optimistically and restores through undo (POST of the snapshot)", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("experience-item-e1");
    await user.click(screen.getByTestId("delete-experience-e1"));
    await waitFor(() =>
      expect(screen.queryByTestId("experience-item-e1")).not.toBeInTheDocument()
    );
    const notice = screen.getByTestId("undo-experience");
    expect(notice).toHaveTextContent("Deleted “DevOps intern”");
    await user.click(within(notice).getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(createExperienceItem).toHaveBeenCalledWith(
        expect.objectContaining({ title: "DevOps intern" })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("experience-item-new-1")).toBeInTheDocument()
    );
    expect(createExperienceItem).toHaveBeenCalledTimes(1);
  });

  it("guards dirty editor switches with a confirmation", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("e1");
    const editor = screen.getByTestId("experience-editor");
    await user.type(within(editor).getByTestId("experience-title"), "!");
    const card2 = await screen.findByTestId("experience-item-e2");
    fireEvent.click(within(card2).getByTestId("experience-item"));
    expect(
      await screen.findByText("Discard changes?")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() =>
      expect(
        within(screen.getByTestId("experience-editor")).getByTestId(
          "experience-title"
        )
      ).toHaveValue("Capstone")
    );
    expect(updateExperienceItem).not.toHaveBeenCalled();
  });

  it("cancelling a clean edit just closes the editor", async () => {
    const user = userEvent.setup();
    renderPage();
    await openItem("e1");
    const editor = screen.getByTestId("experience-editor");
    await user.click(within(editor).getByTestId("cancel-experience"));
    expect(await screen.findByText("Nothing selected")).toBeInTheDocument();
  });

  it("applies derivation and reports the outcome", async () => {
    renderPage();
    const button = await screen.findByTestId("apply-derivation");
    fireEvent.click(button);
    expect(await screen.findByTestId("apply-state")).toHaveTextContent(
      "Applied 1 skill level(s)"
    );
  });

  it("collapses the derivation panel", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("derivation-panel");
    const toggle = screen.getByTestId("derivation-toggle");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByTestId("apply-derivation")).toBeInTheDocument();
  });
});
