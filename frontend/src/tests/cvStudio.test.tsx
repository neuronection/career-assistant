import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { CvStudio } from "@/pages/CvStudio";
import { CvBuilder } from "@/pages/CvBuilder";
import { CvTemplateEditor } from "@/pages/CvTemplateEditor";
import { useChatStore } from "@/stores/chatStore";

const fetchCvs = vi.fn();
const createCv = vi.fn();
const duplicateCv = vi.fn();
const deleteCv = vi.fn();
const fetchCv = vi.fn();
const fetchContextSources = vi.fn();
const previewCv = vi.fn();
const fetchVersions = vi.fn();
const fetchLint = vi.fn();
const fetchContextStatus = vi.fn();
const compileCv = vi.fn();
const patchCv = vi.fn();
const setContext = vi.fn();
const aiAction = vi.fn();
const exportCv = vi.fn();
const restoreVersion = vi.fn();
const fetchVersionPreview = vi.fn();
const fetchTemplates = vi.fn();
const fetchTemplatePreview = vi.fn();
const draftTemplateAi = vi.fn();
const fetchPhotoGallery = vi.fn();
const uploadGalleryPhoto = vi.fn();
const fetchPhotoBlobUrl = vi.fn();
const fetchThemes = vi.fn();
const createTemplate = vi.fn();
const publishTemplateVersion = vi.fn();
const previewTemplateDraft = vi.fn();
const createAssistantSession = vi.fn();
const fetchAssistantMessages = vi.fn();
const streamAssistantTurn = vi.fn();

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    createChatSession: (...args: unknown[]) => createAssistantSession(...args),
    fetchMessages: (...args: unknown[]) => fetchAssistantMessages(...args),
  };
});

vi.mock("@/api/chatStream", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/chatStream")>();
  return {
    ...mod,
    streamChatMessage: (...args: unknown[]) => streamAssistantTurn(...args),
  };
});

vi.mock("@/api/mePhoto", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/mePhoto")>();
  return {
    ...mod,
    fetchPhotoGallery: (...args: unknown[]) => fetchPhotoGallery(...args),
    uploadGalleryPhoto: (...args: unknown[]) => uploadGalleryPhoto(...args),
    fetchPhotoBlobUrl: (...args: unknown[]) => fetchPhotoBlobUrl(...args),
  };
});

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: vi.fn().mockResolvedValue({
      items: [
        { id: "post-1", ref: "abc", source_id: "s1", external_id: "e1", title: "Junior DevOps", org: "Acme", location: {}, url: "" },
      ],
      total: 1,
      unseen: 0,
    }),
  };
});

vi.mock("@/api/cvTemplates", () => ({
  fetchTemplates: (...args: unknown[]) => fetchTemplates(...args),
  fetchTemplatePreview: (...args: unknown[]) => fetchTemplatePreview(...args),
  draftTemplateAi: (...args: unknown[]) => draftTemplateAi(...args),
}));

vi.mock("@/api/cvTemplateDraft", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvTemplateDraft")>();
  return {
    ...mod,
    fetchThemes: (...args: unknown[]) => fetchThemes(...args),
    createTemplate: (...args: unknown[]) => createTemplate(...args),
    publishTemplateVersion: (...args: unknown[]) => publishTemplateVersion(...args),
    previewTemplateDraft: (...args: unknown[]) => previewTemplateDraft(...args),
  };
});

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchCvs: (...args: unknown[]) => fetchCvs(...args),
    createCv: (...args: unknown[]) => createCv(...args),
    duplicateCv: (...args: unknown[]) => duplicateCv(...args),
    deleteCv: (...args: unknown[]) => deleteCv(...args),
    fetchCv: (...args: unknown[]) => fetchCv(...args),
    fetchContextSources: (...args: unknown[]) => fetchContextSources(...args),
    previewCv: (...args: unknown[]) => previewCv(...args),
    fetchVersions: (...args: unknown[]) => fetchVersions(...args),
    fetchLint: (...args: unknown[]) => fetchLint(...args),
    fetchContextStatus: (...args: unknown[]) => fetchContextStatus(...args),
    compileCv: (...args: unknown[]) => compileCv(...args),
    patchCv: (...args: unknown[]) => patchCv(...args),
    setContext: (...args: unknown[]) => setContext(...args),
    aiAction: (...args: unknown[]) => aiAction(...args),
    exportCv: (...args: unknown[]) => exportCv(...args),
    restoreVersion: (...args: unknown[]) => restoreVersion(...args),
    fetchVersionPreview: (...args: unknown[]) => fetchVersionPreview(...args),
  };
});

