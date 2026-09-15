import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { CvStudio } from "@/pages/CvStudio";
import { CvBuilder } from "@/pages/CvBuilder";
import { CvTemplateEditor } from "@/pages/CvTemplateEditor";
import { useChatStore } from "@/stores/chatStore";
import type { CvContextSelection } from "@/types/cv";

async function openInspectorTab(testid: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("inspector-tab-menu"));
  await user.click(screen.getByTestId(`inspector-tab-${testid}`));
}

/**
 * Drive a library `RichTextEditor` from tests: jsdom typing doesn't
 * run through prosemirror's transaction pipeline (beforeinput is
 * unimplemented), so `userEvent.type` changes the DOM without emitting
 * markdown. The editor instance (via `onReady` → the component tree's
 * live editor) accepts commands; insertContent goes through the real
 * dispatch → `onValueChange` fires like a real keystroke burst.
 */
async function typeIntoRichText(_container: HTMLElement, text: string) {
  const { act } = await import("@testing-library/react");
  const holders = [
    ...document.querySelectorAll<HTMLElement>("[data-rich-editor-holder]"),
  ];
  const holder = holders[holders.length - 1];
  expect(holder).toBeTruthy();
  const editor = (holder as unknown as { __editor?: unknown }).__editor;
  expect(editor).toBeTruthy();
  await act(async () => {
    (editor as { commands: { insertContent: (content: string) => boolean } }).commands.insertContent(text);
  });
}

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
const suggestTemplates = vi.fn();
const fetchTemplateVersions = vi.fn();
const fetchTemplateDiff = vi.fn();
const fetchCvRuns = vi.fn();
const fetchPhotoGallery = vi.fn();
const uploadGalleryPhoto = vi.fn();
const fetchPhotoBlobUrl = vi.fn();
const fetchThemes = vi.fn();
const createTemplate = vi.fn();
const publishTemplateVersion = vi.fn();
const previewTemplateDraft = vi.fn();
const fetchCvDesign = vi.fn();
const applyCvOps = vi.fn();
const createCoverLetter = vi.fn();
const createAssistantSession = vi.fn();
const fetchAssistantMessages = vi.fn();
const streamAssistantTurn = vi.fn();
const fetchSynthItems = vi.fn();
const createSynthItem = vi.fn();
const patchSynthItem = vi.fn();

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

vi.mock("@/api/cvIntake", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvIntake")>();
  return {
    ...mod,
    listCvDraftHistory: vi.fn<typeof mod.listCvDraftHistory>(),
  };
});

