import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { bulletsVariantRow, aiAction, createExperienceEntry, createSynthItem, cv, fetchContextSources, fetchContextStatus, fetchCv, fetchExperienceRows, fetchLint, fetchOntology, fetchSynthItems, openInspectorTab, patchCv, preview, previewCv, resetCvStudioMocks, setContext, setSynthPin, updateExperienceEntry } from "@/tests/cvStudioHarness";
import { CvBuilder } from "@/features/cv/pages/CvBuilder";
import { CvStudio } from "@/features/cv/pages/CvStudio";
import { CvTemplateEditor } from "@/features/cv/pages/CvTemplateEditor";

function renderBuilder() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv/cv-1"]}>
        <Routes>
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(resetCvStudioMocks);

describe("CvBuilder — plan 105 context entity editing", () => {
  it("creates an experience entry from the context tab and refreshes sources", async () => {
    const user = userEvent.setup();
    fetchOntology.mockResolvedValue([]);
    createExperienceEntry.mockResolvedValue({});
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    await user.click(screen.getByTestId("context-add-experience"));
    const modal = await screen.findByTestId("entity-editor-modal");
    expect(within(modal).getByTestId("experience-title")).toHaveValue("");
    const titleInput = within(modal).getByTestId("experience-title");
    await user.type(titleInput, "Backend intern");
    expect(titleInput).toHaveValue("Backend intern");
    await user.click(
      within(modal).getByRole("button", { name: "Start date" }),
    );
    const now = new Date();
    const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-15`;
    await user.click(document.querySelector(`[data-day="${iso}"]`)!);
    await user.click(within(modal).getByTestId("toggle-currently-ongoing"));
    await user.click(within(modal).getByTestId("save-experience"));
    await waitFor(() =>
      expect(createExperienceEntry).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Backend intern", kind: "job", source: "self_report" }),
      ),
    );
    expect(screen.queryByTestId("entity-editor-modal")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchContextSources.mock.calls.length).toBe(2));
  });

  it("edits the profile entry behind a context item through the modal", async () => {
    const user = userEvent.setup();
    fetchOntology.mockResolvedValue([]);
    fetchExperienceRows.mockResolvedValue({
      items: [
        {
          id: "exp-1",
          kind: "internship",
          title: "DevOps intern",
          org_name: "Acme",
          start: "2025-01-01",
          end: "2025-12-31",
          open_ended: false,
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
      ],
      years_of_experience: 0.9,
    });
    updateExperienceEntry.mockResolvedValue({});
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    await user.click(screen.getByTestId("context-edit-item-experience:exp-1"));
    const modal = await screen.findByTestId("entity-editor-modal");
    expect(within(modal).getByTestId("experience-title")).toHaveValue("DevOps intern");
    await user.click(within(modal).getByTestId("save-experience"));
    await waitFor(() =>
      expect(updateExperienceEntry).toHaveBeenCalledWith(
        "exp-1",
        expect.objectContaining({ title: "DevOps intern" }),
      ),
    );
    expect(screen.queryByTestId("entity-editor-modal")).not.toBeInTheDocument();
  });
});

describe("CvBuilder — plan 105 origin-aware sync", () => {
  it("local bumps refetch context sources and skip the profile-changed toast", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    const { useToastStore } = await import("@/stores/toastStore");
    useToastStore.setState({ toasts: [] });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fetchContextStatus.mockResolvedValue({
      has_baseline: true,
      stale: true,
      changed: [],
      added: [],
      removed: [],
    });
    const initialSources = fetchContextSources.mock.calls.length;
    const initialLint = fetchLint.mock.calls.length;
    useCvBuilderLink.setState({ dataRevision: 0, lastDataOrigin: "chat" });
    act(() => {
      useCvBuilderLink.getState().notifyDataChanged("local");
    });
    await waitFor(
      () =>
        expect(fetchContextSources.mock.calls.length).toBeGreaterThan(
          initialSources,
        ),
      { timeout: 3000 },
    );
    await waitFor(
      () => expect(fetchLint.mock.calls.length).toBeGreaterThan(initialLint),
      { timeout: 3000 },
    );
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("chat bumps keep toasting on a stale baseline", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    const { useToastStore } = await import("@/stores/toastStore");
    useToastStore.setState({ toasts: [] });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fetchContextStatus.mockResolvedValue({
      has_baseline: true,
      stale: true,
      changed: [],
      added: [],
      removed: [],
    });
    const initialLint = fetchLint.mock.calls.length;
    useCvBuilderLink.setState({ dataRevision: 0, lastDataOrigin: "local" });
    act(() => {
      useCvBuilderLink.getState().notifyDataChanged();
    });
    await waitFor(
      () => expect(fetchLint.mock.calls.length).toBeGreaterThan(initialLint),
      { timeout: 3000 },
    );
    expect(useToastStore.getState().toasts.length).toBe(1);
    expect(useToastStore.getState().toasts[0].title).toBe("Profile changed");
  });
});

describe("CvBuilder — plan 106 bullets editor", () => {

  it("saves the bullets as a bullets variant and pins it (single slot)", async () => {
    const user = userEvent.setup();
    previewCv.mockResolvedValue({
      ...preview,
      resolution: {
        ...preview.resolution,
        snapshot: {
          experience: [
            {
              id: "exp-1",
              title: "DevOps intern",
              org_name: "Acme",
              achievements: [{ text: "Shipped the QA harness" }],
            },
          ],
        },
        snapshot_index: { experience: ["exp-1"] },
      },
    });
    createSynthItem.mockResolvedValue(
      bulletsVariantRow("syn-b1", ["Cut the deploy pipeline to minutes"]),
    );
    setContext.mockImplementation(async () => ({ ...cv }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    await user.click(screen.getByTestId("context-bullets-experience:exp-1"));
    const modal = await screen.findByTestId("bullets-editor-modal");
    expect(
      within(modal).getByTestId("bullets-editor-head")
    ).toHaveTextContent("DevOps intern · Acme");
    expect(within(modal).getByTestId("bullets-row-0")).toHaveValue(
      "Shipped the QA harness"
    );
    await user.clear(within(modal).getByTestId("bullets-row-0"));
    await user.type(
      within(modal).getByTestId("bullets-row-0"),
      "Cut the deploy pipeline to minutes",
    );
    await user.click(within(modal).getByTestId("bullets-editor-save"));
    expect(screen.queryByTestId("bullets-editor-modal")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(createSynthItem).toHaveBeenCalledWith({
        refs: [{ source_key: "experience", item_id: "exp-1" }],
        scope: "bullets",
        payload: {
          achievements: [{ text: "Cut the deploy pipeline to minutes" }],
        },
        voice: { language: "en" },
      }),
    );
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        "syn-b1",
      ),
    );
    await waitFor(() =>
      expect(previewCv.mock.calls.length).toBeGreaterThan(1),
    );
  });

  it("shows the edited chip for a pinned bullets variant; reset unpins it", async () => {
    const user = userEvent.setup();
    fetchCv.mockResolvedValue({
      ...cv,
      context: {
        ...cv.context,
        synth_pins: { "experience:exp-1": "syn-b1" },
      },
    });
    fetchSynthItems.mockResolvedValue([
      bulletsVariantRow("syn-b1", ["Tailored bullet"]),
    ]);
    setContext.mockImplementation(async () => ({ ...cv }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    await user.click(screen.getByTestId("context-bullets-experience:exp-1"));
    const modal = await screen.findByTestId("bullets-editor-modal");
    expect(within(modal).getByTestId("bullets-edited-chip")).toBeInTheDocument();
    expect(within(modal).getByTestId("bullets-row-0")).toHaveValue(
      "Tailored bullet",
    );
    await user.click(within(modal).getByTestId("bullets-editor-reset"));
    const confirms = screen.getAllByRole("button", {
      name: "Reset to profile",
    });
    await user.click(confirms[confirms.length - 1]);
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        null,
      ),
    );
    expect(patchCv).not.toHaveBeenCalled();
  });
});

describe("CvBuilder — plan 106 bullet action retarget", () => {
  it("lands bullet proposals in the editor as chips; saving writes a bullets variant", async () => {
    const user = userEvent.setup();
    aiAction.mockResolvedValue({
      action: "bullet",
      notes: "",
      proposals: [
        {
          proposal: {
            ref: { source_key: "experience", item_id: "exp-1" },
            field: "achievements",
            text: "DevOps intern — cut effort by ~<your number>%",
            bullets: [
              "Cut the deploy pipeline to minutes",
              "Cut flaky retries by ~<your number>%",
            ],
            rationale: "Metric placeholder kept explicit.",
            evidence_refs: [{ source_key: "experience", item_id: "exp-1" }],
          },
          verified: true,
        },
      ],
      coverage: null,
      gaps: [],
    });
    previewCv.mockResolvedValue({
      ...preview,
      resolution: {
        ...preview.resolution,
        snapshot: {
          experience: [
            {
              id: "exp-1",
              title: "DevOps intern",
              org_name: "Acme",
              achievements: [{ text: "Shipped the QA harness" }],
            },
          ],
        },
        snapshot_index: { experience: ["exp-1"] },
      },
    });
    createSynthItem.mockResolvedValue(
      bulletsVariantRow("syn-b2", ["Shipped the QA harness"]),
    );
    setContext.mockImplementation(async () => ({ ...cv }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(
      await screen.findByRole("button", { name: "Improve summary" }),
    );
    const slideOver = await screen.findByTestId("proposals-slideover");
    fireEvent.click(within(slideOver).getByTestId("apply-proposal"));
    expect(screen.queryByTestId("proposals-slideover")).not.toBeInTheDocument();
    const modal = await screen.findByTestId("bullets-editor-modal");
    expect(
      within(modal).getByTestId("bullet-chip-0"),
    ).toHaveTextContent("Cut the deploy pipeline to minutes");
    await user.click(within(modal).getByTestId("bullet-chips-confirm"));
    expect(
      within(modal).getByTestId("bullets-row-1"),
    ).toHaveValue("Cut the deploy pipeline to minutes");
    await user.click(within(modal).getByTestId("bullets-editor-save"));
    await waitFor(() =>
      expect(createSynthItem).toHaveBeenCalledWith({
        refs: [{ source_key: "experience", item_id: "exp-1" }],
        scope: "bullets",
        payload: {
          achievements: [
            { text: "Shipped the QA harness" },
            { text: "Cut the deploy pipeline to minutes" },
            { text: "Cut flaky retries by ~<your number>%" },
          ],
        },
        voice: { language: "en" },
      }),
    );
    const body = createSynthItem.mock.calls[createSynthItem.mock.calls.length - 1][0];
    expect(body.payload.description).toBeUndefined();
  });
});

describe("CvBuilder — plan 106 slice 5 generate-fill", () => {
  it("generates bullets inside the editor from the item's evidence and lands them as chips", async () => {
    const user = userEvent.setup();
    aiAction.mockResolvedValue({
      action: "bullet",
      notes: "",
      proposals: [
        {
          proposal: {
            ref: { source_key: "experience", item_id: "exp-1" },
            field: "achievements",
            text: "DevOps intern — cut effort by ~<your number>%",
            bullets: ["Automated the release train end to end"],
            rationale: "",
            evidence_refs: [{ source_key: "experience", item_id: "exp-1" }],
          },
          verified: true,
        },
      ],
      coverage: null,
      gaps: [],
    });
    previewCv.mockResolvedValue({
      ...preview,
      resolution: {
        ...preview.resolution,
        snapshot: {
          experience: [
            {
              id: "exp-1",
              title: "DevOps intern",
              org_name: "Acme",
              description: "Built QA tooling and release automation",
              achievements: [{ text: "Shipped the QA harness" }],
            },
          ],
        },
        snapshot_index: { experience: ["exp-1"] },
      },
    });
    createSynthItem.mockResolvedValue(
      bulletsVariantRow("syn-b3", ["Shipped the QA harness"]),
    );
    setContext.mockImplementation(async () => ({ ...cv }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    await user.click(screen.getByTestId("context-bullets-experience:exp-1"));
    const modal = await screen.findByTestId("bullets-editor-modal");
    await user.click(within(modal).getByTestId("bullets-editor-generate"));
    await waitFor(() =>
      expect(aiAction).toHaveBeenCalledWith("cv-1", "bullet", {
        source_key: "experience",
        item_id: "exp-1",
        text: "Built QA tooling and release automation",
      }),
    );
    await waitFor(() =>
      expect(
        within(modal).getByTestId("bullet-chip-0"),
      ).toHaveTextContent("Automated the release train end to end"),
    );
    await user.click(within(modal).getByTestId("bullet-chips-confirm"));
    await user.click(within(modal).getByTestId("bullets-editor-save"));
    await waitFor(() =>
      expect(createSynthItem).toHaveBeenCalledWith({
        refs: [{ source_key: "experience", item_id: "exp-1" }],
        scope: "bullets",
        payload: {
          achievements: [
            { text: "Shipped the QA harness" },
            { text: "Automated the release train end to end" },
          ],
        },
        voice: { language: "en" },
      }),
    );
  });
});
