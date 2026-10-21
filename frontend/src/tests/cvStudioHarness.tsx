/**
 * Shared harness for the CV Studio surfaces (plan 124.3 test split).
 *
 * CV Studio, the builder and the template editor share one heavy mock set
 * (CV API, templates, photos, synth library, assistant chat). Keeping it in
 * one module lets each surface test file stay about its own assertions.
 *
 * Import this module FIRST in a surface test: its `vi.mock` calls must be
 * registered before the component modules load. Nothing here imports a
 * component for that reason.
 */

import { expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CvContextSelection } from "@/types/cv";

export const TAB_LABELS: Record<string, string> = {
  context: "Context",
  design: "Design",
  sections: "Sections",
};

export async function openInspectorTab(testid: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: TAB_LABELS[testid] }));
}

/**
 * Drive a library `RichTextEditor` from tests: jsdom typing doesn't
 * run through prosemirror's transaction pipeline (beforeinput is
 * unimplemented), so `userEvent.type` changes the DOM without emitting
 * markdown. The editor instance (via `onReady` → the component tree's
 * live editor) accepts commands; insertContent goes through the real
 * dispatch → `onValueChange` fires like a real keystroke burst.
 */
export async function typeIntoRichText(_container: HTMLElement, text: string) {
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


export const fetchCvs = vi.fn();
export const createCv = vi.fn();
export const duplicateCv = vi.fn();
export const deleteCv = vi.fn();
export const fetchCv = vi.fn();
export const fetchContextSources = vi.fn();
export const previewCv = vi.fn();
export const fetchVersions = vi.fn();
export const fetchLint = vi.fn();
export const fetchContextStatus = vi.fn();
export const compileCv = vi.fn();
export const patchCv = vi.fn();
export const setContext = vi.fn();
export const setSynthPin = vi.fn();
export const aiAction = vi.fn();
export const exportCv = vi.fn();
export const fetchExperienceRows = vi.fn();
export const createExperienceEntry = vi.fn();
export const updateExperienceEntry = vi.fn();
export const fetchOntology = vi.fn();
export const restoreVersion = vi.fn();
export const fetchVersionPreview = vi.fn();
export const fetchTemplates = vi.fn();
export const fetchTemplatePreview = vi.fn();
export const draftTemplateAi = vi.fn();
export const suggestTemplates = vi.fn();
export const fetchTemplateVersions = vi.fn();
export const fetchTemplateDiff = vi.fn();
export const fetchCvRuns = vi.fn();
export const fetchPhotoGallery = vi.fn();
export const uploadGalleryPhoto = vi.fn();
export const fetchPhotoBlobUrl = vi.fn();
export const fetchThemes = vi.fn();
export const createTemplate = vi.fn();
export const publishTemplateVersion = vi.fn();
export const previewTemplateDraft = vi.fn();
export const fetchCvDesign = vi.fn();
export const applyCvOps = vi.fn();
export const createCoverLetter = vi.fn();
export const createAssistantSession = vi.fn();
export const fetchAssistantMessages = vi.fn();
export const streamAssistantTurn = vi.fn();
export const fetchSynthItems = vi.fn();
export const refreshSynthSourceState = vi.fn();
export const generateSynthItems = vi.fn();
export const createSynthItem = vi.fn();
export const patchSynthItem = vi.fn();
export const deleteSynthItem = vi.fn();

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
    setSynthPin: (...args: unknown[]) => setSynthPin(...args),
    aiAction: (...args: unknown[]) => aiAction(...args),
    exportCv: (...args: unknown[]) => exportCv(...args),
    restoreVersion: (...args: unknown[]) => restoreVersion(...args),
    fetchVersionPreview: (...args: unknown[]) => fetchVersionPreview(...args),
    fetchCvRuns: (...args: unknown[]) => fetchCvRuns(...args),
    fetchSynthItems: (...args: unknown[]) => fetchSynthItems(...args),
    createSynthItem: (...args: unknown[]) => createSynthItem(...args),
    generateSynthItems: (...args: unknown[]) => generateSynthItems(...args),
    patchSynthItem: (...args: unknown[]) => patchSynthItem(...args),
    deleteSynthItem: (...args: unknown[]) => deleteSynthItem(...args),
    refreshSynthSourceState: (...args: unknown[]) =>
      refreshSynthSourceState(...args),
    fetchCvDesign: (...args: unknown[]) => fetchCvDesign(...args),
    applyCvOps: (...args: unknown[]) => applyCvOps(...args),
    createCoverLetter: (...args: unknown[]) => createCoverLetter(...args),
  };
});