const cv = {
  id: "cv-1",
  title: "Backend Intern CV",
  kind: "resume",
  target_posting_id: null,
  language: "en",
  page_size: "a4",
  max_pages: 1,
  status: "draft",
  working_content: {},
  context: { mode: "all", include: [], exclude: [] },
  source_document_id: null,
  created_at: "2026-09-04T10:00:00Z",
  updated_at: "2026-09-04T10:00:00Z",
  latest_version: null,
};

const sources = {
  sources: [
    {
      key: "experience",
      label: "Experience",
      description: "Roles",
      items: [
        { item_id: "exp-1", label: "DevOps intern", detail: "Acme" },
      ],
    },
    {
      key: "skills",
      label: "Skills",
      description: "Skills",
      items: [{ item_id: "sk-1", label: "Python", detail: "programming" }],
    },
  ],
};

const preview = {
  html: "<html><body><h1>Test Student</h1><h2>Experience</h2></body></html>",
  metrics: { estimated_pages: 1, lines_per_page: 40, overflow: false, empty_blocks: [] },
  blocks: [{ kind: "header" }, { kind: "summary" }],
  resolution: {
    snapshot: {},
    snapshot_index: { experience: ["exp-1"], skills: ["sk-1"] },
    items: [],
    resolved_at: "2026-09-04T10:00:00Z",
  },
};

const lint = {
  score: 92,
  passed: true,
  checks: [{ id: "section_order", level: "pass", message: "Section order matches reading order." }],
  metrics: {},
  resolved_items: 3,
};

function renderStudio() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv"]}>
        <Routes>
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

function renderEditor() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv/templates/tpl-1"]}>
        <Routes>
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

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

const template = {
  id: "tpl-1",
  key: "classic",
  version: 1,
  title: "Classic Serif",
  description: "Traditional serif layout",
  author_key: "bank",
  source: "bank",
  visibility: "private",
  language: "en",
  page_size: "a4",
  ats_safe: true,
  status: "active",
  content: {
    blocks: [{ kind: "header" }, { kind: "summary" }],
    design: {},
    pages: {},
    prompts: {},
  },
  content_hash: "h",
};

