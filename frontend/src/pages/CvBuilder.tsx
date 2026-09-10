import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Eye, FileText, Sparkles } from "lucide-react";
import { Button, EmptyState, Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { UndoNotice } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";
import {
  aiAction,
  compileCv,
  draftCoverLetter,
  duplicateCv,
  exportCv,
  fetchContextSources,
  fetchContextStatus,
  fetchCoverLetterBrief,
  fetchCv,
  fetchVersionPreview,
  fetchLint,
  fetchVersions,
  patchCv,
  previewCv,
  restoreVersion,
  setContext,
} from "@/api/cv";
import { useToastStore } from "@/stores/toastStore";
import { fetchTemplates } from "@/api/cvTemplates";
import { fetchPostings } from "@/api/postings";
import { fetchPhotoGallery, uploadGalleryPhoto, type GalleryPhoto } from "@/api/mePhoto";
import { BuilderToolbar, EXPORT_FORMATS, type ExportFormat } from "@/components/cv/BuilderToolbar";
import { openCvChat } from "@/components/chat/cvChatLink";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import type { CvAssistantState } from "@/types/cvAssistant";
import { BLOCK_TYPES } from "@/components/cv/blockTypes";
import { ContextPanel } from "@/components/cv/ContextPanel";
import { InspectorPanel, type InspectorTab } from "@/components/cv/InspectorPanel";
import { PreviewCanvas } from "@/components/cv/PreviewCanvas";
import { TemplateGallery } from "@/components/cv/TemplateGallery";
import { CommandPalette, type CommandItem } from "@/components/cv/CommandPalette";
import { GenerateCvModal } from "@/components/cv/GenerateCvModal";
import { LetterBriefPanel } from "@/components/cv/LetterBriefPanel";
import { letterPropsOf } from "@/components/cv/LetterSectionsEditor";
import type { CvTemplateSummary } from "@/types/cvTemplate";
import type {
  CoverLetterBriefOut,
  CoverLetterSuggestionOut,
  CvBlock,
  CvContextSourceOut,
  CvDocumentOut,
  CvLintReport,
  CvProposal,
  CvRenderMetrics,
  CvSuggestionOut,
  CvVersionOut,
} from "@/types/cv";
function refKey(sourceKey: string, itemId: string): string {
  return `${sourceKey}:${itemId}`;
}

export function CvBuilder() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const pushToast = useToastStore((state) => state.push);
  const [cv, setCv] = useState<CvDocumentOut | null>(null);
  const [sources, setSources] = useState<CvContextSourceOut[]>([]);
  const [templates, setTemplates] = useState<CvTemplateSummary[]>([]);
  const [savedPostings, setSavedPostings] = useState<{ id: string; title: string; org: string }[]>([]);
  const [photos, setPhotos] = useState<GalleryPhoto[]>([]);
  const [tailorPostingId, setTailorPostingId] = useState("");
  const [html, setHtml] = useState("");
  const [metrics, setMetrics] = useState<CvRenderMetrics>({});
  const [blocks, setBlocks] = useState<CvBlock[]>([]);
  const [overrides, setOverrides] = useState<Record<string, Record<string, string>>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [versions, setVersions] = useState<CvVersionOut[]>([]);
  const [lint, setLint] = useState<CvLintReport | null>(null);
  const [suggestion, setSuggestion] = useState<CvSuggestionOut | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [tone, setTone] = useState("");
  const [length, setLength] = useState("");
  const [versionPreview, setVersionPreview] = useState<{ version: number; html: string } | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("design");
  const [activePane, setActivePane] = useState<"context" | "canvas" | "inspector">("canvas");
  const [previewLoading, setPreviewLoading] = useState(true);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [history, setHistory] = useState<{
    past: { blocks: CvBlock[]; overrides: Record<string, Record<string, string>> }[];
    future: { blocks: CvBlock[]; overrides: Record<string, Record<string, string>> }[];
  }>({ past: [], future: [] });
  const [notice, setNotice] = useState<string | null>(null);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [versionDiff, setVersionDiff] = useState<{
    version: number;
    newHtml: string;
    oldHtml: string;
  } | null>(null);
  const [brief, setBrief] = useState<CoverLetterBriefOut | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [letterSuggestion, setLetterSuggestion] =
    useState<CoverLetterSuggestionOut | null>(null);
  const [aiDraft, setAiDraft] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const isLetter = cv?.kind === "cover_letter";
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragIndex = useRef<number | null>(null);
  const undoRef = useRef<() => void>(() => {});
  const redoRef = useRef<() => void>(() => {});
  undoRef.current = undo;
  redoRef.current = redo;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redoRef.current();
        else undoRef.current();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redoRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const refreshPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const result = await previewCv(id);
      setHtml(result.html);
      setMetrics(result.metrics);
      setBlocks(result.blocks ?? []);
      const next = new Set<string>();
      for (const [key, ids] of Object.entries(result.resolution.snapshot_index)) {
        for (const itemId of ids) next.add(refKey(key, itemId));
      }
      setSelected(next);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setPreviewLoading(false);
    }
  }, [id]);

  const refreshMeta = useCallback(async () => {
    try {
      const [rows, report, status] = await Promise.all([
        fetchVersions(id),
        fetchLint(id),
        fetchContextStatus(id),
      ]);
      setVersions(rows);
      setLint(report);
      if (status.stale) {
        pushToast({
          title: t("cvBuilder.profileChangedTitle"),
          body: t("cvBuilder.profileChangedBody"),
          severity: "info",
          link: "",
        });
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  }, [id, pushToast]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [document, context, templateList, postings, photos] = await Promise.all([
          fetchCv(id),
          fetchContextSources(),
          fetchTemplates().catch(() => []),
          fetchPostings({ saved: true }).catch(() => ({ items: [] })),
          fetchPhotoGallery().catch(() => []),
        ]);
        if (cancelled) return;
        setCv(document);
        setSources(context.sources);
        setTemplates(templateList);
        setSavedPostings(
          postings.items.map((row) => ({
            id: String(row.id),
            title: row.title,
            org: row.org,
          }))
        );
        setPhotos(photos);
        setOverrides(document.working_content.overrides ?? {});
        setAiDraft(document.working_content?.generated_by === "cv_draft");
        setLoaded(true);
        await refreshPreview();
        await refreshMeta();
      } catch (err) {
        if (!cancelled) {
          setError(apiDetail(err));
          setLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, refreshPreview, refreshMeta]);

  const persistWorking = useCallback(
    (next: { blocks: CvBlock[]; overrides: Record<string, Record<string, string>> }, immediate = false) => {
      setHistory((h) => ({
        past: [...h.past.slice(-19), { blocks, overrides }],
        future: [],
      }));
      setBlocks(next.blocks);
      setOverrides(next.overrides);
      if (saveTimer.current) clearTimeout(saveTimer.current);
      const run = async () => {
        try {
          setSaveState("saving");
          await patchCv(id, { working_content: { blocks: next.blocks, overrides: next.overrides } });
          await refreshPreview();
          setSaveState("saved");
        } catch (err) {
          setSaveState("error");
          setError(apiDetail(err));
        }
      };
      if (immediate) void run();
      else saveTimer.current = setTimeout(run, 500);
    },
    [id, refreshPreview, blocks, overrides]
  );

  const commitWorking = useCallback(
    async (snapshot: { blocks: CvBlock[]; overrides: Record<string, Record<string, string>> }) => {
      setBlocks(snapshot.blocks);
      setOverrides(snapshot.overrides);
      try {
        setSaveState("saving");
        await patchCv(id, { working_content: snapshot });
        await refreshPreview();
        setSaveState("saved");
      } catch (err) {
        setSaveState("error");
        setError(apiDetail(err));
      }
    },
    [id, refreshPreview]
  );

  function undo() {
    const previous = history.past[history.past.length - 1];
    if (!previous) return;
    setHistory((h) => ({
      past: h.past.slice(0, -1),
      future: [...h.future, { blocks, overrides }],
    }));
    setNotice(null);
    void commitWorking(previous);
  }

  function redo() {
    const next = history.future[history.future.length - 1];
    if (!next) return;
    setHistory((h) => ({
      past: [...h.past, { blocks, overrides }],
      future: h.future.slice(0, -1),
    }));
    void commitWorking(next);
  }

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  const commitContext = useCallback(
    async (next: Set<string>) => {
      const include = [...next].map((value) => {
        const [source, item] = value.split(":");
        return { source_key: source, item_id: item };
      });
      try {
        await setContext(id, { mode: "custom", include, exclude: [] });
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id, refreshPreview]
  );

  const flushPendingSave = useCallback(async () => {
    if (!saveTimer.current) return;
    clearTimeout(saveTimer.current);
    saveTimer.current = null;
    try {
      setSaveState("saving");
      await patchCv(id, { working_content: { blocks, overrides } });
      setSaveState("saved");
    } catch (err) {
      setSaveState("error");
      setError(apiDetail(err));
    }
  }, [id, blocks, overrides]);

  const applyAssistantState = useCallback(
    (state: CvAssistantState) => {
      setCv((prev) => (prev ? ({ ...prev, ...state.document } as CvDocumentOut) : prev));
      setBlocks(state.blocks ?? []);
      setOverrides(state.overrides ?? {});
      setHtml(state.html);
      setMetrics(state.metrics);
      const next = new Set<string>();
      for (const [key, ids] of Object.entries(state.resolution?.snapshot_index ?? {})) {
        for (const itemId of ids) next.add(refKey(key, itemId));
      }
      setSelected(next);
      void refreshMeta();
    },
    [refreshMeta]
  );

  const lastBuilderState = useCvBuilderLink((state) => state.lastBuilderState);
  useEffect(() => {
    if (lastBuilderState) {
      applyAssistantState(lastBuilderState);
    }
  }, [lastBuilderState, applyAssistantState]);

  useEffect(() => {
    useCvBuilderLink.getState().registerFlush(() => void flushPendingSave());
    return () => useCvBuilderLink.getState().registerFlush(null);
  }, [flushPendingSave]);

  function toggleItem(sourceKey: string, itemId: string) {
    const key = refKey(sourceKey, itemId);
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
    void commitContext(next);
  }

  function toggleGroup(source: CvContextSourceOut, includeAll: boolean) {
    const next = new Set(selected);
    for (const item of source.items ?? []) {
      const key = refKey(source.key, item.item_id);
      if (includeAll) next.add(key);
      else next.delete(key);
    }
    setSelected(next);
    void commitContext(next);
  }

  useEffect(() => {
    if (cv?.kind !== "cover_letter" || !cv.target_posting_id) {
      setBrief(null);
      return;
    }
    let cancelled = false;
    setBriefLoading(true);
    fetchCoverLetterBrief(cv.target_posting_id)
      .then((result) => {
        if (!cancelled) setBrief(result);
      })
      .catch(() => {
        if (!cancelled) setBrief(null);
      })
      .finally(() => {
        if (!cancelled) setBriefLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cv?.kind, cv?.target_posting_id]);

  async function runLetterDraft() {
    setBusy("ai:cover_letter");
    setError("");
    try {
      const body: Record<string, unknown> = {};
      if (tone) body.tone = tone;
      if (length) body.length = length;
      setLetterSuggestion(await draftCoverLetter(id, body));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy("");
    }
  }

  const applyLetterDraft = useCallback(
    async (paragraphs: string[], draft: CoverLetterSuggestionOut["draft"]) => {
      const current = letterPropsOf(blocks);
      const letterBlock: CvBlock = {
        kind: "letter",
        props: {
          ...(current?.props ?? {}),
          salutation: draft.salutation || current?.props.salutation || "Dear Hiring Team,",
          closing: draft.closing || current?.props.closing || "Sincerely,",
          ...(draft.subject ? { subject: draft.subject } : {}),
          paragraphs,
        },
      };
      let next: CvBlock[];
      if (current) {
        next = blocks.map((block, position) =>
          position === current.index ? letterBlock : block
        );
      } else {
        next = [...blocks, letterBlock];
      }
      setLetterSuggestion(null);
      setNotice(t("cvBuilder.draftApplied"));
      persistWorking({ blocks: next, overrides }, true);
    },
    [blocks, overrides, persistWorking]
  );

  function handleTailorRequest() {
    if (!tailorPostingId) return;
    void runAction("tailor", { posting_id: tailorPostingId });
  }

  function moveBlock(index: number, delta: number) {
    const next = [...blocks];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    persistWorking({ blocks: next, overrides }, true);
  }

  function removeBlock(index: number) {
    const next = blocks.filter((_, position) => position !== index);
    setNotice(t("cvBuilder.sectionRemoved"));
    persistWorking({ blocks: next, overrides }, true);
  }

  function addBlock(kind: string) {
    const props = { ...(BLOCK_TYPES.find((type) => type.value === kind)?.props ?? {}) };
    const next = [...blocks, { kind, props }];
    persistWorking({ blocks: next, overrides }, true);
  }

  function duplicateBlock(index: number) {
    const source = blocks[index];
    if (!source) return;
    const copy: CvBlock = {
      kind: source.kind,
      props: JSON.parse(JSON.stringify(source.props ?? {})) as Record<string, unknown>,
    };
    const next = [...blocks];
    next.splice(index + 1, 0, copy);
    setNotice(t("cvBuilder.sectionDuplicated"));
    persistWorking({ blocks: next, overrides }, true);
  }

  function updateBlockProps(index: number, patch: Record<string, unknown>) {
    const next = blocks.map((block, position) =>
      position === index ? { ...block, props: { ...block.props, ...patch } } : block
    );
    persistWorking({ blocks: next, overrides });
  }

  const applyPhoto = useCallback(
    async (photoDocumentId: string) => {
      setError("");
      try {
        const updated = await patchCv(id, {
          photo_document_id: photoDocumentId || null,
        });
        setCv(updated);
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id, refreshPreview]
  );

  const handlePhotoUpload = useCallback(
    async (file: File) => {
      setError("");
      setPhotoUploading(true);
      try {
        const photo = await uploadGalleryPhoto(file);
        setPhotos(await fetchPhotoGallery());
        pushToast({
          title: t("cvBuilder.photoUploaded"),
          body: t("cvBuilder.photoUploadedBody", { filename: photo.filename }),
          severity: "success",
          link: "",
        });
        await applyPhoto(photo.document_id);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setPhotoUploading(false);
      }
    },
    [applyPhoto, pushToast]
  );

  const applyTemplate = useCallback(
    async (templateId: string) => {
      setError("");
      try {
        const updated = await patchCv(id, {
          template_id: templateId || null,
        });
        setCv(updated);
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id, refreshPreview]
  );

  const renameCv = useCallback(
    async (title: string) => {
      setError("");
      try {
        const updated = await patchCv(id, { title });
        setCv(updated);
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id]
  );

  async function saveVersion() {
    setBusy("save");
    setError("");
    try {
      const result = await compileCv(id);
      await refreshMeta();
      setBusy("");
      setMetrics(result.metrics);
      pushToast({
        title: t("cvBuilder.versionSaved"),
        body: t("cvBuilder.versionSavedBody", { version: result.version.version }),
        severity: "success",
        link: "",
      });
    } catch (err) {
      setError(apiDetail(err));
      setBusy("");
    }
  }

  async function applyOverridePatch(target: Record<string, Record<string, string>>) {
    persistWorking({ blocks, overrides: { ...overrides, ...target } }, true);
  }

  async function applyProposal(entry: CvProposal) {
    const field = entry.field ?? "description";
    const key = entry.ref ? refKey(entry.ref.source_key, entry.ref.item_id) : "summary:summary";
    setNotice(t("cvBuilder.proposalApplied"));
    await applyOverridePatch({ [key]: { ...overrides[key], [field]: entry.text } });
    setSuggestion(null);
  }

  async function runAction(
    action: "summary" | "bullet" | "gaps" | "compaction" | "tailor" | "translate",
    ref?: { source_key?: string; item_id?: string; text?: string; posting_id?: string }
  ) {
    setBusy(`ai:${action}`);
    setError("");
    try {
      const body: Record<string, unknown> = { ...(ref ?? {}) };
      if (tone) body.tone = tone;
      if (length) body.length = length;
      const result = await aiAction(
        id,
        action,
        action === "gaps" ? (ref ?? {}) : body
      );
      setSuggestion(result);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy("");
    }
  }

  async function handleDuplicate() {
    setError("");
    try {
      const copy = await duplicateCv(id);
      window.location.assign(`/cv/${copy.id}`);
    } catch (err) {
      setError(apiDetail(err));
    }
  }

  async function handleExport(format: ExportFormat) {
    setBusy(`export:${format}`);
    setError("");
    try {
      const blob = await exportCv(id, format);
      const url = URL.createObjectURL(blob);
      if (format === "pdf") {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${cv?.title ?? "cv"}.pdf`;
        anchor.click();
        URL.revokeObjectURL(url);
        await refreshMeta();
      } else {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${cv?.title ?? "cv"}.${format === "ats_text" ? "txt" : format}`;
        anchor.click();
      }
      URL.revokeObjectURL(url);
      await refreshMeta();
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (format === "pdf" && status === 503) {
        try {
          const result = await previewCv(id);
          const url = URL.createObjectURL(
            new Blob([result.html], { type: "text/html" })
          );
          window.open(url, "_blank");
          pushToast({
            title: t("cvBuilder.serverPdfUnavailable"),
            body: t("cvBuilder.printViewBody"),
            severity: "info",
            link: "",
          });
        } catch {
          setError(apiDetail(err));
        }
      } else {
        setError(apiDetail(err));
      }
    } finally {
      setBusy("");
    }
  }

  const overflow = metrics.overflow === true;
  const pages = metrics.estimated_pages ?? 1;
  const maxPages = cv?.max_pages ?? 1;
  const currentLetter = isLetter ? letterPropsOf(blocks) : null;

  if (!loaded) {
    return (
      <div className="p-6 text-sm text-[var(--as-muted-fg)]">
        {t("templateEditor.loadingEditor")}
      </div>
    );
  }
  if (!cv) {
    return (
      <div className="p-6">
        <EmptyState icon={FileText} title={t("cvBuilder.notFound")} description={error || t("cvBuilder.maybeDeleted")} />
      </div>
    );
  }

  const commands: CommandItem[] = [
    { id: "save-version", label: t("templateEditor.saveVersion"), hint: "Ctrl+S", run: () => void saveVersion() },
    { id: "open-versions", label: t("cvBuilder.showVersions"), run: () => setVersionsOpen(true) },
    { id: "browse-templates", label: t("cvBuilder.browseTemplates"), run: () => setGalleryOpen(true) },
    { id: "ask-ai", label: t("cvBuilder.askAssistant"), run: () => void openCvChat(id, "docked") },
    ...(isLetter
      ? [{ id: "ai-letter", label: t("cvBuilder.aiDraftLetter"), run: () => void runLetterDraft() }]
      : [
          { id: "ai-summary", label: t("cvBuilder.aiImproveSummary"), run: () => void runAction("summary") },
          { id: "ai-compaction", label: t("cvBuilder.aiTightenText"), run: () => void runAction("compaction") },
          { id: "ai-gaps", label: t("cvBuilder.aiFindGaps"), run: () => void runAction("gaps") },
          {
            id: "ai-translate",
            label: t("cvBuilder.aiTranslateTo", { lang: cv?.language?.toUpperCase() ?? "" }),
            run: () => void runAction("translate"),
          },
        ]),
    ...EXPORT_FORMATS.map((format) => ({
      id: `export-${format}`,
      label: t("cvBuilder.exportFormat", { format: format === "ats_text" ? "ATS text" : format.toUpperCase() }),
      run: () => void handleExport(format),
    })),
  ];

  return (
    <div className="flex min-h-0 flex-col gap-3 lg:h-full" data-testid="cv-builder">
      <BuilderToolbar
        title={cv.title}
        onRename={(title) => void renameCv(title)}
        versions={versions}
        lint={lint}
        pages={pages}
        maxPages={maxPages}
        overflow={overflow}
        saveState={saveState}
        saveBusy={busy === "save"}
        exportBusy={busy.startsWith("export:") ? busy.slice("export:".length) : ""}
        canUndo={history.past.length > 0}
        canRedo={history.future.length > 0}
        onSaveVersion={() => void saveVersion()}
        onExport={(format) => void handleExport(format)}
        onOpenVersions={() => setVersionsOpen(true)}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenAssistant={() => void openCvChat(id, "docked")}
        onUndo={undo}
        onRedo={redo}
      />

      {error && (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {aiDraft && !isLetter && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)] p-3 text-sm"
          data-testid="ai-draft-banner"
        >
          <Sparkles className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
          <span className="min-w-0 flex-1 text-[var(--as-fg)]">{t("cvBuilder.aiDraftBanner")}</span>
          <Button variant="outline" size="sm" onClick={() => setGenerateOpen(true)} data-testid="regenerate-cv">
            {t("cvBuilder.regenerate")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setAiDraft(false)} data-testid="dismiss-ai-draft">
            {t("common.hide")}
          </Button>
        </div>
      )}

      <div className="mb-2 flex shrink-0 gap-1 lg:hidden" role="group" aria-label={t("experience.panesAria")} data-testid="pane-switcher">
        {(
          [
            ["context", t("cvBuilder.pane.context")],
            ["canvas", t("cvBuilder.pane.preview")],
            ["inspector", t("cvBuilder.pane.inspector")],
          ] as const
        ).map(
          ([paneId, label]) => (
            <button
              key={paneId}
              type="button"
              aria-pressed={activePane === paneId}
              onClick={() => setActivePane(paneId)}
              data-testid={`pane-${paneId}`}
              className={`flex-1 rounded-lg border border-[var(--as-border)] px-2 py-1.5 text-xs font-medium transition-colors duration-150 ${
                activePane === paneId
                  ? "bg-[var(--as-surface-raised)] text-[var(--as-fg)]"
                  : "bg-[var(--as-surface)] text-[var(--as-muted-fg)]"
              }`}
            >
              {label}
            </button>
          )
        )}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(230px,280px)_minmax(0,1fr)_minmax(290px,340px)] lg:gap-4">
        <div
          className={`${
            activePane === "context" ? "flex" : "hidden"
          } cv-pane-enter min-h-0 flex-col rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-2.5 lg:flex`}
          data-testid="builder-side"
        >
          {isLetter ? (
            <LetterBriefPanel brief={brief} loading={briefLoading} />
          ) : (
            <ContextPanel
              sources={sources ?? []}
              selected={selected}
              onToggle={toggleItem}
              onToggleGroup={(source, includeAll) => void toggleGroup(source, includeAll)}
              onBullet={(sourceKey, itemId) => void runAction("bullet", { source_key: sourceKey, item_id: itemId })}
            />
          )}
        </div>

        <div
          className={`${
            activePane === "canvas" ? "flex" : "hidden"
          } cv-pane-enter min-h-0 flex-col lg:flex`}
          data-testid="builder-canvas"
        >
          <PreviewCanvas html={html} loading={previewLoading} pageSize={cv?.page_size} />
        </div>

        <div
          className={`${
            activePane === "inspector" ? "flex" : "hidden"
          } cv-pane-enter min-h-0 flex-col rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-2.5 lg:flex`}
          data-testid="builder-inspector"
        >
          <InspectorPanel
            tab={inspectorTab}
            onTabChange={setInspectorTab}
            mode={isLetter ? "cover_letter" : "resume"}
            letterProps={currentLetter?.props ?? null}
            onUpdateLetterProps={(patch) => {
              if (currentLetter) updateBlockProps(currentLetter.index, patch);
            }}
            letterSuggestion={letterSuggestion}
            onCloseLetterSuggestion={() => setLetterSuggestion(null)}
            onApplyLetterDraft={(paragraphs, draft) =>
              void applyLetterDraft(paragraphs, draft)
            }
            onDraftLetter={() => void runLetterDraft()}
            hasTargetPosting={Boolean(cv.target_posting_id)}
            templates={templates}
            templateId={cv.template_id ?? ""}
            onTemplate={(templateId) => void applyTemplate(templateId)}
            onBrowseTemplates={() => setGalleryOpen(true)}
            onCustomizeTemplate={() => {
              if (cv.template_id) navigate(`/cv/templates/${cv.template_id}`);
            }}
            photos={photos}
            photoId={cv.photo_document_id ?? ""}
            onPhoto={(photoId) => void applyPhoto(photoId)}
            photoUploading={photoUploading}
            onUploadPhoto={(file) => void handlePhotoUpload(file)}
            onError={setError}
            blocks={blocks}
            onAddBlock={addBlock}
            onMoveBlock={moveBlock}
            onDuplicateBlock={duplicateBlock}
            onRemoveBlock={removeBlock}
            onUpdateBlockProps={updateBlockProps}
            dragIndexRef={dragIndex}
            onDragReorder={(target) => {
              if (dragIndex.current !== null) moveBlock(dragIndex.current, target);
              dragIndex.current = null;
            }}
            busy={busy}
            tone={tone}
            onToneChange={setTone}
            length={length}
            onLengthChange={setLength}
            savedPostings={savedPostings}
            tailorPostingId={tailorPostingId}
            onTailorPostingChange={setTailorPostingId}
            onTailorRequest={handleTailorRequest}
            translateLabel={`Translate → ${cv.language.toUpperCase()}`}
            onRunAction={(action) => void runAction(action)}
            onDuplicate={() => void handleDuplicate()}
            suggestion={suggestion}
            onCloseSuggestion={() => setSuggestion(null)}
            onApplyProposal={(entry) => void applyProposal(entry)}
            lint={lint}
          />
        </div>
      </div>

      {notice && (
        <div
          className="fixed bottom-6 left-6 z-[var(--as-z-modal)]"
          data-testid="undo-notice-host"
        >
          <UndoNotice
            message={notice}
            actionLabel={t("common.undo")}
            onUndo={() => {
              setNotice(null);
              undo();
            }}
            onDismiss={() => setNotice(null)}
            duration={6000}
          />
        </div>
      )}

      <Modal open={versionsOpen} onOpenChange={(open) => !open && setVersionsOpen(false)}>
        <ModalContent size="md" aria-describedby={undefined}>
          <ModalHeader>
            <ModalTitle>{t("cvBuilder.versions")}</ModalTitle>
          </ModalHeader>
          <div className="max-h-[65vh] overflow-y-auto p-4 pt-0" data-testid="versions-panel">

            {versions.length === 0 ? (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("cvBuilder.versionsEmpty")}
              </p>
            ) : (
              <ul className="space-y-1">
                {versions.map((version, position) => (
                  <li key={version.id} className="flex items-center gap-2 text-sm" data-testid="version-row">
                    <span className="flex-1">
                      v{version.version} · {version.created_by} ·{" "}
                      {new Date(version.created_at).toLocaleString()}
                    </span>
                    {position + 1 < versions.length && (
                      <Button
                        variant="outline"
                        data-testid={`diff-version-${version.version}`}
                        onClick={async () => {
                          const previous = versions[position + 1];
                          setBusy(`diff:${version.version}`);
                          try {
                            const [newHtml, oldHtml] = await Promise.all([
                              fetchVersionPreview(id, version.version),
                              fetchVersionPreview(id, previous.version),
                            ]);
                            setVersionDiff({
                              version: version.version,
                              newHtml,
                              oldHtml,
                            });
                          } catch (err) {
                            setError(apiDetail(err));
                          } finally {
                            setBusy("");
                          }
                        }}
                      >
                        {t("cvBuilder.diffVersion", { version: version.version })}
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      data-testid={`preview-version-${version.version}`}
                      onClick={async () => {
                        setBusy(`preview:${version.version}`);
                        try {
                          const html = await fetchVersionPreview(id, version.version);
                          setVersionPreview({ version: version.version, html });
                        } catch (err) {
                          setError(apiDetail(err));
                        } finally {
                          setBusy("");
                        }
                      }}
                    >
                      <Eye className="mr-1 h-3 w-3" /> {t("cvBuilder.preview")}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={async () => {
                        const document = await restoreVersion(id, version.version);
                        setBlocks(document.working_content.blocks ?? []);
                        setOverrides(document.working_content.overrides ?? {});
                        setVersionsOpen(false);
                        await refreshPreview();
                      }}
                    >
                      {t("cvBuilder.restore")}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
                    </div>
        </ModalContent>
      </Modal>


      <Modal
        open={versionPreview !== null}
        onOpenChange={(open) => !open && setVersionPreview(null)}
      >
        <ModalContent
          size="xl"
          className="w-[92vw] max-w-[min(1100px,92vw)]"
          aria-describedby={undefined}
        >
          <ModalHeader>
            <div className="flex w-full items-center justify-between pr-6">
              <ModalTitle>
                {t("cvBuilder.previewVersion", { version: versionPreview?.version })}
              </ModalTitle>
              <Button
                variant="outline"
                data-testid="restore-from-preview"
                onClick={async () => {
                  if (!versionPreview) return;
                  const document = await restoreVersion(id, versionPreview.version);
                  setBlocks(document.working_content.blocks ?? []);
                  setOverrides(document.working_content.overrides ?? {});
                  setVersionPreview(null);
                  setVersionsOpen(false);
                  await refreshPreview();
                }}
              >
                {t("cvBuilder.restoreThisVersion")}
              </Button>
            </div>
          </ModalHeader>
          <div className="p-4 pt-0">
            <iframe
              title={t("cvBuilder.previewVersionTitle", { version: versionPreview?.version })}
              srcDoc={versionPreview?.html ?? ""}
              sandbox=""
              className="h-[70vh] w-full rounded border bg-white"
              data-testid="version-preview-frame"
            />
          </div>
        </ModalContent>
      </Modal>

            <Modal
        open={versionDiff !== null}
        onOpenChange={(open) => !open && setVersionDiff(null)}
      >
        <ModalContent
          size="xl"
          className="w-[92vw] max-w-[min(1100px,92vw)]"
          aria-describedby={undefined}
        >
          <ModalHeader>
            <ModalTitle>
              {t("cvBuilder.compareVersions", {
                newVersion: versionDiff?.version,
                oldVersion: (versionDiff?.version ?? 1) - 1,
              })}
            </ModalTitle>
          </ModalHeader>
          <div
            className="grid grid-cols-1 gap-4 p-4 pt-0 sm:grid-cols-2"
            data-testid="version-diff-panel"
          >
            <figure className="space-y-1.5">
              <figcaption className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("cvBuilder.diffCurrent", { version: versionDiff?.version })}
              </figcaption>
              <div className="h-80 overflow-hidden rounded-lg border border-[var(--as-border)] bg-white">
                <iframe
                  title={t("cvBuilder.versionThumbnail", { version: versionDiff?.version })}
                  srcDoc={versionDiff?.newHtml ?? ""}
                  sandbox=""
                  className="h-[720px] w-[720px] origin-top-left scale-[0.45] border-0"
                  data-testid="version-diff-frame-new"
                />
              </div>
            </figure>
            <figure className="space-y-1.5">
              <figcaption className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("cvBuilder.diffPrevious", { version: (versionDiff?.version ?? 1) - 1 })}
              </figcaption>
              <div className="h-80 overflow-hidden rounded-lg border border-[var(--as-border)] bg-white">
                <iframe
                  title={t("cvBuilder.versionThumbnail", { version: (versionDiff?.version ?? 1) - 1 })}
                  srcDoc={versionDiff?.oldHtml ?? ""}
                  sandbox=""
                  className="h-[720px] w-[720px] origin-top-left scale-[0.45] border-0"
                  data-testid="version-diff-frame-old"
                />
              </div>
            </figure>
          </div>
          <div className="flex justify-end gap-2 px-4 pb-4">
            <Button
              variant="outline"
              data-testid="restore-from-diff"
              onClick={async () => {
                if (!versionDiff) return;
                const document = await restoreVersion(id, versionDiff.version);
                setBlocks(document.working_content.blocks ?? []);
                setOverrides(document.working_content.overrides ?? {});
                setVersionDiff(null);
                setVersionsOpen(false);
                await refreshPreview();
              }}
            >
              {t("cvBuilder.restoreVersion", { version: versionDiff?.version })}
            </Button>
          </div>
        </ModalContent>
      </Modal>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
      />

      <TemplateGallery
        open={galleryOpen}
        onClose={() => setGalleryOpen(false)}
        actionLabel={t("cvBuilder.applyToCv")}
        currentTemplateId={cv.template_id}
        onUse={(template) => void applyTemplate(template.id)}
      />

      <GenerateCvModal open={generateOpen} onOpenChange={setGenerateOpen} />
    </div>
  );
}