vi.mock("@/api/cvTemplates", () => ({
  fetchTemplates: (...args: unknown[]) => fetchTemplates(...args),
  fetchTemplatePreview: (...args: unknown[]) => fetchTemplatePreview(...args),
  draftTemplateAi: (...args: unknown[]) => draftTemplateAi(...args),
  suggestTemplates: (...args: unknown[]) => suggestTemplates(...args),
  fetchTemplateVersions: (...args: unknown[]) => fetchTemplateVersions(...args),
  fetchTemplateDiff: (...args: unknown[]) => fetchTemplateDiff(...args),
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
    fetchCvRuns: (...args: unknown[]) => fetchCvRuns(...args),
    fetchSynthItems: (...args: unknown[]) => fetchSynthItems(...args),
    createSynthItem: (...args: unknown[]) => createSynthItem(...args),
    patchSynthItem: (...args: unknown[]) => patchSynthItem(...args),
    fetchCvDesign: (...args: unknown[]) => fetchCvDesign(...args),
    applyCvOps: (...args: unknown[]) => applyCvOps(...args),
    createCoverLetter: (...args: unknown[]) => createCoverLetter(...args),
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
  context: { mode: "all", include: [], exclude: [] } as CvContextSelection,
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
          <Route path="/profile/import" element={<div data-testid="import-dest" />} />
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
  version: 1,  title: "Classic Serif",
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

const sidebarTemplate = {
  ...template,
  key: "navy-sidebar",
  title: "Navy Sidebar",
  content: {
    ...template.content,
    blocks: [
      { kind: "header" },
      { kind: "summary", area: "sidebar", column: "sidebar" },
    ],
    design: { layout: "sidebar", sidebar_side: "left" },
  },
};

beforeEach(async () => {
  vi.clearAllMocks();
  vi.mocked(
    (await import("@/api/cvIntake")).listCvDraftHistory
  ).mockResolvedValue([]);
  fetchCvs.mockResolvedValue([cv]);
  fetchTemplates.mockResolvedValue([template]);
  suggestTemplates.mockResolvedValue({
    picks: [{ template_id: "tpl-1", title: "Classic Serif", reason: "ATS-safe serif" }],
    candidates_considered: 6,
  });
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
  fetchCvDesign.mockResolvedValue({
    design: {
      accent_color: "#1d4ed8",
      text_color: "#111827",
      muted_color: "#6b7280",
      heading_color: "#0f172a",
      background_color: "#ffffff",
      font_stack: "sans",
      base_size_pt: 10,
      line_height: 1.35,
      spacing_scale: 1,
      header_style: "left",
      show_photo: false,
      density: "normal",
      margin_mm: null,
      section_style: "flat",
      corner_radius: 0,
      heading_case: "uppercase",
      heading_weight: 600,
      heading_rule: "line",
      show_icons: true,
      icon_size_mm: 3.2,
      photo_shape: "circle",
      photo_size_mm: 22,
      section_gap_mm: null,
      item_gap_mm: null,
      border_color: "#e5e7eb",
      layout: "single",
      sidebar_side: "left",
      sidebar_color: "#16324f",
      sidebar_text_color: "#ffffff",
      sidebar_width_pct: 34,
      main_padding_mm: null,
      sidebar_padding_mm: null,
    },
    template: { id: "tpl-1", title: "Classic Serif", owned: false, ats_safe: true },
  });
  applyCvOps.mockImplementation(async (_id: string, ops: { op: string; design?: Record<string, unknown> }[]) => {
    const patch = ops[0]?.design ?? {};
    return {
      results: ops.map((op) => ({ op: op.op, ok: true, detail: "design updated" })),
      state: {
        document: { ...cv, template_id: "tpl-copy-1" },
        blocks: preview.blocks,
        overrides: {},
        html: "<html>restyled</html>",
        metrics: preview.metrics,
        resolution: { snapshot_index: {} },
        operations: [],
        critique: null,
        version: 2,
        design: {
          ...{
            accent_color: "#1d4ed8",
            text_color: "#111827",
            muted_color: "#6b7280",
            heading_color: "#0f172a",
            background_color: "#ffffff",
            font_stack: "sans",
            base_size_pt: 10,
            line_height: 1.35,
            spacing_scale: 1,
            header_style: "left",
            show_photo: false,
            density: "normal",
            margin_mm: null,
            section_style: "flat",
            corner_radius: 0,
            heading_case: "uppercase",
            heading_weight: 600,
            heading_rule: "line",
            show_icons: true,
            icon_size_mm: 3.2,
            photo_shape: "circle",
            photo_size_mm: 22,
            section_gap_mm: null,
            item_gap_mm: null,
            border_color: "#e5e7eb",
            layout: "single",
            sidebar_side: "left",
            sidebar_color: "#16324f",
            sidebar_text_color: "#ffffff",
            sidebar_width_pct: 34,
            main_padding_mm: null,
            sidebar_padding_mm: null,
          },
          ...patch,
        },
      },
    };
  });
  createAssistantSession.mockResolvedValue({ id: "s-assist", title: "CV assistant" });
  fetchAssistantMessages.mockResolvedValue([]);
  streamAssistantTurn.mockResolvedValue(undefined);
  fetchVersions.mockResolvedValue([]);
  fetchCvRuns.mockResolvedValue([]);
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
  fetchSynthItems.mockResolvedValue([]);
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
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
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

  it("picks a template with AI inside the new-CV form", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("ask-ai-choose"));
    const tile = await screen.findByTestId("use-suggestion-tpl-1");
    expect(tile).toHaveTextContent("Classic Serif");
    expect(tile.parentElement).toHaveTextContent("ATS-safe serif");
    fireEvent.click(tile);
    await waitFor(() =>
      expect(screen.getByTestId("new-cv-template-section")).toHaveTextContent(
        "Classic Serif"
      )
    );
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "AI CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({
      title: "AI CV",
      template_id: "tpl-1",
    });
  });

  it("creates a CV with no template chosen (studio default)", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("new-cv-template-section"));
    expect(screen.getByTestId("no-template-note")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Plain CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({ title: "Plain CV" });
  });

  it("opens the gallery and creates a CV from a chosen template", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
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
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
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

  it("hosts the context panel as the inspector's first tab", async () => {
    renderBuilder();
    expect(await screen.findByTestId("builder-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("inspector-body-context")).toBeInTheDocument();
    expect(
      screen.getByTestId("context-group-toggle-skills"),
    ).toBeInTheDocument();
    await openInspectorTab("design");
    expect(screen.getByTestId("inspector-body-design")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-body-context")).toBeNull();
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
    expect(await screen.findByTestId("inspector-body-context")).toBeInTheDocument();
    await openInspectorTab("design");
    expect(screen.getByTestId("inspector-body-design")).toBeInTheDocument();
    // The AI actions live in the toolbar cluster now — no AI tab.
    expect(screen.getByTestId("ai-toolbar-cluster")).toBeInTheDocument();
    expect(screen.getByTestId("ai-presets")).toBeInTheDocument();
    expect(screen.queryByTestId("inspector-body-ai")).not.toBeInTheDocument();
    // The lint report lives in the ATS chip popover — no lint tab.
    fireEvent.click(screen.getByTestId("ats-chip"));
    expect(await screen.findByTestId("lint-panel")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    const user = userEvent.setup();
    await user.click(screen.getByTestId("inspector-tab-menu"));
    const inspectorMenu = await screen.findByRole("menu");
    expect(within(inspectorMenu).queryByText("Lint")).not.toBeInTheDocument();
    expect(within(inspectorMenu).queryByText("AI")).not.toBeInTheDocument();
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

describe("CvStudio — import bridging", () => {
  it("the New CV modal offers an Import-from-CV mode that routes to the workspace", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("new-cv"));
    fireEvent.click(await screen.findByRole("button", { name: "Import from CV" }));
    fireEvent.click(await screen.findByTestId("import-cv-go"));
    expect(await screen.findByTestId("import-dest")).toBeInTheDocument();
  });

  it("shows the imported source CVs panel with status chips", async () => {
    const { listCvDraftHistory } = await import("@/api/cvIntake");
    vi.mocked(listCvDraftHistory).mockResolvedValue([
      {
        document_id: "doc-9",
        status: "applied",
        updated_at: "2026-09-09T09:00:00Z",
        report: { created: { skills: 2 } },
        document: {
          id: "doc-9",
          filename: "imported-cv.pdf",
          mime: "application/pdf",
          size_bytes: 1024,
          page_count: 1,
          status: "ready",
          error: "",
          created_at: "2026-09-09T09:00:00Z",
        },
      },
    ]);
    renderStudio();
    const panel = await screen.findByTestId("cvstudio-imports-panel");
    expect(panel).toHaveTextContent("imported-cv.pdf");
    expect(panel).toHaveTextContent("Imported");
    expect(
      screen.getByTestId("cvstudio-import-doc-9")
    ).toHaveAttribute("href", "/profile/import/doc-9");
  });
});

describe("CvTemplateEditor — plan 70 area paddings", () => {
  it("exposes main/sidebar padding controls for sidebar layouts and round-trips them", async () => {
    fetchTemplates.mockResolvedValue([sidebarTemplate]);
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Navy Sidebar"
    );
    const controls = await screen.findByTestId("sidebar-controls");
    expect(within(controls).getByText("Main column padding")).toBeInTheDocument();
    expect(within(controls).getByText("Sidebar padding")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("save-template"));
    await waitFor(() => expect(createTemplate).toHaveBeenCalled());
    const body = createTemplate.mock.calls[0][0];
    expect(body.content.design).toHaveProperty("main_padding_mm");
    expect(body.content.design).toHaveProperty("sidebar_padding_mm");
  });
});

describe("CvBuilder — plan 70 items kinds filter", () => {
  it("toggles experience kinds on an items section and saves the filter", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const group = await screen.findByRole("group", { name: "Include kinds" });
    fireEvent.click(within(group).getByRole("button", { name: "Jobs" }));
    await waitFor(
      () => {
        const blocks =
          patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
            .blocks;
        expect(blocks[blocks.length - 1].props.kinds).toEqual(["job"]);
      },
      { timeout: 3000 }
    );
  });
});

describe("CvBuilder — plan 85 consolidated Design tab", () => {
  it("renders the merged Design tab with template card, tokens and photo", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("design");
    const body = await screen.findByTestId("inspector-body-design");
    expect(within(body).getByTestId("design-token-editor")).toBeInTheDocument();
    expect(within(body).getByTestId("template-meta")).toHaveTextContent(
      "Classic Serif"
    );
    expect(within(body).getByTestId("template-picker")).toBeInTheDocument();
    expect(within(body).getByTestId("browse-templates")).toBeInTheDocument();
    expect(within(body).getByTestId("photo-picker-card")).toBeInTheDocument();
    expect(within(body).getByTestId("apply-design")).toBeDisabled();
    // The action footer is pinned outside the scrollable body.
    const scroll = within(body).getByTestId("design-scroll");
    expect(scroll).not.toContainElement(within(body).getByTestId("design-footer"));
    expect(within(body).getByTestId("design-footer")).toContainElement(
      within(body).getByTestId("apply-design")
    );
    await userEvent.click(screen.getByTestId("inspector-tab-menu"));
    const menu = await screen.findByRole("menu");
    expect(within(menu).queryByText("Template")).not.toBeInTheDocument();
  });

  it("applies a design change through the ops endpoint and re-syncs", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("design");
    const body = await screen.findByTestId("inspector-body-design");
    fireEvent.change(within(body).getByLabelText("Accent"), {
      target: { value: "#b91c1c" },
    });
    expect(within(body).getByTestId("apply-design")).toBeEnabled();
    fireEvent.click(within(body).getByTestId("apply-design"));
    await waitFor(() => expect(applyCvOps).toHaveBeenCalledTimes(1));
    const [cvId, ops] = applyCvOps.mock.calls[0];
    expect(cvId).toBe("cv-1");
    expect(ops[0].op).toBe("update_design");
    expect(ops[0].design.accent_color).toBe("#b91c1c");
    expect(await screen.findByTestId("preview-frame")).toBeInTheDocument();
  });
});

describe("CvBuilder — plan 71 container styling", () => {
  it("configures a block container in the builder sections panel", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-skills"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const container = await screen.findByTestId("container-2");
    fireEvent.change(within(container).getByLabelText("Container"), {
      target: { value: "card" },
    });
    await waitFor(
      () => {
        const blocks =
          patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
            .blocks;
        expect(blocks[blocks.length - 1].props.container.container).toBe("card");
      },
      { timeout: 3000 }
    );
  });
});