beforeEach(() => {
  vi.clearAllMocks();
  fetchCvs.mockResolvedValue([cv]);
  fetchTemplates.mockResolvedValue([template]);
  fetchPhotoGallery.mockResolvedValue([
    { document_id: "photo-1", filename: "me.png", created_at: "2026-09-04", is_default: true },
    { document_id: "photo-2", filename: "alt.png", created_at: "2026-09-04", is_default: false },
  ]);
  fetchPhotoBlobUrl.mockResolvedValue("blob:mock-photo");
  uploadGalleryPhoto.mockResolvedValue({
    document_id: "photo-new",
    filename: "studio.png",
    created_at: "2026-09-05",
    is_default: false,
  });
  fetchThemes.mockResolvedValue([
    {
      key: "teal_modern",
      label: "Teal Modern",
      description: "Clean sans",
      accent_color: "#0f766e",
      heading_color: "#134e4a",
      design: { accent_color: "#0f766e", header_style: "centered" },
    },
  ]);
  previewTemplateDraft.mockResolvedValue("<html><body>Preview</body></html>");
  publishTemplateVersion.mockResolvedValue({ ...template, version: 2 });
  createTemplate.mockResolvedValue({ ...template, id: "tpl-new", author_key: "u1" });
  fetchTemplatePreview.mockResolvedValue(
    "<html><body><h1>Sample</h1></body></html>"
  );
  draftTemplateAi.mockResolvedValue({ ...template, id: "tpl-2", title: "AI draft" });
  createCv.mockImplementation(async (body: { title: string }) => ({ ...cv, id: "cv-2", title: body.title }));
  duplicateCv.mockResolvedValue({ ...cv, id: "cv-3", title: "copy" });
  deleteCv.mockResolvedValue(undefined);
  fetchCv.mockResolvedValue(cv);
  fetchContextSources.mockResolvedValue(sources);
  previewCv.mockResolvedValue(preview);
  createAssistantSession.mockResolvedValue({ id: "s-assist", title: "CV assistant" });
  fetchAssistantMessages.mockResolvedValue([]);
  streamAssistantTurn.mockResolvedValue(undefined);
  fetchVersions.mockResolvedValue([]);
  fetchLint.mockResolvedValue(lint);
  fetchContextStatus.mockResolvedValue({ has_baseline: false, stale: false, changed: [], added: [], removed: [] });
  compileCv.mockResolvedValue({
    version: { id: "v1", version: 1, content: {}, context_resolution: {}, content_hash: "h", created_by: "user_save", created_at: "2026-09-04T10:00:00Z" },
    html: preview.html,
    metrics: preview.metrics,
  });
  patchCv.mockImplementation(async (_id: string, body: Record<string, unknown>) => ({
    ...cv,
    ...body,
  }));
  setContext.mockImplementation(async () => ({ ...cv }));
  previewCv.mockImplementation(async () => {
    const lastPatch = patchCv.mock.calls[patchCv.mock.calls.length - 1]?.[1] as
      | { working_content?: { blocks?: typeof preview.blocks } }
      | undefined;
    return { ...preview, blocks: lastPatch?.working_content?.blocks ?? preview.blocks };
  });
  aiAction.mockResolvedValue({
    action: "summary",
    notes: "",
    proposals: [
      {
        proposal: {
          field: "summary",
          text: "Grounded summary draft",
          rationale: "from evidence",
          evidence_refs: [{ source_key: "experience", item_id: "exp-1" }],
          ref: null,
        },
        verified: true,
      },
    ],
    coverage: null,
    gaps: [],
  });
  exportCv.mockResolvedValue(new Blob(["x"], { type: "text/markdown" }));
  restoreVersion.mockResolvedValue(cv);
  fetchVersionPreview.mockResolvedValue("<html><body>v1 snapshot</body></html>");
});

describe("CvStudio", () => {
  it("lists CVs and opens the create modal", async () => {
    renderStudio();
    expect(await screen.findByText("Backend Intern CV")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Design CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0].title).toBe("Design CV");
  });

  it("shows an error state when loading fails", async () => {
    fetchCvs.mockRejectedValue(new Error("boom"));
    renderStudio();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("asks for confirmation before deleting a CV", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId(`delete-cv-${cv.id}`));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Delete “Backend Intern CV”/);
    expect(deleteCv).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete CV" }));
    await waitFor(() => expect(deleteCv).toHaveBeenCalledWith("cv-1"));
  });

  it("gallery shows a grid-only picker with previews and per-card customize", async () => {
    fetchTemplates.mockResolvedValue([
      template,
      { ...template, id: "tpl-2", title: "Second Style" },
    ]);
    renderStudio();
    fireEvent.click(await screen.findByTestId("open-templates"));
    expect(await screen.findByTestId("gallery-grid")).toBeInTheDocument();
    expect(screen.queryByTestId("gallery-featured")).not.toBeInTheDocument();
    const cards = screen.getAllByTestId("template-card");
    expect(cards).toHaveLength(2);
    expect(screen.getByTestId("preview-template-tpl-2")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("edit-template-tpl-2"));
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Second Style"
    );
  });

  it("opens the gallery and creates a CV from a chosen template", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("open-templates"));
    const card = await screen.findByTestId("template-card");
    expect(card).toHaveTextContent("Classic Serif");
    await waitFor(() =>
      expect(fetchTemplatePreview).toHaveBeenCalledWith("tpl-1")
    );
    fireEvent.click(screen.getByTestId(`use-template-${template.id}`));
    expect(await screen.findByText(/New CV from “Classic Serif”/)).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Serif CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({
      title: "Serif CV",
      template_id: "tpl-1",
    });
  });

  it("drafts a template with AI from the gallery", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("open-templates"));
    fireEvent.change(await screen.findByTestId("template-brief"), {
      target: { value: "serif, teal accent" },
    });
    fireEvent.click(screen.getByText("Draft with AI"));
    await waitFor(() => expect(draftTemplateAi).toHaveBeenCalledWith("serif, teal accent"));
    expect(await screen.findByText("AI draft")).toBeInTheDocument();
  });
});

