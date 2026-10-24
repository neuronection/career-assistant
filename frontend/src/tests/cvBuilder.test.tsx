import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { aiAction, compileCv, createAssistantSession, createCoverLetter, cv, exportCv, fetchAssistantMessages, fetchCv, fetchCvRuns, fetchLint, fetchPhotoBlobUrl, fetchPhotoGallery, fetchTemplatePreview, fetchTemplates, fetchVersionPreview, fetchVersions, lint, openInspectorTab, patchCv, preview, previewCv, resetCvStudioMocks, restoreVersion, setContext, sidebarTemplate, typeIntoRichText, uploadGalleryPhoto } from "@/tests/cvStudioHarness";
import { CvBuilder } from "@/features/cv/pages/CvBuilder";
import { useChatStore } from "@/stores/chatStore";
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

describe("CvBuilder", () => {
  it("shows the AI draft banner for generated CVs and dismisses it", async () => {
    fetchCv.mockResolvedValue({ ...cv, working_content: { generated_by: "cv_draft" } });
    renderBuilder();
    expect(await screen.findByTestId("ai-draft-banner")).toHaveTextContent(
      /AI draft applied/
    );
    fireEvent.click(screen.getByTestId("dismiss-ai-draft"));
    expect(screen.queryByTestId("ai-draft-banner")).not.toBeInTheDocument();
  });

  it("regenerate reopens the generate flow from the banner", async () => {
    fetchCv.mockResolvedValue({ ...cv, working_content: { generated_by: "cv_draft" } });
    renderBuilder();
    await screen.findByTestId("ai-draft-banner");
    fireEvent.click(screen.getByTestId("regenerate-cv"));
    expect(await screen.findByTestId("cv-generate-form")).toBeInTheDocument();
  });

  it("hides the AI draft banner for hand-made CVs", async () => {
    renderBuilder();
    await screen.findByTestId("builder-toolbar");
    expect(screen.queryByTestId("ai-draft-banner")).not.toBeInTheDocument();
  });

  it("Ask AI opens the shared chat docked and bound to this CV", async () => {
    renderBuilder();
    expect(await screen.findByTestId("preview-frame")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("cv-ask-ai"));
    await waitFor(() =>
      expect(createAssistantSession).toHaveBeenCalledWith({
        title: "CV chat",
        context: undefined,
      }),
    );
    await waitFor(() => expect(useChatStore.getState().chatMode).toBe("docked"));
    await waitFor(() => expect(useChatStore.getState().activeSessionId).toBe("s-assist"));
    expect(fetchAssistantMessages).toHaveBeenCalledWith("s-assist");
    await waitFor(() =>
      expect(useChatStore.getState().pendingCvAttach).toEqual({
        id: "cv-1",
        title: "Backend Intern CV",
      }),
    );
  });

  it("Runs & metrics popup lists runs with the LLM-call ledger and ops", async () => {
    fetchCvRuns.mockResolvedValue([
      {
        job_id: "job-polish-1",
        job_type: "cv_polish",
        status: "succeeded",
        stage: "done",
        error: null,
        created_at: "2026-09-11T10:00:00Z",
        finished_at: "2026-09-11T10:00:05Z",
        outcome: "completed",
        resumed_from: "job-generate-1",
        final_version: 3,
        stages: [{ node: "review", at: "2026-09-11T10:00:01Z", note: "reviewing the draft (1/3)" }],
        iterations: [
          {
            n: 0,
            summary: "Tightened spacing",
            ops: [
              { op: "update_design", ok: true, detail: "design updated (private copy)" },
              { op: "set_override", ok: false, detail: "reverted" },
            ],
            coverage: { missing: [{ source_key: "projects", item_id: "p1", label: "PWA project" }] },
          },
        ],
        llm_calls: [
          {
            id: "a1",
            task: "cv_build_review",
            stage: "cv_draft.review",
            status: "ok",
            provider: "mock",
            model: "mock-vision",
            prompt_version: "v1",
            tokens_in: 3200,
            tokens_out: 700,
            latency_ms: 850,
          },
        ],
        aggregate: {
          calls: 1,
          tokens_in: 3200,
          tokens_out: 700,
          latency_ms_sum: 850,
          by_task: { cv_build_review: { calls: 1, tokens_in: 3200, tokens_out: 700, latency_ms_sum: 850 } },
        },
      },
    ]);
    renderBuilder();
    await userEvent.click(await screen.findByTestId("open-runs"));
    const row = await screen.findByTestId("cv-run-row");
    expect(row).toHaveAttribute("data-run-type", "cv_polish");
    expect(row).toHaveTextContent("1 call(s) · 3200 in / 700 out");
    expect(row).toHaveTextContent("final v3");
    expect(row).toHaveTextContent("AI polish finished — review the final draft in the builder.");
    fireEvent.click(screen.getByTestId("cv-run-toggle"));
    const detail = await screen.findByTestId("cv-runs-detail");
    expect(detail).toHaveTextContent("Reviewing the build");
    expect(detail).toHaveTextContent("mock-vision");
    expect(detail).toHaveTextContent("850 ms");
    expect(detail).toHaveTextContent("Reviewing the draft");
    expect(detail).toHaveTextContent("✓");
    expect(detail).toHaveTextContent("✗");
    expect(screen.getByTestId("cv-runs-coverage")).toHaveTextContent(
      "PWA project"
    );
    expect(detail).toHaveTextContent(/earlier run/);
  });

  it("runs popup shows the empty state and recovers from a fetch error", async () => {
    fetchCvRuns.mockResolvedValue([]);
    renderBuilder();
    await userEvent.click(await screen.findByTestId("open-runs"));
    expect(await screen.findByTestId("cv-runs-list")).toHaveTextContent(
      "No AI runs yet"
    );
    await userEvent.click(await screen.findByRole("button", { name: "Close" }));
    fetchCvRuns.mockRejectedValue(new Error("boom"));
    await userEvent.click(await screen.findByTestId("open-runs"));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("renders preview, lint score and context toggles", async () => {
    renderBuilder();
    expect(await screen.findByTestId("preview-frame")).toHaveAttribute("srcdoc", expect.stringContaining("Experience"));
    expect(await screen.findByText("ATS 92")).toBeInTheDocument();
    await openInspectorTab("context");
    expect(screen.getByTestId("context-toggle-experience:exp-1")).toBeChecked();
    expect(screen.getByTestId("context-toggle-skills:sk-1")).toBeChecked();
  });

  it("shows a shimmer skeleton while the preview loads", async () => {
    let resolvePreview: (value: typeof preview) => void = () => {};
    previewCv.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePreview = resolve;
        })
    );
    renderBuilder();
    expect(await screen.findByTestId("preview-skeleton")).toBeInTheDocument();
    resolvePreview(preview);
    await waitFor(() =>
      expect(screen.queryByTestId("preview-skeleton")).not.toBeInTheDocument()
    );
    expect(screen.getByTestId("preview-frame")).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("Experience")
    );
  });

  it("zooms the preview in, out and back with the floating zoom bar", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    expect(screen.getByTestId("zoom-label")).toHaveTextContent("100%");
    fireEvent.click(screen.getByTestId("zoom-in"));
    expect(screen.getByTestId("zoom-label")).toHaveTextContent("125%");
    fireEvent.click(screen.getByTestId("zoom-out"));
    fireEvent.click(screen.getByTestId("zoom-out"));
    expect(screen.getByTestId("zoom-label")).toHaveTextContent("75%");
    const wrapper = screen.getByTestId("preview-frame").closest("div[style]");
    expect(wrapper).toHaveAttribute("style", expect.stringContaining("scale(0.75)"));
    expect(wrapper).toHaveAttribute("style", expect.stringContaining("width: 133.33333333333334%"));
    fireEvent.click(screen.getByTestId("zoom-fit"));
    expect(screen.getByTestId("zoom-label")).toHaveTextContent("100%");
  });

  it("re-fits on pane resize and keeps manual zoom until fit is chosen again", async () => {
    let clientWidth = 794;
    const descriptor = Object.getOwnPropertyDescriptor(
      Element.prototype,
      "clientWidth"
    );
    Object.defineProperty(Element.prototype, "clientWidth", {
      configurable: true,
      get: () => clientWidth,
    });
    let onResize: ResizeObserverCallback | undefined;
    class CapturingObserver {
      constructor(cb: ResizeObserverCallback) {
        onResize = cb;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    const originalObserver = global.ResizeObserver;
    global.ResizeObserver = CapturingObserver as never;
    try {
      renderBuilder();
      await screen.findByTestId("preview-frame");
      expect(screen.getByTestId("zoom-label")).toHaveTextContent("100%");
      expect(screen.getByTestId("zoom-fit")).toHaveAttribute(
        "aria-pressed",
        "true"
      );

      fireEvent.click(screen.getByTestId("zoom-in"));
      expect(screen.getByTestId("zoom-label")).toHaveTextContent("125%");
      expect(screen.getByTestId("zoom-fit")).toHaveAttribute(
        "aria-pressed",
        "false"
      );

      clientWidth = 1588;
      act(() => {
        onResize?.([], null as never);
      });
      expect(screen.getByTestId("zoom-label")).toHaveTextContent("125%");

      fireEvent.click(screen.getByTestId("zoom-fit"));
      expect(screen.getByTestId("zoom-label")).toHaveTextContent("200%");

      clientWidth = 397;
      act(() => {
        onResize?.([], null as never);
      });
      expect(screen.getByTestId("zoom-label")).toHaveTextContent("50%");
      expect(screen.getByTestId("zoom-fit")).toHaveAttribute(
        "aria-pressed",
        "true"
      );
    } finally {
      if (descriptor) {
        Object.defineProperty(Element.prototype, "clientWidth", descriptor);
      }
      global.ResizeObserver = originalObserver;
    }
  });

  it("shows the autosave indicator while persisting working content", async () => {
    let resolvePatch: (() => void) | undefined;
    patchCv.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePatch = () => resolve(cv);
        })
    );
    renderBuilder();
    await openInspectorTab("sections");
    await userEvent.click(screen.getByTestId("section-menu-1"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move up" }));
    await waitFor(() =>
      expect(screen.getByTestId("autosave-indicator")).toHaveTextContent("Saving…")
    );
    resolvePatch?.();
    await waitFor(() =>
      expect(screen.getByTestId("autosave-indicator")).toHaveTextContent("Saved")
    );
  });

  it("undoes and redoes section changes through the 20-step local stack", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-languages"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const [, addedBody] = patchCv.mock.calls[0];
    expect(addedBody.working_content.blocks).toHaveLength(3);
    fireEvent.click(screen.getByTestId("undo"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2));
    expect(patchCv.mock.calls[1][1].working_content.blocks).toHaveLength(2);
    fireEvent.click(screen.getByTestId("redo"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(3));
    expect(patchCv.mock.calls[2][1].working_content.blocks).toHaveLength(3);
  });

  it("offers an Undo notice after removing a section", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    const menus = screen.getAllByTestId(/section-menu-\d+/);
    await userEvent.click(menus[menus.length - 1]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Remove" }));
    const host = await screen.findByTestId("undo-notice-host");
    expect(host).toHaveTextContent("Section removed");
    fireEvent.click(within(host).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2));
    expect(patchCv.mock.calls[1][1].working_content.blocks).toHaveLength(2);
  });

  it("compares two versions side by side in the diff panel", async () => {
    fetchVersions.mockResolvedValue([
      { id: "v2", version: 2, content: {}, context_resolution: {}, content_hash: "h2", created_by: "user", created_at: "2026-09-04T12:00:00Z" },
      { id: "v1", version: 1, content: {}, context_resolution: {}, content_hash: "h1", created_by: "user", created_at: "2026-09-04T10:00:00Z" },
    ]);
    fetchVersionPreview.mockImplementation(async (_id: string, version: number) =>
      `<html><body>v${version} snapshot</body></html>`
    );
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("open-versions"));
    fireEvent.click(await screen.findByTestId("diff-version-2"));
    const diffPanel = await screen.findByTestId("version-diff-panel");
    expect(within(diffPanel).getByTestId("version-diff-frame-new")).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("v2 snapshot")
    );
    expect(within(diffPanel).getByTestId("version-diff-frame-old")).toHaveAttribute(
      "srcdoc",
      expect.stringContaining("v1 snapshot")
    );
  });

  it("edits custom-text blocks with the rich-text editor", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-custom_text"));
    fireEvent.click(await screen.findByTestId("edit-custom-text"));
    const editor = await screen.findByTestId("custom-text-editor");
    expect(within(editor).getByRole("toolbar")).toBeInTheDocument();
    expect(within(editor).getByRole("button", { name: "Bold (**bold**)" })).toBeInTheDocument();
    expect(within(editor).getByRole("button", { name: "Italic (*italic*)" })).toBeInTheDocument();
    await typeIntoRichText(editor, "Hello world");
    await waitFor(() => {
      const calls = patchCv.mock.calls;
      const blocks = calls[calls.length - 1]?.[1]?.working_content?.blocks;
      expect(blocks?.[blocks.length - 1]?.props?.text).toBe("Hello world");
    }, { timeout: 3000 });
  });

  it("autosaves custom-text edits into working_content", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-custom_text"));
    fireEvent.click(await screen.findByTestId("edit-custom-text"));
    const editor = await screen.findByTestId("custom-text-editor");
    await typeIntoRichText(editor, "Few words about me");
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2), { timeout: 3000 });
    const blocks = patchCv.mock.calls[1][1].working_content.blocks;
    expect(blocks[blocks.length - 1].props.text).toBe("Few words about me");
  });

  it("edits the summary text as a CV override", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("configure-section-1"));
    const editor = await screen.findByTestId("summary-text-1");
    fireEvent.change(editor, {
      target: { value: "Typed summary from the studio." },
    });
    await waitFor(() => expect(patchCv).toHaveBeenCalled(), { timeout: 3000 });
    const body = patchCv.mock.calls[patchCv.mock.calls.length - 1][1] as {
      working_content: { overrides: Record<string, { summary: string }> };
    };
    expect(body.working_content.overrides["summary:summary"].summary).toBe(
      "Typed summary from the studio."
    );
  });

  it("marks estimated page boundaries when the CV grows over one page", async () => {
    previewCv.mockResolvedValue({ ...preview, metrics: { ...preview.metrics, estimated_pages: 2 } });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    expect(await screen.findByTestId("page-break-2")).toBeInTheDocument();
    expect(screen.getByTestId("page-break-2")).toHaveTextContent("Page 2");
  });

  it("shows no page boundary on a single-page CV", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    expect(screen.queryByTestId(/page-break-/)).not.toBeInTheDocument();
  });

  it("adds sections from the card picker with previews", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    const menu = await screen.findByTestId("add-section-menu");
    expect(within(menu).getByTestId("block-preview-skills")).toBeInTheDocument();
    expect(within(menu).getByText("About me")).toBeInTheDocument();
    fireEvent.click(within(menu).getByTestId("add-block-skills"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks[blocks.length - 1].props.display).toBe("chips");
  });

  it("duplicates a section with its configuration", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    await userEvent.click(screen.getByTestId("section-menu-1"));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Duplicate" }));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks).toHaveLength(3);
    expect(blocks[2].kind).toBe("summary");
  });

  it("summarizes a section's configuration at a glance", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    expect(screen.queryByTestId("section-summary-0")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-skills"));
    expect(await screen.findByTestId("section-summary-2")).toHaveTextContent("Chips");
    expect(screen.getByTestId("section-summary-2")).toHaveTextContent("max 18");
  });

  it("hides a section with the eye toggle and persists the flag", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("section-hide-0"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    expect(patchCv.mock.calls[0][1].working_content.blocks[0].hidden).toBe(true);
    expect(screen.getByTestId("section-card-0")).toHaveClass("opacity-60");
    expect(screen.getByTestId("section-summary-0")).toHaveTextContent("Hidden");
    fireEvent.click(await screen.findByTestId("section-hide-0"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2));
    expect(patchCv.mock.calls[1][1].working_content.blocks[0].hidden).toBe(false);
  });

  it("reorders sections with arrow keys on the drag handle", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.keyDown(screen.getByTestId("section-handle-1"), { key: "ArrowUp" });
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks.map((block: { kind: string }) => block.kind)).toEqual([
      "summary",
      "header",
    ]);
  });

  it("configures a section inline via stepper and toggle", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-skills"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    fireEvent.click(await screen.findByTestId("toggle-show-levels"));
    fireEvent.click(screen.getByLabelText("Max items increase"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2), { timeout: 3000 });
    const last = patchCv.mock.calls[1][1].working_content.blocks[2].props;
    expect(last.show_levels).toBe(true);
    expect(last.max_items).toBe(19);
  });

  it("dims the dragged card and restores it on drag end", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    const cards = await screen.findAllByTestId(/section-card-\d+/);
    fireEvent.dragStart(cards[1]);
    expect(cards[1]).toHaveClass("opacity-40");
    fireEvent.dragEnd(cards[1]);
    expect(cards[1]).not.toHaveClass("opacity-40");
  });

  it("groups sections by template area, adds per area and reassigns by drag", async () => {
    fetchTemplates.mockResolvedValue([sidebarTemplate]);
    fetchCv.mockResolvedValue({ ...cv, template_id: "tpl-1" });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    expect(await screen.findByTestId("area-group-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("area-group-main")).toBeInTheDocument();
    expect(screen.getByTestId("area-count-sidebar")).toHaveTextContent("0");
    expect(screen.queryByTestId("section-area-0")).not.toBeInTheDocument();

    const firstCard = screen.getByTestId("section-card-0");
    fireEvent.dragStart(firstCard);
    const sidebarGroup = screen.getByTestId("area-group-sidebar");
    fireEvent.drop(sidebarGroup);
    await waitFor(() => expect(patchCv).toHaveBeenCalled());
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks[blocks.length - 1]).toMatchObject({
      kind: "header",
      area: "sidebar",
      column: "sidebar",
    });
    await waitFor(() =>
      expect(screen.getByTestId("area-count-sidebar")).toHaveTextContent("1")
    );

    fireEvent.click(await screen.findByTestId("add-section-sidebar"));
    const menu = await screen.findByTestId("add-section-menu");
    expect(within(menu).queryByText("Add to")).not.toBeInTheDocument();
    fireEvent.click(within(menu).getByTestId("add-block-skills"));
    await waitFor(() =>
      expect(patchCv.mock.calls.length).toBeGreaterThanOrEqual(2)
    );
    const saved = patchCv.mock.calls[patchCv.mock.calls.length - 1][1];
    const savedBlocks = saved.working_content.blocks;
    expect(savedBlocks[savedBlocks.length - 1]).toMatchObject({
      kind: "skills",
      area: "sidebar",
      column: "sidebar",
    });
  });

  it("keeps the global add picker area toggle for sidebar templates", async () => {
    fetchTemplates.mockResolvedValue([sidebarTemplate]);
    fetchCv.mockResolvedValue({ ...cv, template_id: "tpl-1" });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(await screen.findByTestId("add-section-button"));
    const menu = await screen.findByTestId("add-section-menu");
    expect(await screen.findByText("Add to")).toBeInTheDocument();
    await userEvent.click(
      within(screen.getByRole("group", { name: "Add to" })).getByRole("button", {
        name: "Left panel",
      })
    );
    fireEvent.click(within(menu).getByTestId("add-block-skills"));
    await waitFor(() => expect(patchCv).toHaveBeenCalled());
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks[blocks.length - 1]).toMatchObject({
      kind: "skills",
      area: "sidebar",
      column: "sidebar",
    });
  });

  it("shows the polish notes inside the AI runs panel, not as a separate button", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    expect(screen.queryByTestId("polish-trace-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("open-polish")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("open-runs")[0]).toHaveTextContent("AI runs");

    fetchVersions.mockResolvedValue([
      {
        id: "v-polish",
        version: 2,
        content: {
          polish: {
            request: { notes: "Lead with the internship.", length: "standard", language: "en", max_pages: 1 },
            outcome: { status: "completed" },
            iterations: [
              {
                n: 0,
                summary: "One spacing fix.",
                ops: [{ op: "move_block", ok: true, detail: "Languages section moved" }],
              },
            ],
          },
        },
        context_resolution: {},
        content_hash: "h",
        created_by: "ai_apply",
        created_at: "2026-09-04T12:00:00Z",
      } as never,
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const allRunsButtons = await screen.findAllByTestId("open-runs");
    const runsButton = allRunsButtons[allRunsButtons.length - 1];
    expect(runsButton).toHaveTextContent("Notes");
    expect(screen.queryByTestId("polish-trace-card")).not.toBeInTheDocument();
    await userEvent.click(runsButton);
    expect(await screen.findByTestId("runs-panel")).toBeInTheDocument();
    expect(screen.getByTestId("polish-trace-card")).toHaveTextContent(
      "Lead with the internship."
    );
    expect(screen.getByText("Languages section moved")).toBeInTheDocument();
  });

  it("keeps a flat single-layout list with no area controls", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    await screen.findByTestId("sections-list");
    expect(screen.queryByTestId(/area-group-/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("section-area-0")).not.toBeInTheDocument();
  });

  it("configures a languages block format with CEFR and proficiency toggles", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-languages"));
    await waitFor(() => expect(patchCv).toHaveBeenCalled());
    const addedCount = patchCv.mock.calls[0][1].working_content.blocks.length;
    expect(addedCount).toBeGreaterThanOrEqual(3);
    fireEvent.click(screen.getByTestId("configure-section-2"));
    fireEvent.click(await screen.findByTestId("toggle-show-cefr-band"));
    fireEvent.click(await screen.findByTestId("toggle-latest-proficiency-certificate"));
    await waitFor(
      () => {
        const blocks =
          patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
            .blocks;
        expect(blocks[blocks.length - 1].props.show_cefr).toBe(true);
        expect(blocks[blocks.length - 1].props.show_proficiency).toBe(true);
      },
      { timeout: 3000 }
    );
  });

  it("opens the template style editor from the Design tab Customize button", async () => {
    renderBuilder();
    await openInspectorTab("design");
    expect(screen.getByTestId("customize-template")).toBeDisabled();
    fireEvent.change(await screen.findByTestId("template-picker"), {
      target: { value: "tpl-1" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("customize-template")).toBeEnabled()
    );
    fireEvent.click(screen.getByTestId("customize-template"));
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
  });

  it("opens the template style editor from the gallery Customize button", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("design");
    fireEvent.click(screen.getByTestId("browse-templates"));
    fireEvent.click(await screen.findByTestId("edit-template-tpl-1"));
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
  });

  it("renders the full-bleed workspace shell with toolbar, side rail and canvas", async () => {
    renderBuilder();
    expect(await screen.findByTestId("builder-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("builder-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("builder-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("ats-chip")).toHaveTextContent("ATS 92");
  });

  it("keys its panes off the workspace container, not the viewport", async () => {
    renderBuilder();
    expect(await screen.findByTestId("cv-builder")).toHaveClass("ca-workspace");
    expect(screen.getByTestId("pane-switcher")).toHaveClass("ca-ws-switcher");
    expect(screen.getByTestId("builder-inspector")).toHaveClass("ca-ws-pane");
    expect(screen.getByTestId("builder-canvas")).toHaveClass("ca-ws-pane");
  });

  it("hosts the sections panel as the inspector's default tab", async () => {
    renderBuilder();
    expect(await screen.findByTestId("builder-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("inspector-body-sections")).toBeInTheDocument();
    expect(screen.getAllByTestId(/section-card-\d+/).length).toBeGreaterThan(0);
    await openInspectorTab("context");
    expect(screen.getByTestId("inspector-body-context")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-body-sections")).toBeNull();
  });

  it("exports via the Download dropdown", async () => {
    const user = userEvent.setup();
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await user.click(screen.getByTestId("export-dropdown"));
    await user.click(await screen.findByTestId("export-item-md"));
    await waitFor(() => expect(exportCv).toHaveBeenCalledWith("cv-1", "md"));
  });

  it("renames the CV inline from the toolbar", async () => {
    renderBuilder();
    const input = await screen.findByTestId("cv-title-input");
    fireEvent.change(input, { target: { value: "Renamed CV" } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { title: "Renamed CV" })
    );
  });

  it("keeps the old title when the inline edit is cancelled with Escape", async () => {
    renderBuilder();
    const input = await screen.findByTestId("cv-title-input");
    fireEvent.change(input, { target: { value: "Discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(patchCv).not.toHaveBeenCalledWith("cv-1", { title: "Discarded" });
  });

  it("switches inspector tabs and shows the matching panel body", async () => {
    renderBuilder();
    expect(await screen.findByTestId("inspector-body-sections")).toBeInTheDocument();
    await openInspectorTab("context");
    expect(screen.getByTestId("inspector-body-context")).toBeInTheDocument();
    // The AI actions live in the toolbar cluster now — no AI tab.
    expect(screen.getByTestId("ai-toolbar-cluster")).toBeInTheDocument();
    expect(screen.getByTestId("ai-presets")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-body-ai")).not.toBeInTheDocument();
    // The lint report lives in the ATS chip popover — no lint tab.
    fireEvent.click(screen.getByTestId("ats-chip"));
    expect(await screen.findByTestId("lint-panel")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    // The inspector exposes exactly three tabs — no Lint/AI anywhere.
    const tablist = screen.getByRole("tablist", { name: "Inspector panels" });
    expect(within(tablist).getAllByRole("tab")).toHaveLength(3);
    expect(within(tablist).queryByRole("tab", { name: "Lint" })).not.toBeInTheDocument();
    expect(within(tablist).queryByRole("tab", { name: "AI" })).not.toBeInTheDocument();
  });

  it("toggles a whole context group with the tri-state header switch", async () => {
    previewCv.mockImplementation(async () => {
      const include = setContext.mock.calls.length
        ? setContext.mock.calls[setContext.mock.calls.length - 1][1].include
        : [
            { source_key: "experience", item_id: "exp-1" },
            { source_key: "skills", item_id: "sk-1" },
          ];
      const snapshotIndex: Record<string, string[]> = {};
      for (const entry of include) {
        (snapshotIndex[entry.source_key] ??= []).push(entry.item_id);
      }
      return {
        ...preview,
        resolution: { ...preview.resolution, snapshot_index: snapshotIndex },
      };
    });
    renderBuilder();
    await openInspectorTab("context");
    const groupToggle = await screen.findByRole("checkbox", {
      name: "Include all Skills",
    });
    fireEvent.click(groupToggle);
    await waitFor(() => expect(setContext).toHaveBeenCalled());
    expect(setContext.mock.calls[0][1].include).toEqual([
      { source_key: "experience", item_id: "exp-1" },
    ]);
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: "Include all Skills" }),
      ).not.toBeChecked(),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Include all Skills" }),
    );
    await waitFor(() => expect(setContext).toHaveBeenCalledTimes(2));
    expect(setContext.mock.calls[1][1].include).toEqual([
      { source_key: "experience", item_id: "exp-1" },
      { source_key: "skills", item_id: "sk-1" },
    ]);
  });

  it("summarizes coverage and per-group inclusion at a glance", async () => {
    renderBuilder();
    await openInspectorTab("context");
    await screen.findByTestId("context-summary");
    expect(screen.getByTestId("context-summary")).toHaveTextContent("2 / 2");
    expect(screen.getByTestId("context-group-count-skills")).toHaveTextContent(
      "1/1",
    );
    expect(screen.getByTestId("context-group-count-experience")).toHaveTextContent(
      "1/1",
    );
    // Empty groups surface their hint without needing to expand.
    expect(screen.getByText("Nothing recorded yet")).toBeInTheDocument();
  });

  it("filters context items through the search box", async () => {
    renderBuilder();
    await openInspectorTab("context");
    const search = await screen.findByTestId("context-search");
    fireEvent.change(search, { target: { value: "python" } });
    expect(screen.getByTestId("context-toggle-skills:sk-1")).toBeInTheDocument();
    expect(screen.queryByTestId("context-toggle-experience:exp-1")).not.toBeInTheDocument();
  });

  it("collapses and expands context groups from the header", async () => {
    renderBuilder();
    await openInspectorTab("context");
    const header = await screen.findByTestId("context-group-header-skills");
    const body = screen.getByTestId("context-group-body-skills");
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(body).toHaveAttribute("data-open", "true");
    fireEvent.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(body).toHaveAttribute("data-open", "false");
    fireEvent.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(body).toHaveAttribute("data-open", "true");
  });

  it("switches the mobile workspace pane", async () => {
    renderBuilder();
    expect(await screen.findByTestId("pane-switcher")).toBeInTheDocument();
    const inspectorBtn = screen.getByTestId("pane-inspector");
    expect(inspectorBtn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(inspectorBtn);
    expect(inspectorBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("pane-canvas"));
    expect(inspectorBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("unticking an item switches the context to custom include-list", async () => {
    renderBuilder();
    await openInspectorTab("context");
    const toggle = await screen.findByTestId("context-toggle-skills:sk-1");
    fireEvent.click(toggle);
    await waitFor(() => expect(setContext).toHaveBeenCalled());
    const [cvId, body] = setContext.mock.calls[0];
    expect(cvId).toBe("cv-1");
    expect(body.mode).toBe("custom");
    expect(body.include).toEqual([{ source_key: "experience", item_id: "exp-1" }]);
    await waitFor(() => expect(previewCv).toHaveBeenCalledTimes(2));
  });

  it("shows versions only in the popup opened from the toolbar", async () => {
    fetchVersions.mockResolvedValue([
      { id: "v1", version: 1, content: {}, context_resolution: {}, content_hash: "h", created_by: "user_save", created_at: "2026-09-04T10:00:00Z" },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    expect(screen.queryByTestId("versions-panel")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("open-versions"));
    expect(await screen.findByTestId("versions-panel")).toBeInTheDocument();
    expect(screen.getByTestId("version-row")).toHaveTextContent("v1");
  });

  it("saves a version and refreshes the list", async () => {
    fetchVersions
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { id: "v1", version: 1, content: {}, context_resolution: {}, content_hash: "h", created_by: "user_save", created_at: "2026-09-04T10:00:00Z" },
      ]);
    renderBuilder();
    fireEvent.click(await screen.findByTestId("save-version"));
    await waitFor(() => expect(compileCv).toHaveBeenCalledWith("cv-1"));
    fireEvent.click(await screen.findByTestId("open-versions"));
    await waitFor(() => expect(screen.getByTestId("version-row")).toBeInTheDocument());
  });

  it("picks a per-CV photo from the gallery with a live preview", async () => {
    renderBuilder();
    await openInspectorTab("design");
    const strip = await screen.findByTestId("photo-gallery-strip");
    expect(strip).toBeInTheDocument();
    await waitFor(() => expect(fetchPhotoBlobUrl).toHaveBeenCalledWith("photo-2"));
    fireEvent.click(screen.getByTestId("photo-choice-photo-2"));
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { photo_document_id: "photo-2" })
    );
  });

  it("uploads a photo from the Design tab and selects it for this CV", async () => {
    renderBuilder();
    await openInspectorTab("design");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["png"], "studio.png", { type: "image/png" })],
      },
    });
    await waitFor(() => expect(uploadGalleryPhoto).toHaveBeenCalledTimes(1));
    const file = uploadGalleryPhoto.mock.calls[0][0] as File;
    expect(file.name).toBe("studio.png");
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { photo_document_id: "photo-new" })
    );
    await waitFor(() => expect(fetchPhotoGallery).toHaveBeenCalledTimes(2));
  });

  it("returns the photo choice to the profile default", async () => {
    renderBuilder();
    await openInspectorTab("design");
    fireEvent.click(await screen.findByTestId("photo-choice-photo-2"));
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { photo_document_id: "photo-2" })
    );
    fireEvent.click(await screen.findByTestId("photo-use-default"));
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { photo_document_id: null })
    );
  });

  it("applies a template via the picker", async () => {
    renderBuilder();
    await openInspectorTab("design");
    const picker = await screen.findByTestId("template-picker");
    fireEvent.change(picker, { target: { value: "tpl-1" } });
    await waitFor(() => expect(patchCv).toHaveBeenCalledWith("cv-1", { template_id: "tpl-1" }));
  });

  it("browses templates in the builder and applies with a preview", async () => {
    renderBuilder();
    await openInspectorTab("design");
    fireEvent.click(await screen.findByTestId("browse-templates"));
    const card = await screen.findByTestId("template-card");
    expect(card).toHaveTextContent("Classic Serif");
    await waitFor(() =>
      expect(fetchTemplatePreview).toHaveBeenCalledWith("tpl-1")
    );
    fireEvent.click(screen.getByTestId("use-template-tpl-1"));
    await waitFor(() =>
      expect(patchCv).toHaveBeenCalledWith("cv-1", { template_id: "tpl-1" })
    );
  });

  it("previews an immutable version snapshot from the popup", async () => {
    fetchVersions.mockResolvedValue([
      { id: "v1", version: 1, content: {}, context_resolution: {}, content_hash: "h", created_by: "user_save", created_at: "2026-09-04T10:00:00Z" },
    ]);
    renderBuilder();
    fireEvent.click(await screen.findByTestId("open-versions"));
    fireEvent.click(await screen.findByTestId("preview-version-1"));
    await waitFor(() =>
      expect(fetchVersionPreview).toHaveBeenCalledWith("cv-1", 1)
    );
    const frame = await screen.findByTestId("version-preview-frame");
    expect(frame).toHaveAttribute("srcdoc", expect.stringContaining("v1 snapshot"));
    expect(restoreVersion).not.toHaveBeenCalled();
  });

  it("tails the CV against a saved posting via the tailor popover", async () => {
    const user = userEvent.setup();
    aiAction.mockResolvedValue({
      action: "tailor",
      notes: "",
      proposals: [],
      coverage: { covered: [], missing: [] },
      gaps: [],
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await user.click(screen.getByRole("button", { name: "More AI actions" }));
    await user.click(await screen.findByRole("menuitem", { name: /Tailor to saved posting/ }));
    const picker = await screen.findByTestId("tailor-picker");
    fireEvent.change(picker.querySelector("select")!, { target: { value: "post-1" } });
    fireEvent.click(screen.getByTestId("tailor-run"));
    await waitFor(() =>
      expect(aiAction).toHaveBeenCalledWith("cv-1", "tailor", {
        posting_id: "post-1",
      })
    );
  });

  it("opens the command palette with Ctrl+K and runs a command", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByTestId("command-palette")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("command-save-version"));
    await waitFor(() => expect(compileCv).toHaveBeenCalledWith("cv-1"));
  });

  it("sends tone/length presets and translate targets the CV language", async () => {
    const user = userEvent.setup();
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await user.click(screen.getByTestId("ai-presets"));
    fireEvent.change(await screen.findByTestId("tone-select"), {
      target: { value: "confident" },
    });
    fireEvent.change(screen.getByTestId("length-select"), {
      target: { value: "short" },
    });
    await user.click(screen.getByRole("button", { name: "More AI actions" }));
    await user.click(await screen.findByText("Translate → EN"));
    await waitFor(() =>
      expect(aiAction).toHaveBeenCalledWith(
        "cv-1",
        "translate",
        expect.objectContaining({ tone: "confident", length: "short" })
      )
    );
  });

  it("runs the summary action from the toolbar split-button and applies a proposal from the slide-over", async () => {
    renderBuilder();
    fireEvent.click(await screen.findByRole("button", { name: "Improve summary" }));
    const slideOver = await screen.findByTestId("proposals-slideover");
    const card = within(slideOver).getByTestId("proposal-card");
    expect(card).toHaveTextContent("Grounded summary draft");
    fireEvent.click(within(slideOver).getByTestId("apply-proposal"));
    await waitFor(() => expect(patchCv).toHaveBeenCalled());
    const [, body] = patchCv.mock.calls[0];
    expect(body.working_content.overrides["summary:summary"].summary).toBe(
      "Grounded summary draft"
    );
  });

  it("navigates slide-over proposals with arrow keys", async () => {
    aiAction.mockResolvedValue({
      action: "summary",
      notes: "",
      proposals: [
        {
          proposal: { field: "summary", text: "First draft", rationale: "", evidence_refs: [], ref: null },
          verified: true,
        },
        {
          proposal: { field: "summary", text: "Second draft", rationale: "", evidence_refs: [], ref: null },
          verified: true,
        },
      ],
      coverage: null,
      gaps: [],
    });
    renderBuilder();
    fireEvent.click(await screen.findByRole("button", { name: "Improve summary" }));
    const slideOver = await screen.findByTestId("proposals-slideover");
    const applyButtons = within(slideOver).getAllByTestId("apply-proposal");
    await waitFor(() => expect(applyButtons[0]).toHaveFocus());
    fireEvent.keyDown(slideOver, { key: "ArrowDown" });
    expect(applyButtons[1]).toHaveFocus();
    fireEvent.keyDown(slideOver, { key: "ArrowUp" });
    expect(applyButtons[0]).toHaveFocus();
  });
});