vi.mock("@/api/experience", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/experience")>();
  return {
    ...mod,
    fetchExperience: (...args: unknown[]) => fetchExperienceRows(...args),
    fetchDerivation: vi.fn().mockResolvedValue({ skills: [], years_of_experience: 0 }),
    createExperienceItem: (...args: unknown[]) => createExperienceEntry(...args),
    updateExperienceItem: (...args: unknown[]) => updateExperienceEntry(...args),
  };
});

vi.mock("@/api/skills", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...mod,
    fetchSkillOntology: (...args: unknown[]) => fetchOntology(...args),
    fetchMySkills: vi.fn().mockResolvedValue([]),
  };
});

export const bulletsVariantRow = (id: string, texts: string[]) => ({
  id,
  scope: "bullets" as const,
  variant_key: "default",
  target_posting_id: null,
  source_refs: [{ source_key: "experience", item_id: "exp-1" }],
  source_state: [],
  payload: { achievements: texts.map((text) => ({ text })) },
  voice: { language: "en" },
  status: "active",
  source: "manual",
  verified: true,
  stale: false,
  orphaned: false,
  last_used_at: null,
  created_at: "",
});

export const cv = {
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

export const sources = {
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
    {
      key: "objective",
      label: "Objective",
      description: "Aspirations",
      items: [],
    },
  ],
};

export const preview = {
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

export const lint = {
  score: 92,
  passed: true,
  checks: [{ id: "section_order", level: "pass", message: "Section order matches reading order." }],
  metrics: {},
  resolved_items: 3,
};

export const template = {
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

export const sidebarTemplate = {
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


export async function resetCvStudioMocks() {
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
  setSynthPin.mockImplementation(
    async (
      _id: string,
      sourceKey: string,
      itemId: string,
      synthId: string | null,
    ) => {
      const key = `${sourceKey}:${itemId}`;
      const pins = {
        ...((cv.context?.synth_pins as Record<string, string>) ?? {}),
      };
      if (synthId) pins[key] = synthId;
      else delete pins[key];
      return { ...cv, context: { ...(cv.context ?? {}), synth_pins: pins } };
    },
  );
  fetchSynthItems.mockResolvedValue([]);
  previewCv.mockImplementation(async () => {
    const lastPatch = patchCv.mock.calls[patchCv.mock.calls.length - 1]?.[1] as
      | { working_content?: { blocks?: typeof preview.blocks } }
      | undefined;
    // The applied-variant truth follows the document's pins (like the real
    // backend), with the latest pin write overlaid.
    const synthApplied: Record<string, string> = {
      ...((cv.context?.synth_pins as Record<string, string>) ?? {}),
    };
    const lastPin = setSynthPin.mock.calls[setSynthPin.mock.calls.length - 1] as
      | [string, string, string, string | null]
      | undefined;
    if (lastPin) {
      const key = `${lastPin[1]}:${lastPin[2]}`;
      if (lastPin[3]) synthApplied[key] = lastPin[3];
      else delete synthApplied[key];
    }
    return {
      ...preview,
      blocks: lastPatch?.working_content?.blocks ?? preview.blocks,
      resolution: { ...preview.resolution, synth_applied: synthApplied },
    };
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
}