describe("CvTemplateEditor", () => {
  it("loads a bank template, applies a theme and saves as a copy", async () => {
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
    await waitFor(() => expect(previewTemplateDraft).toHaveBeenCalled());
    fireEvent.click(await screen.findByTestId("theme-teal_modern"));
    fireEvent.click(screen.getByTestId("save-template"));
    await waitFor(() => expect(createTemplate).toHaveBeenCalled());
    const body = createTemplate.mock.calls[0][0];
    expect(body.title).toContain("Classic Serif");
    expect(body.content.design.accent_color).toBe("#0f766e");
  });

  it("publishes a new version for an owned template", async () => {
    fetchTemplates.mockResolvedValue([
      { ...template, author_key: "user-1", source: "custom" },
    ]);
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
    fireEvent.click(await screen.findByTestId("save-template"));
    await waitFor(() =>
      expect(publishTemplateVersion).toHaveBeenCalledWith(
        "tpl-1",
        expect.objectContaining({ title: "Classic Serif" })
      )
    );
  });
});

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
        title: "CV assistant",
        context: { surface: "cv_builder", cv_id: "cv-1" },
      }),
    );
    await waitFor(() => expect(useChatStore.getState().chatMode).toBe("docked"));
    await waitFor(() => expect(useChatStore.getState().activeSessionId).toBe("s-assist"));
    expect(fetchAssistantMessages).toHaveBeenCalledWith("s-assist");
  });

  it("renders preview, lint score and context toggles", async () => {
    renderBuilder();
    expect(await screen.findByTestId("preview-frame")).toHaveAttribute("srcdoc", expect.stringContaining("Experience"));
    expect(await screen.findByText("ATS 92")).toBeInTheDocument();
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
    fireEvent.click(await screen.findByTestId("inspector-tab-sections"));
    const moveButtons = screen.getAllByLabelText("Move up");
    fireEvent.click(moveButtons[moveButtons.length - 1]);
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
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
    const removeButtons = screen.getAllByLabelText("Remove section");
    fireEvent.click(removeButtons[removeButtons.length - 1]);
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

  it("edits custom-text blocks with the markdown-lite toolbar", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-custom_text"));
    fireEvent.click(await screen.findByTestId("edit-custom-text"));
    const editor = (await screen.findByTestId("custom-text-editor")) as HTMLTextAreaElement;
    expect(editor).toHaveValue("");
    const setSelection = (start: number, end: number) => {
      editor.focus();
      editor.setSelectionRange(start, end);
    };

    fireEvent.change(editor, { target: { value: "Hello world" } });
    setSelection(0, 5);
    fireEvent.click(screen.getByTestId("md-tool-bold"));
    expect(editor).toHaveValue("**Hello** world");

    fireEvent.change(editor, { target: { value: "Hello world" } });
    setSelection(0, 5);
    fireEvent.click(screen.getByTestId("md-tool-italic"));
    expect(editor).toHaveValue("*Hello* world");

    fireEvent.change(editor, { target: { value: "Hello world" } });
    setSelection(0, 11);
    fireEvent.click(screen.getByTestId("md-tool-bullet"));
    expect(editor).toHaveValue("- Hello world");
    setSelection(0, 13);
    fireEvent.click(screen.getByTestId("md-tool-bullet"));
    expect(editor).toHaveValue("Hello world");

    fireEvent.change(editor, { target: { value: "Hello world" } });
    setSelection(0, 5);
    fireEvent.click(screen.getByTestId("md-tool-link"));
    expect(editor).toHaveValue("[Hello](https://) world");

    expect(screen.getByTestId("custom-text-counter")).toHaveTextContent(
      `${editor.value.length}/2000`
    );
    await waitFor(() => expect(patchCv).toHaveBeenCalled(), { timeout: 3000 });
  });

  it("autosaves custom-text edits into working_content", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-custom_text"));
    fireEvent.click(await screen.findByTestId("edit-custom-text"));
    const editor = await screen.findByTestId("custom-text-editor");
    fireEvent.change(editor, { target: { value: "Few words about me" } });
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(2), { timeout: 3000 });
    const blocks = patchCv.mock.calls[1][1].working_content.blocks;
    expect(blocks[blocks.length - 1].props.text).toBe("Few words about me");
  });

  it("adds sections from the card picker with previews", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
    const duplicates = screen.getAllByLabelText("Duplicate section");
    fireEvent.click(duplicates[1]);
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const blocks = patchCv.mock.calls[0][1].working_content.blocks;
    expect(blocks).toHaveLength(3);
    expect(blocks[2].kind).toBe("summary");
  });

  it("configures a section inline via stepper and toggle", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-sections"));
    const cards = await screen.findAllByTestId(/section-card-\d+/);
    fireEvent.dragStart(cards[1]);
    expect(cards[1]).toHaveClass("opacity-40");
    fireEvent.dragEnd(cards[1]);
    expect(cards[1]).not.toHaveClass("opacity-40");
  });

  it("opens the template style editor from the Design tab Customize button", async () => {
    renderBuilder();
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-design"));
    fireEvent.click(screen.getByTestId("browse-templates"));
    fireEvent.click(await screen.findByTestId("edit-template-tpl-1"));
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
  });

  it("renders the full-bleed workspace shell with toolbar, side rail and canvas", async () => {
    renderBuilder();
    expect(await screen.findByTestId("builder-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("builder-side")).toBeInTheDocument();
    expect(screen.getByTestId("builder-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("ats-chip")).toHaveTextContent("ATS 92");
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
    expect(await screen.findByTestId("inspector-body-design")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("inspector-tab-ai"));
    expect(screen.getByTestId("inspector-body-ai")).toBeInTheDocument();
    expect(screen.getByTestId("ai-presets")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("inspector-tab-lint"));
    expect(screen.getByTestId("lint-panel")).toBeInTheDocument();
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
    const groupToggle = await screen.findByTestId("context-group-toggle-skills");
    fireEvent.click(groupToggle);
    await waitFor(() => expect(setContext).toHaveBeenCalled());
    expect(setContext.mock.calls[0][1].include).toEqual([
      { source_key: "experience", item_id: "exp-1" },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("context-group-toggle-skills")).not.toBeChecked()
    );
    fireEvent.click(screen.getByTestId("context-group-toggle-skills"));
    await waitFor(() => expect(setContext).toHaveBeenCalledTimes(2));
    expect(setContext.mock.calls[1][1].include).toEqual([
      { source_key: "experience", item_id: "exp-1" },
      { source_key: "skills", item_id: "sk-1" },
    ]);
  });

  it("filters context items through the search box", async () => {
    renderBuilder();
    const search = await screen.findByTestId("context-search");
    fireEvent.change(search, { target: { value: "python" } });
    expect(screen.getByTestId("context-toggle-skills:sk-1")).toBeInTheDocument();
    expect(screen.queryByTestId("context-toggle-experience:exp-1")).not.toBeInTheDocument();
  });

  it("collapses and expands context groups from the header", async () => {
    renderBuilder();
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
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
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
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
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
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
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
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
    const picker = await screen.findByTestId("template-picker");
    fireEvent.change(picker, { target: { value: "tpl-1" } });
    await waitFor(() => expect(patchCv).toHaveBeenCalledWith("cv-1", { template_id: "tpl-1" }));
  });

  it("browses templates in the builder and applies with a preview", async () => {
    renderBuilder();
    fireEvent.click(await screen.findByTestId("inspector-tab-design"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-ai"));
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
    fireEvent.click(screen.getByTestId("inspector-tab-ai"));
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

  it("runs the summary action from the split-button and applies a proposal from the slide-over", async () => {
    renderBuilder();
    fireEvent.click(await screen.findByTestId("inspector-tab-ai"));
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
    fireEvent.click(await screen.findByTestId("inspector-tab-ai"));
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