describe("CvBuilder — measured pages override the estimate", () => {
  it("prefers lint's measured page count over the renderer estimate", async () => {
    fetchLint.mockResolvedValue({
      ...lint,
      metrics: {
        ...lint.metrics,
        pages_actual: 2,
        pages_actual_over_budget: true,
      },
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const toolbar = await screen.findByTestId("builder-toolbar");
    await waitFor(() =>
      expect(toolbar.textContent).toMatch(/~2\/1 page/),
    );
  });
});

describe("builder: matching cover letter entry", () => {
  it("offers the dropdown item when a posting is attached and hands off creation", async () => {
    const user = userEvent.setup();
    createCoverLetter.mockResolvedValue({ id: "letter-1", kind: "cover_letter" });
    fetchCv.mockResolvedValue({ ...cv, target_posting_id: "posting-9" });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await user.click(screen.getByTestId("export-dropdown"));
    await user.click(await screen.findByTestId("create-matching-letter"));
    await waitFor(() =>
      expect(createCoverLetter).toHaveBeenCalledWith({
        posting_id: "posting-9",
        base_cv_id: "cv-1",
        title: "Matching cover letter — Backend Intern CV",
      })
    );
  });

  it("hides the entry when the CV has no posting attached", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("export-dropdown"));
    expect(screen.queryByTestId("create-matching-letter")).not.toBeInTheDocument();
  });
});