describe("CvBuilder — plan 71 critique card", () => {
  it("renders the copilot critique with one-click fixes", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    act(() => {
      useCvBuilderLink.setState({
        lastBuilderState: {
          document: { id: "cv-1", title: "T", kind: "resume", language: "en", page_size: "a4", max_pages: 1, status: "draft", template_id: null, photo_document_id: null },
          blocks: preview.blocks,
          overrides: {},
          html: preview.html,
          metrics: preview.metrics,
          resolution: { snapshot_index: {} },
          operations: [],
          critique: {
            summary: "Layout is close to budget",
            issues: [{ severity: "major", area: "page_budget", message: "Content renders on 2 pages but the budget is 1." }],
            safe_token_fixes: { base_size_pt: "9.5" },
          },
          version: 1,
        },
      });
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const canvas = screen.getByTestId("builder-canvas");
    const card = await within(canvas).findByTestId("critique-card");
    expect(within(card).getByTestId("critique-issue-0")).toHaveTextContent("page_budget");
    applyCvOps.mockResolvedValueOnce({
      results: [{ op: "update_design", ok: true, detail: "ok" }],
      state: {
        document: { id: "cv-1" },
        blocks: preview.blocks,
        overrides: {},
        html: "<html>fixed</html>",
        metrics: preview.metrics,
        resolution: { snapshot_index: {} },
        operations: [],
        critique: null,
        version: 2,
      },
    });
    fireEvent.click(within(card).getByTestId("apply-critique-fixes"));
    await waitFor(() => expect(applyCvOps).toHaveBeenCalledTimes(1));
    expect(applyCvOps.mock.calls[0][1][0].design).toEqual({ base_size_pt: "9.5" });
  });
});

describe("CvBuilder — plan 72 synth highlights + item ordering", () => {
  it("adds the Custom highlights section from the add-section card", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-synth_items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const [, body] = patchCv.mock.calls[0];
    const added = body.working_content.blocks[body.working_content.blocks.length - 1];
    expect(added.kind).toBe("synth_items");
    expect(added.props.title).toBe("Highlights");
    expect(added.props.show_source_chips).toBe(true);
  });

  it("configs a synth_items block and round-trips its props", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Tailored text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: true,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-synth_items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const chips = await screen.findByRole("button", {
      name: /Tailored text \(changed\)/,
    });
    fireEvent.click(chips);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.selected).toEqual(["syn-1"]);
    });
    fireEvent.click(screen.getByTestId("stepper-max-items").children[2]);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.max_items).toBe(7);
    });
    const chipsToggle = screen.getByTestId("toggle-show-source-chips") as HTMLInputElement;
    expect(chipsToggle.checked).toBe(true);
    fireEvent.click(chipsToggle);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.show_source_chips).toBe(false);
    });
  });

  it("reorders items in an items block and persists the full order array", async () => {
    const richPreview = {
      ...preview,
      resolution: {
        ...preview.resolution,
        snapshot: {
          experience: [
            { id: "exp-1", title: "Older Role" },
            { id: "exp-2", title: "Newer Role" },
          ],
        },
        snapshot_index: { ...preview.resolution.snapshot_index, experience: ["exp-1", "exp-2"] },
      },
    };
    previewCv.mockImplementation(async () => {
      const lastPatch = patchCv.mock.calls[patchCv.mock.calls.length - 1]?.[1] as
        | { working_content?: { blocks?: typeof richPreview.blocks } }
        | undefined;
      return {
        ...richPreview,
        blocks: lastPatch?.working_content?.blocks ?? richPreview.blocks,
      };
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    fireEvent.click(await screen.findByTestId("items-order-toggle"));
    await screen.findByTestId("items-order-list");
    fireEvent.click(screen.getByTestId("items-order-up-exp-2"));
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      const itemsBlock = blocks.find(
        (block: { kind: string }) => block.kind === "items"
      );
      expect(itemsBlock.props.order).toEqual(["exp-2", "exp-1"]);
    });
  });

  it("renders active variants nested under their items, cross-listed per ref", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [
          { source_key: "experience", item_id: "exp-1" },
          { source_key: "skills", item_id: "sk-1" },
        ],
        source_state: [],
        payload: { description: "Cross-listed text" },
        voice: { language: "en" },
        status: "active",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(screen.getByTestId("context-group-header-skills"));
    expect(
      await screen.findAllByTestId("context-variant-syn-1"),
    ).toHaveLength(2);
    expect(screen.queryByTestId("context-variant-toggle-syn-1")).toBeNull(),
      void screen.queryByTestId("context-variant-toggle-syn-1");
  });

  it("flags a pin whose variant is not active (plan 83 follow-up)", async () => {
    cv.context = {
      mode: "all",
      include: [],
      exclude: [],
      synth_pins: { "experience:exp-1": "syn-gone" },
    };
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Active text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(await screen.findByTestId("context-pin-inactive")).toBeInTheDocument();
    cv.context = { mode: "all", include: [], exclude: [] };
  });

  it("pins a variant per item with the star and persists synth_pins", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Pinned text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    setContext.mockImplementation(async () => ({ ...cv }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    const star = await screen.findByTestId("context-pin-star-syn-1");
    expect(star.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(star);
    await waitFor(() =>
      expect(setContext).toHaveBeenCalledWith(
        "cv-1",
        expect.objectContaining({
          synth_pins: { "experience:exp-1": "syn-1" },
        }),
      ),
    );
    const starred = await screen.findByTestId("context-pin-star-syn-1");
    expect(starred.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(starred);
    await waitFor(() => expect(setContext).toHaveBeenCalledTimes(2));
    expect(setContext.mock.calls[1][1].synth_pins).toEqual({});
  });

  it("shows an edit button on variant rows that opens the editor", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Nested under its item" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("context-variant-edit-syn-1"));
    const text = await screen.findByTestId("synth-editor-description-input");
    await typeIntoRichText(text, "Nested under its item");
    await waitFor(() =>
      expect(
        (text.querySelector(".ProseMirror") as HTMLElement | null)?.textContent,
      ).toContain("Nested under its item"),
    );
  });

  it("finds variants nested under their own item row, not the group bottom", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Cross-listed text" },
        voice: { language: "en" },
        status: "draft",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(await screen.findByTestId("context-variant-syn-1")).toBeTruthy();
  });

  it("opens the variant editor from the context panel add-variant button", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("ai-add-variant-exp-1"));
    expect(
      await screen.findByTestId("synth-editor-description-input"),
    ).toBeInTheDocument();
  });

  it("marks draft variants in the tree and activates them inline", async () => {
    const draft = {
      id: "syn-1",
      scope: "item",
      variant_key: "tailored",
      target_posting_id: null,
      source_refs: [{ source_key: "experience", item_id: "exp-1" }],
      source_state: [],
      payload: { description: "Drafted by the polish run" },
      voice: { language: "en" },
      status: "draft",
      source: "ai",
      verified: true,
      stale: false,
      orphaned: false,
      last_used_at: null,
      created_at: "",
    };
    fetchSynthItems.mockResolvedValue([draft]);
    patchSynthItem.mockImplementation(async () => ({
      ...draft,
      status: "active",
    }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(await screen.findByTestId("context-variant-draft")).toBeTruthy();
    fireEvent.click(await screen.findByTestId("context-variant-activate-syn-1"));
    await waitFor(() =>
      expect(patchSynthItem).toHaveBeenCalledWith("syn-1", { status: "active" }),
    );
    await waitFor(() => expect(fetchSynthItems.mock.calls.length).toBe(2));
    expect(screen.getByTestId("undo-notice-host")).toBeTruthy();
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

describe("template editor: version history + diff", () => {
  it("lists versions and renders the deterministic token/block diff", async () => {
    fetchTemplateVersions.mockResolvedValue([
      { id: "tpl-2", version: 2, title: "Classic Serif", created_at: "2026-09-15T10:00:00Z", content_hash: "h2" },
      { id: "tpl-1", version: 1, title: "Classic Serif", created_at: "2026-09-14T10:00:00Z", content_hash: "h1" },
    ]);
    fetchTemplateDiff.mockResolvedValue({
      from_version: 1,
      to_version: 2,
      token_changes: [
        { path: "design.accent_color", from: "#1d4ed8", to: "#0f766e" },
      ],
      block_changes: {
        added: ["interests:"],
        removed: [],
        props_changed: [],
      },
    });
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue("Classic Serif");
    fireEvent.click(screen.getByTestId("template-history-toggle"));
    expect(await screen.findByTestId("template-history-v2")).toBeInTheDocument();
    const diff = await screen.findByTestId("template-history-diff");
    expect(diff).toHaveTextContent("Changes v1 → v2");
    expect(diff).toHaveTextContent("design.accent_color");
    expect(diff).toHaveTextContent("#1d4ed8 → #0f766e");
    expect(diff).toHaveTextContent("+ interests:");
  });
});
