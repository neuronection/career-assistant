import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Copy, Eye, FileText, Sparkles, X } from "lucide-react";
import { Button, EmptyState, Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { UndoNotice } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";
import type { VariantGenerateRequest } from "@/components/cv/VariantEditor";
import {
  aiAction,
  compileCv,
  createCoverLetter,
  createSynthItem,
  draftCoverLetter,
  duplicateCv,
  exportCv,
  fetchContextSources,
  fetchContextStatus,
  fetchCoverLetterBrief,
  fetchCv,
  fetchCvDesign,
  fetchSynthItems,
  generateSynthItems,
  fetchVersionPreview,
  fetchLint,
  fetchVersions,
  applyCvOps,
  patchCv,
  patchSynthItem,
  previewCv,
  refreshSynthSourceState,
  restoreVersion,
  setContext,
} from "@/api/cv";
import { useToastStore } from "@/stores/toastStore";
import { fetchTemplates } from "@/api/cvTemplates";
import { fetchPostings } from "@/api/postings";
import { fetchPhotoGallery, uploadGalleryPhoto, type GalleryPhoto } from "@/api/mePhoto";
import { BuilderToolbar, EXPORT_FORMATS, type ExportFormat } from "@/components/cv/BuilderToolbar";
import { BuildProgressCard } from "@/components/cv/BuildProgress";
import { RunsPanelModal } from "@/components/cv/RunsPanel";
import { AiToolbarCluster } from "@/components/cv/AiToolbarCluster";
import { CritiqueCard } from "@/components/cv/CritiqueCard";
import { openCvChat } from "@/components/chat/cvChatLink";
import { useCvBuilderLink } from "@/stores/cvBuilderLinkStore";
import type { CvAssistantCritique, CvAssistantState } from "@/types/cvAssistant";
import { BLOCK_TYPES } from "@/components/cv/blockTypes";
import { ContextPanel } from "@/components/cv/ContextPanel";
import { EntityEditorModal } from "@/components/profile/EntityEditorModal";
import { ItemBulletsEditorModal } from "@/components/cv/ItemBulletsEditorModal";
import { VariantEditor, type VariantEditorBody } from "@/components/cv/VariantEditor";
import { InspectorPanel, type InspectorTab } from "@/components/cv/InspectorPanel";
import { PreviewCanvas } from "@/components/cv/PreviewCanvas";
import { TemplateGallery } from "@/components/cv/TemplateGallery";
import { CommandPalette, type CommandItem } from "@/components/cv/CommandPalette";
import { GenerateCvModal } from "@/components/cv/GenerateCvModal";
import { LetterBriefPanel } from "@/components/cv/LetterBriefPanel";
import { letterPropsOf } from "@/components/cv/LetterSectionsEditor";
import { areaOf, areasForDesign, type CvArea } from "@/components/cv/areas";
import type { CvTemplateSummary } from "@/types/cvTemplate";
import type { CvDesignTokens } from "@/types/cvTemplate";
import type {
  CoverLetterBriefOut,
  CoverLetterSuggestionOut,
  CvBlock,
  CvContextSourceOut,
  CvDocumentOut,
  CvLintReport,
  CvOverridePatch,
  CvProposal,
  CvRenderMetrics,
  CvSuggestionOut,
  CvSynthBullet,
  CvSynthItem,
  CvVersionOut,
} from "@/types/cv";
function refKey(sourceKey: string, itemId: string): string {
  return `${sourceKey}:${itemId}`;
}

function toBackendLength(length?: string): "short" | "medium" | "long" {
  if (length === "concise") return "short";
  if (length === "detailed") return "long";
  return "medium";
}

function usableVariants(items: CvSynthItem[]): CvSynthItem[] {
  return items.filter((item) => item.status !== "archived");
}

export function CvBuilder() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const pushToast = useToastStore((state) => state.push);
  const [cv, setCv] = useState<CvDocumentOut | null>(null);
  const [sources, setSources] = useState<CvContextSourceOut[]>([]);
  const [synthItems, setSynthItems] = useState<CvSynthItem[]>([]);
  const synthPins = ((cv?.context?.synth_pins ?? {}) as Record<string, string>) ?? {};
  const [variantEditor, setVariantEditor] = useState<{
    open: boolean;
    initial: CvSynthItem | null;
    sourceKey: string;
  }>({ open: false, initial: null, sourceKey: "" });
  const [entityEditor, setEntityEditor] = useState<{
    open: boolean;
    sourceKey: string;
    itemId: string | null;
  }>({ open: false, sourceKey: "", itemId: null });
  const [bulletsEditor, setBulletsEditor] = useState<{
    open: boolean;
    sourceKey: string;
    itemId: string;
  }>({ open: false, sourceKey: "", itemId: "" });
  const [bulletsProposal, setBulletsProposal] = useState<string[] | null>(null);
  const [templates, setTemplates] = useState<CvTemplateSummary[]>([]);
  const [savedPostings, setSavedPostings] = useState<{ id: string; title: string; org: string }[]>([]);
  const [photos, setPhotos] = useState<GalleryPhoto[]>([]);
  const [tailorPostingId, setTailorPostingId] = useState("");
  const [html, setHtml] = useState("");
  const [metrics, setMetrics] = useState<CvRenderMetrics>({});
  const [blocks, setBlocks] = useState<CvBlock[]>([]);
  const [overrides, setOverrides] = useState<Record<string, CvOverridePatch>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [versions, setVersions] = useState<CvVersionOut[]>([]);
  const polishVersion = versions.find(
    (version) =>
      (version.content as { polish?: unknown } | undefined)?.polish != null
  );
  const [lint, setLint] = useState<CvLintReport | null>(null);
  const [suggestion, setSuggestion] = useState<CvSuggestionOut | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [tone, setTone] = useState("");
  const [length, setLength] = useState("");
  const [versionPreview, setVersionPreview] = useState<{ version: number; html: string } | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("sections");
  const [activePane, setActivePane] = useState<"canvas" | "inspector">("canvas");
  const [previewLoading, setPreviewLoading] = useState(true);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [history, setHistory] = useState<{
    past: { blocks: CvBlock[]; overrides: Record<string, CvOverridePatch> }[];
    future: { blocks: CvBlock[]; overrides: Record<string, CvOverridePatch> }[];
  }>({ past: [], future: [] });
  const [notice, setNotice] = useState<string | null>(null);
  const [critique, setCritique] = useState<CvAssistantCritique | null>(null);
  const [critiqueDismissed, setCritiqueDismissed] = useState(false);
  const [snapshotRows, setSnapshotRows] = useState<Record<string, unknown>>({});
  const [designState, setDesignState] = useState<CvDesignTokens | null>(null);
  const [designSaved, setDesignSaved] = useState<CvDesignTokens | null>(null);
  const [designMeta, setDesignMeta] = useState<{
    id: string;
    title: string;
    owned: boolean;
    ats_safe: boolean;
  } | null>(null);
  const [designApplying, setDesignApplying] = useState(false);
  const designDirty =
    !!designState &&
    !!designSaved &&
    JSON.stringify(designState) !== JSON.stringify(designSaved);
  void designApplying;
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

  const refreshSources = useCallback(async () => {
    try {
      const context = await fetchContextSources();
      setSources(context.sources);
    } catch {
      void undefined;
    }
  }, []);

  const bulletsEditorView = useMemo(() => {
    if (!bulletsEditor.open) return null;
    const rows = snapshotRows[bulletsEditor.sourceKey];
    const row = (Array.isArray(rows) ? rows : []).find(
      (entry) =>
        typeof entry === "object" &&
        entry !== null &&
        (entry as { id?: string }).id === bulletsEditor.itemId
    ) as
      | {
          title?: string;
          org_name?: string;
          description?: string;
          achievements?: CvSynthBullet[];
        }
      | undefined;
    const key = `${bulletsEditor.sourceKey}:${bulletsEditor.itemId}`;
    const patched = overrides[key]?.achievements;
    return {
      head: { title: row?.title ?? "", org: row?.org_name ?? "" },
      base: row?.achievements ?? [],
      override: Array.isArray(patched) ? patched : null,
      text: String(row?.description ?? ""),
    };
  }, [bulletsEditor, snapshotRows, overrides]);

  const closeBulletsEditor = useCallback(() => {
    setBulletsEditor({ open: false, sourceKey: "", itemId: "" });
    setBulletsProposal(null);
  }, []);

  const refreshPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const result = await previewCv(id);
      setHtml(result.html);
      setMetrics(result.metrics);
      setBlocks(result.blocks ?? []);
      setSnapshotRows(result.resolution.snapshot ?? {});
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

  const refreshMeta = useCallback(
    async (notifyProfileChanged = true) => {
      try {
        const [rows, report, status] = await Promise.all([
          fetchVersions(id),
          fetchLint(id),
          fetchContextStatus(id),
        ]);
        setVersions(rows);
        setLint(report);
        if (status.stale && notifyProfileChanged) {
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
    },
    [id, pushToast]
  );

  const loadDesign = useCallback(async () => {
    try {
      const out = await fetchCvDesign(id);
      setDesignState(out.design);
      setDesignMeta(out.template);
      setDesignSaved(out.design);
    } catch (err) {
      setError(apiDetail(err));
    }
  }, [id]);

  const changeDesign = (patch: Partial<CvDesignTokens>) => {
    setDesignState((current) => (current ? { ...current, ...patch } : current));
  };

  const resetDesign = () => {
    setDesignState(designSaved ? { ...designSaved } : null);
  };

  const applyDesign = async () => {
    if (!designState || !designSaved) return;
    const patch: Record<string, unknown> = {};
    const saved = designSaved as unknown as Record<string, unknown>;
    for (const [key, value] of Object.entries(designState)) {
      if (JSON.stringify(value) !== JSON.stringify(saved[key])) {
        patch[key] = value;
      }
    }
    if (Object.keys(patch).length === 0) return;
    setDesignApplying(true);
    try {
      const out = await applyCvOps(id, [{ op: "update_design", design: patch }]);
      setDesignState(out.state.design ?? designState);
      setDesignSaved(out.state.design ?? designState);
      setHtml(out.state.html);
      setMetrics(out.state.metrics as CvRenderMetrics);
      setBlocks(out.state.blocks ?? []);
      if (out.state.document.template_id) {
        setCv((prev) =>
          prev ? ({ ...prev, template_id: out.state.document.template_id } as CvDocumentOut) : prev
        );
      }
      void refreshMeta();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setDesignApplying(false);
    }
  };

  const applyPageSize = async (page_size: string) => {
    try {
      const out = await applyCvOps(id, [{ op: "set_doc_options", page_size }]);
      setHtml(out.state.html);
      setMetrics(out.state.metrics as CvRenderMetrics);
      setCv((prev) => (prev ? ({ ...prev, page_size } as CvDocumentOut) : prev));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const applyCritiqueFixes = async (fixes: Record<string, string>) => {
    try {
      const out = await applyCvOps(id, [{ op: "update_design", design: fixes }]);
      setHtml(out.state.html);
      setMetrics(out.state.metrics as CvRenderMetrics);
      setBlocks(out.state.blocks ?? []);
      setCritique(null);
      void refreshMeta();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  useEffect(() => {
    setCritiqueDismissed(false);
  }, [critique]);

  useEffect(() => {
    if (isLetter) setInspectorTab("context");
  }, [isLetter]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [document, context, templateList, postings, photos, variants] = await Promise.all([
          fetchCv(id),
          fetchContextSources(),
          fetchTemplates().catch(() => []),
          fetchPostings({ saved: true }).catch(() => ({ items: [] })),
          fetchPhotoGallery().catch(() => []),
          fetchSynthItems().then(usableVariants).catch(() => [] as CvSynthItem[]),
        ]);
        if (cancelled) return;
        setCv(document);
        setSources(context.sources);
        setSynthItems(variants);
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
        void loadDesign();
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
    (next: { blocks: CvBlock[]; overrides: Record<string, CvOverridePatch> }, immediate = false) => {
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
    async (snapshot: { blocks: CvBlock[]; overrides: Record<string, CvOverridePatch> }) => {
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
        await setContext(id, {
          mode: "custom",
          include,
          exclude: [],
          synth_pins: synthPins,
        });
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id, synthPins, refreshPreview]
  );

  const commitSynthMode = useCallback(
    async (pins?: Record<string, string>) => {
      const include = [...selected].map((value) => {
        const [source, item] = value.split(":");
        return { source_key: source, item_id: item };
      });
      try {
        const effectivePins = pins ?? synthPins;
        await setContext(id, {
          mode: "custom",
          include,
          exclude: [],
          synth_pins: effectivePins,
        });
        setCv((prev) =>
          prev
            ? ({
                ...prev,
                context: {
                  ...(prev.context ?? {}),
                  synth_pins: effectivePins,
                },
              } as CvDocumentOut)
            : prev,
        );
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [id, selected, synthPins, refreshPreview]
  );

  const activateVariant = useCallback(
    async (variant: CvSynthItem) => {
      try {
        await patchSynthItem(variant.id, { status: "active" });
        setSynthItems(usableVariants(await fetchSynthItems()));
        setNotice(t("cvSynth.activated"));
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [refreshPreview, t]
  );

  const resetVariant = useCallback(
    async (variant: CvSynthItem) => {
      try {
        await refreshSynthSourceState(variant.id);
        setSynthItems(usableVariants(await fetchSynthItems()));
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [refreshPreview]
  );

  const commitSynthPin = useCallback(
    async (sourceKey: string, itemId: string, synthId: string | null) => {
      const pins = { ...synthPins };
      if (synthId) {
        const variant = synthItems.find((v) => v.id === synthId);
        if (variant?.status === "draft") {
          await activateVariant(variant);
        }
        pins[`${sourceKey}:${itemId}`] = synthId;
      } else {
        delete pins[`${sourceKey}:${itemId}`];
      }
      await commitSynthMode(pins);
    },
    [synthPins, synthItems, commitSynthMode, activateVariant]
  );

  // Plan 103 2d: optimistic landing — patch the saved row into the
  // list synchronously; the following fetch reconciles (position,
  // computed state).
  const absorbSynthRow = useCallback((row: CvSynthItem) => {
    setSynthItems((previous) => {
      const rest = previous.filter((item) => item.id !== row.id);
      return [row, ...rest];
    });
  }, []);

  const saveVariant = useCallback(
    async (body: VariantEditorBody) => {
      try {
        const trackedId = body.persisted_id || variantEditor.initial?.id;
        if (trackedId) {
          await patchSynthItem(trackedId, {
            payload: body.payload,
            variant_key: body.variant_key,
          });
        } else {
          const created = await createSynthItem({
            refs: body.refs,
            scope: body.scope,
            payload: body.payload,
            variant_key: body.variant_key,
            target_posting_id: body.target_posting_id ?? undefined,
            voice: body.voice,
          });
          absorbSynthRow(created);
        }
        setVariantEditor({ open: false, initial: null, sourceKey: "" });
        setNotice(t("cvSynth.saved"));
        setSynthItems(usableVariants(await fetchSynthItems()));
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [variantEditor.initial, absorbSynthRow, refreshPreview, t]
  );

  const saveVariantAndUse = useCallback(
    async (body: VariantEditorBody) => {
      const trackedId = body.persisted_id;
      try {
        let row: CvSynthItem;
        if (trackedId) {
          row = await patchSynthItem(trackedId, {
            payload: body.payload,
            variant_key: body.variant_key,
            status: "active",
          });
        } else {
          row = await createSynthItem({
            refs: body.refs,
            scope: body.scope,
            payload: body.payload,
            variant_key: body.variant_key,
            target_posting_id: body.target_posting_id ?? undefined,
            voice: body.voice,
          });
        }
        absorbSynthRow(row);
        const promote = await patchSynthItem(row.id, { status: "active" });
        absorbSynthRow(promote);
        const pins = { ...synthPins };
        const firstRef = body.refs[0];
        if (firstRef) {
          pins[`${firstRef.source_key}:${firstRef.item_id}`] = row.id;
        }
        await commitSynthMode(pins);
        setVariantEditor({ open: false, initial: null, sourceKey: "" });
        setNotice(t("cvSynth.activated"));
        setSynthItems(usableVariants(await fetchSynthItems()));
        await refreshPreview();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [synthPins, absorbSynthRow, commitSynthMode, refreshPreview, t]
  );

  const generateVariantDraft = useCallback(
    async (
      request: VariantGenerateRequest,
      refs: { source_key: string; item_id: string }[]
    ) => {
      const out = await generateSynthItems({
        refs,
        action: request.action,
        language: request.target_language ?? "en",
        target_language:
          request.action === "translate" ? request.target_language : undefined,
        tone: request.tone ?? undefined,
        length: toBackendLength(request.length),
        instruction: request.instruction,
      });
      const row = out.items[0];
      if (!row) {
        throw new Error(t("cvSynth.noDraft", { defaultValue: "No draft was generated" }));
      }
      return {
        id: row.id,
        description: row.payload.description ?? "",
        achievements: row.payload.achievements ?? [],
        language: row.voice.language ?? "en",
      };
    },
    [t]
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
      setCritique(state.critique ?? null);
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

  const dataRevision = useCvBuilderLink((state) => state.dataRevision);
  const refreshSynthRows = useCallback(async () => {
    try {
      setSynthItems(usableVariants(await fetchSynthItems()));
    } catch {
      // best-effort: the preview refresh below is the visible part
    }
  }, []);
  useEffect(() => {
    // Plan 104: chat-side mutations (approved/reverted cards, write tools)
    // land server-side while this page is open — refetch the resolved CV
    // so the Studio stays current without a manual reload. Debounced so a
    // burst of approvals triggers one refresh. Plan 105: context sources
    // ride along (created entities must appear), and local (Studio-driven)
    // bumps skip the "Profile changed" toast — the user made the change.
    if (dataRevision === 0) {
      return;
    }
    const timer = setTimeout(() => {
      // Never race the editor's debounced autosave: commit pending local
      // edits first, then pull the server's resolved state.
      useCvBuilderLink.getState().flushPendingSave();
      void refreshPreview();
      void refreshSources();
      void refreshMeta(useCvBuilderLink.getState().lastDataOrigin !== "local");
      void refreshSynthRows();
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataRevision]);

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

  function moveBlockTo(index: number, to: number) {
    const next = [...blocks];
    if (to < 0 || to > next.length) return;
    const [moved] = next.splice(index, 1);
    next.splice(to > index ? to - 1 : to, 0, moved);
    persistWorking({ blocks: next, overrides }, true);
  }

  function assignArea(index: number, area: CvArea["id"]) {
    const source = blocks[index];
    if (!source || areaOf(source) === area) return;
    const marked = blocks.map((block, position) =>
      position === index
        ? { ...block, area, column: area as CvArea["id"] }
        : block
    );
    const lastInArea = marked.reduce(
      (last, block, position) =>
        position !== index && areaOf(block) === area ? position : last,
      -1
    );
    const [moved] = marked.splice(index, 1);
    marked.splice(lastInArea >= 0 ? lastInArea : marked.length, 0, moved);
    persistWorking({ blocks: marked, overrides }, true);
  }

  function removeBlock(index: number) {
    const next = blocks.filter((_, position) => position !== index);
    setNotice(t("cvBuilder.sectionRemoved"));
    persistWorking({ blocks: next, overrides }, true);
  }

  function addBlock(kind: string, area?: CvArea["id"]) {
    const props = { ...(BLOCK_TYPES.find((type) => type.value === kind)?.props ?? {}) };
    const target = area ?? areas[0].id;
    const block: CvBlock =
      areas.length > 1 ? { kind, props, area: target, column: target } : { kind, props };
    const next = [...blocks];
    const last = next.map(areaOf).lastIndexOf(target);
    next.splice(last === -1 ? next.length : last + 1, 0, block);
    setNotice(t("cvBuilder.sectionAdded"));
    persistWorking({ blocks: next, overrides }, true);
  }

  function duplicateBlock(index: number) {
    const source = blocks[index];
    if (!source) return;
    const area = areaOf(source);
    const copy: CvBlock = {
      kind: source.kind,
      props: JSON.parse(JSON.stringify(source.props ?? {})) as Record<string, unknown>,
      ...(source.area ? { area: source.area } : {}),
      ...(areas.length > 1 ? { column: area } : {}),
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

  function setBlockHidden(index: number, hidden: boolean) {
    const next = blocks.map((block, position) =>
      position === index ? { ...block, hidden } : block
    );
    persistWorking({ blocks: next, overrides });
  }

  const itemOptions = useMemo(() => {
    const out: Record<string, { id: string; label: string }[]> = {};
    for (const [key, rows] of Object.entries(snapshotRows)) {
      if (!Array.isArray(rows)) continue;
      const list = rows
        .map((row) => {
          const entry = row as {
            id?: string;
            item_id?: string;
            title?: string;
            program?: string;
            issuer?: string;
            label?: string;
          };
          return {
            id: String(entry.id ?? entry.item_id ?? ""),
            label: String(
              entry.title ?? entry.program ?? entry.issuer ?? entry.label ?? ""
            ),
          };
        })
        .filter((entry) => entry.id && entry.label);
      if (list.length > 0) out[key] = list;
    }
    return out;
  }, [snapshotRows]);

  const synthOptions = useMemo(
    () =>
      synthItems
        .filter((variant) => variant.status !== "archived")
        .map((variant) => {
          // Library rows from before typed payloads landed may omit
          // payload/voice — the unhandled error at this map broke the
          // whole vitest run in CI.
          const payload = variant.payload ?? { description: "", summary: "" };
          const voice = variant.voice ?? { language: "en" };
          return {
            id: variant.id,
            label:
              (payload.description || payload.summary || "").slice(0, 42) ||
              `${variant.variant_key} · ${voice.language}`,
            stale: variant.stale,
          };
        }),
    [synthItems]
  );

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

  async function createMatchingLetter() {
    if (!cv?.target_posting_id) return;
    setBusy("letter");
    setError("");
    try {
      const letter = await createCoverLetter({
        posting_id: cv.target_posting_id,
        base_cv_id: cv.id,
        title: `Matching cover letter — ${cv.title}`.slice(0, 200),
      });
      navigate(`/cv/${letter.id}`);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy("");
    }
  }

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

  async function applyOverridePatch(target: Record<string, CvOverridePatch>) {
    persistWorking({ blocks, overrides: { ...overrides, ...target } }, true);
  }

  async function applyProposal(entry: CvProposal) {
    const field = entry.field ?? "description";
    const key = entry.ref ? refKey(entry.ref.source_key, entry.ref.item_id) : "summary:summary";
    if (entry.bullets?.length && entry.ref) {
      // Plan 106: bullet proposals never apply-all — they land in the
      // bullets editor as keep/discard chips against the current list.
      setNotice(t("cvBuilder.proposalChipsHint"));
      setSuggestion(null);
      setBulletsEditor({
        open: true,
        sourceKey: entry.ref.source_key,
        itemId: entry.ref.item_id,
      });
      setBulletsProposal(entry.bullets);
      return;
    }
    setNotice(t("cvBuilder.proposalApplied"));
    await applyOverridePatch({ [key]: { ...overrides[key], [field]: entry.text } });
    setSuggestion(null);
  }

  async function runAction(
    action: "summary" | "gaps" | "compaction" | "tailor" | "translate",
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

  const overflow =
    lint?.metrics?.pages_actual_over_budget === true || metrics.overflow === true;
  const measuredPages = Number(lint?.metrics?.pages_actual) || 0;
  const pages = measuredPages || metrics.estimated_pages || 1;
  const pagesSource =
    lint?.metrics?.page_count_source === "pdf" ||
    lint?.metrics?.page_count_source === "last_export"
      ? lint.metrics.page_count_source
      : null;
  const maxPages = cv?.max_pages ?? 1;
  const currentLetter = isLetter ? letterPropsOf(blocks) : null;
  const activeDesign = templates.find(
    (row) => row.id === (cv?.template_id ?? "")
  )?.content?.design;
  const areas = areasForDesign(activeDesign as Partial<CvDesignTokens>);

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
    { id: "open-runs", label: t("cvBuilder.runs.title"), run: () => setRunsOpen(true) },
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
    <div className="ca-workspace flex min-h-0 flex-col gap-3 lg:h-full" data-testid="cv-builder">
      <BuilderToolbar
        title={cv.title}
        onRename={(title) => void renameCv(title)}
        versions={versions}
        lint={lint}
        pages={pages}
        maxPages={maxPages}
        overflow={overflow}
        pagesSource={pagesSource}
        saveState={saveState}
        saveBusy={busy === "save"}
        exportBusy={busy.startsWith("export:") ? busy.slice("export:".length) : ""}
        canUndo={history.past.length > 0}
        canRedo={history.future.length > 0}
        onSaveVersion={() => void saveVersion()}
        onExport={(format) => void handleExport(format)}
        onCreateLetter={
          !isLetter && cv.target_posting_id ? () => void createMatchingLetter() : null
        }
        letterBusy={busy === "letter"}
        aiCluster={
          <AiToolbarCluster
            mode={isLetter ? "cover_letter" : "resume"}
            busy={busy}
            translateLabel={`Translate → ${cv.language.toUpperCase()}`}
            hasTargetPosting={Boolean(cv.target_posting_id)}
            savedPostings={savedPostings}
            tailorPostingId={tailorPostingId}
            onTailorPostingChange={setTailorPostingId}
            onTailorRequest={handleTailorRequest}
            onRunAction={(action) => void runAction(action)}
            onDraftLetter={() => void runLetterDraft()}
            tone={tone}
            onToneChange={setTone}
            length={length}
            onLengthChange={setLength}
          />
        }
        onOpenVersions={() => setVersionsOpen(true)}
        onOpenRuns={() => setRunsOpen(true)}
        onOpenPolish={polishVersion ? () => setRunsOpen(true) : null}        onOpenPalette={() => setPaletteOpen(true)}
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

      <BuildProgressCard
        cvId={id}
        onOpenRuns={() => setRunsOpen(true)}
        onRunFinished={() => void refreshPreview().then(() => refreshMeta())}
      />

      <div className="ca-ws-switcher mb-2 flex shrink-0 gap-1" role="group" aria-label={t("experience.panesAria")} data-testid="pane-switcher">
        {(
          [
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

      <div className="ca-ws-grid ca-ws-grid-narrow grid min-h-0 flex-1 grid-cols-1 gap-3">
        <div
          className={`${
            activePane === "inspector" ? "flex" : "hidden"
          } ca-ws-pane cv-pane-enter min-h-0 flex-col rounded-xl border border-transparent bg-[var(--as-muted)] p-2.5`}
          data-testid="builder-inspector"
        >
          <InspectorPanel
            tab={inspectorTab}
            onTabChange={setInspectorTab}
            mode={isLetter ? "cover_letter" : "resume"}
            context={
              isLetter ? (
                <LetterBriefPanel brief={brief} loading={briefLoading} />
              ) : (
                <ContextPanel
                  sources={sources ?? []}
                  selected={selected}
                  onToggle={toggleItem}
                  onToggleGroup={(source, includeAll) => void toggleGroup(source, includeAll)}
                  synthPins={(cv?.context?.synth_pins as Record<string, string>) ?? {}}
                  onPinVariant={(sourceKey, itemId, synthId) =>
                    void commitSynthPin(sourceKey, itemId, synthId)
                  }
                  variants={synthItems}
                  onAddVariant={(sourceKey) =>
                    setVariantEditor({ open: true, initial: null, sourceKey })
                  }
                  onEditVariant={(variant) =>
                    setVariantEditor({ open: true, initial: variant, sourceKey: "" })
                  }
                  onResetVariant={(variant) => void resetVariant(variant)}
                  onAddItem={(sourceKey) =>
                    setEntityEditor({ open: true, sourceKey, itemId: null })
                  }
                  onEditItem={(sourceKey, itemId) =>
                    setEntityEditor({ open: true, sourceKey, itemId })
                  }
                  onEditBullets={(sourceKey, itemId) =>
                    setBulletsEditor({ open: true, sourceKey, itemId })
                  }
                />
              )
            }
            letterProps={currentLetter?.props ?? null}
            onUpdateLetterProps={(patch) => {
              if (currentLetter) updateBlockProps(currentLetter.index, patch);
            }}
            letterSuggestion={letterSuggestion}
            onCloseLetterSuggestion={() => setLetterSuggestion(null)}
            onApplyLetterDraft={(paragraphs, draft) =>
              void applyLetterDraft(paragraphs, draft)
            }
            templates={templates}
            templateId={cv.template_id ?? ""}
            onTemplate={(templateId) => void applyTemplate(templateId)}
            onBrowseTemplates={() => setGalleryOpen(true)}
            onCustomizeTemplate={() => {
              if (cv.template_id) navigate(`/cv/templates/${cv.template_id}`);
            }}
            design={designState}
            designTemplateMeta={designMeta}
            designDirty={designDirty}
            onDesignChange={changeDesign}
            onDesignApply={() => void applyDesign()}
            onDesignReset={resetDesign}
            pageSize={cv.page_size}
            onPageSize={(page_size) => void applyPageSize(page_size)}
            photos={photos}
            photoId={cv.photo_document_id ?? ""}
            onPhoto={(photoId) => void applyPhoto(photoId)}
            photoUploading={photoUploading}
            onUploadPhoto={(file) => void handlePhotoUpload(file)}
            onError={setError}
            blocks={blocks}
            areas={areas}
            skillOptions={Array.isArray(snapshotRows.skills)
              ? (snapshotRows.skills as { item_id?: string; label?: string; title?: string }[]).map((row) => ({
                  id: String(row.item_id ?? row.label ?? ""),
                  label: String(row.label ?? row.title ?? ""),
                }))
              : []}
            itemOptions={itemOptions}
            synthOptions={synthOptions}
            onAddBlock={addBlock}
            onMoveBlock={moveBlock}
            onAssignArea={assignArea}
            onDuplicateBlock={duplicateBlock}
            onRemoveBlock={removeBlock}
            onUpdateBlockProps={updateBlockProps}
            onSetBlockHidden={setBlockHidden}
            dragIndexRef={dragIndex}
            onDragReorder={(target) => {
              if (dragIndex.current !== null) moveBlockTo(dragIndex.current, target);
              dragIndex.current = null;
            }}
            busy={busy}
            suggestion={suggestion}
            onCloseSuggestion={() => setSuggestion(null)}
            onApplyProposal={(entry) => void applyProposal(entry)}
          />
        </div>

        <div
          className={`${
            activePane === "canvas" ? "flex" : "hidden"
          } ca-ws-pane cv-pane-enter min-h-0 flex-col`}
          data-testid="builder-canvas"
        >
          {critique && !critiqueDismissed && (
            <div className="relative mb-2 shrink-0" data-testid="canvas-critique">
              <CritiqueCard
                critique={critique}
                onApplyFixes={(fixes) => void applyCritiqueFixes(fixes)}
                busy={busy.startsWith("ai:")}
              />
              <button
                type="button"
                aria-label="Dismiss critique"
                title="Dismiss"
                onClick={() => setCritiqueDismissed(true)}
                data-testid="dismiss-critique"
                className="absolute right-1.5 top-1.5 cursor-pointer rounded p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          )}
          <PreviewCanvas
            html={html}
            loading={previewLoading}
            pageSize={cv?.page_size}
            pages={pages}
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

      <RunsPanelModal
        open={runsOpen}
        onOpenChange={setRunsOpen}
        cv={cv}
        polishVersion={polishVersion}
      />
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
          <div
            className="flex items-center justify-end gap-2 border-t border-[var(--as-border)] p-4 pt-3"
            data-testid="versions-footer"
          >
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleDuplicate()}
              data-testid="duplicate-cv"
            >
              <Copy className="mr-1 h-3.5 w-3.5" />
              {isLetter ? "Duplicate letter" : "Duplicate CV"}
            </Button>
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
        cvId={cv.id}
        onUse={(template) => void applyTemplate(template.id)}
      />

      <GenerateCvModal open={generateOpen} onOpenChange={setGenerateOpen} />

      {variantEditor.open && (
        <VariantEditor
          open
          sources={sources ?? []}
          savedPostings={savedPostings}
          initial={variantEditor.initial}
          defaultLanguage={cv.language}
          defaultSourceKey={variantEditor.sourceKey}
          busy={busy !== ""}
          onActivate={async () => {
            if (variantEditor.initial)
              await activateVariant(variantEditor.initial);
            setVariantEditor({ open: false, initial: null, sourceKey: "" });
          }}
          onClose={() => setVariantEditor({ open: false, initial: null, sourceKey: "" })}
          onSubmit={saveVariant}
          onUseSaved={saveVariantAndUse}
          onGenerate={generateVariantDraft}
          variants={synthItems}
        />
      )}

      {entityEditor.open && (
        <EntityEditorModal
          sourceKey={entityEditor.sourceKey}
          itemId={entityEditor.itemId}
          onSaved={() => {
            setEntityEditor({ open: false, sourceKey: "", itemId: null });
            useCvBuilderLink.getState().notifyDataChanged("local");
          }}
          onClose={() => setEntityEditor({ open: false, sourceKey: "", itemId: null })}
        />
      )}

      {bulletsEditorView && (
        <ItemBulletsEditorModal
          sourceKey={bulletsEditor.sourceKey}
          itemId={bulletsEditor.itemId}
          head={bulletsEditorView.head}
          base={bulletsEditorView.base}
          override={bulletsEditorView.override}
          proposal={bulletsProposal ? { bullets: bulletsProposal } : null}
          onProposalConsumed={() => setBulletsProposal(null)}
          onGenerate={async () => {
            const out = await aiAction(id, "bullet", {
              source_key: bulletsEditor.sourceKey,
              item_id: bulletsEditor.itemId,
              text: bulletsEditorView.text,
            });
            const first = out.proposals[0];
            return first?.proposal.bullets ?? [];
          }}
          onSave={(entries) => {
            const key = `${bulletsEditor.sourceKey}:${bulletsEditor.itemId}`;
            closeBulletsEditor();
            void applyOverridePatch({
              [key]: { ...overrides[key], achievements: entries },
            });
          }}
          onReset={() => {
            const key = `${bulletsEditor.sourceKey}:${bulletsEditor.itemId}`;
            const next = { ...overrides };
            delete next[key];
            closeBulletsEditor();
            void persistWorking({ blocks, overrides: next }, true);
          }}
          onClose={closeBulletsEditor}
        />
      )}
    </div>
  );
}
