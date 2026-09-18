import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, List, Plus, Sparkles, X } from "lucide-react";
import {
  Button,
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import type { CvSynthBullet, CvSynthItem, CvSynthPayload } from "@/types/cv";
import type { CvContextSourceOut } from "@/types/cv";
import { CvRichTextEditor } from "@/components/cv/CvRichTextEditor";

const MAX_REFS = 5;

type CvSynthAction = "summarize" | "detail" | "restyle" | "posting_fit" | "translate";

export interface VariantEditorBody {
  refs: { source_key: string; item_id: string }[];
  scope: "item" | "summary";
  payload: { description: string; achievements: CvSynthBullet[] };
  variant_key: string;
  target_posting_id?: string | null;
  voice: { language: string };
  /** Plan 103: the slot row the form is currently
   * tracking — null (or absent) means a fresh creation. */
  persisted_id?: string | null;
}

export interface VariantGenerateRequest {
  action: CvSynthAction;
  target_language?: string;
  tone?: string;
  length?: string;
  instruction?: string;
}


interface VariantEditorProps {
  open: boolean;
  sources: CvContextSourceOut[];
  savedPostings?: { id: string; title: string }[];
  initial?: CvSynthItem | null;
  defaultLanguage?: string;
  defaultSourceKey?: string;
  busy?: boolean;
  /** The caller's draft + active variants; the editor derives the slot
   * (same refs, variant_key, posting) for the back/forward browser. */
  variants?: CvSynthItem[];
  onGenerate?: (
    request: VariantGenerateRequest,
    refs: { source_key: string; item_id: string }[]
  ) => Promise<{
    id?: string;
    description: string;
    achievements: CvSynthBullet[];
    language: string;
  }>;
  onUseSaved?: (body: VariantEditorBody) => Promise<void>;
  onActivate?: () => Promise<void> | void;
  onClose: () => void;
  onSubmit: (body: VariantEditorBody) => Promise<void>;
}

function refKey(sourceKey: string, itemId: string): string {
  return `${sourceKey}:${itemId}`;
}

function toOptions(refs: string[]): { source_key: string; item_id: string }[] {
  return refs.map((key) => {
    const [source_key, item_id] = key.split(":");
    return { source_key, item_id };
  });
}

function slotKeyOf(
  refKeys: string[],
  variantKey: string,
  postingId: string
): string {
  return `${[...refKeys].sort().join("|")}#${variantKey}#${postingId || ""}`;
}

function rowSlotKeyOf(row: CvSynthItem): string {
  return slotKeyOf(
    (row.source_refs ?? []).map((ref) => refKey(ref.source_key, ref.item_id)),
    row.variant_key,
    row.target_posting_id ?? ""
  );
}

function variantTextOf(payload: CvSynthPayload): string {
  const text = payload.description || payload.summary || "";
  if (text) return text;
  return (payload.achievements ?? [])
    .map((entry) => (entry.text ?? "").trim())
    .filter(Boolean)
    .join(" · ");
}

function textsOf(payload: CvSynthPayload | undefined): string[] {
  return (payload?.achievements ?? []).map((entry) => (entry.text ?? "").trim());
}

const FIELD_CLASS =
  "w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--as-accent)]";

const GEN_ACTIONS: CvSynthAction[] = [
  "summarize",
  "detail",
  "restyle",
  "posting_fit",
  "translate",
];

export function VariantEditor({
  open,
  sources,
  savedPostings = [],
  initial = null,
  defaultLanguage = "en",
  defaultSourceKey,
  busy = false,
  variants = [],
  onGenerate,
  onUseSaved,
  onActivate,
  onClose,
  onSubmit,
}: VariantEditorProps) {
  const { t } = useTranslation();
  const editing = initial !== null;
  const [refs, setRefs] = useState<string[]>(
    initial
      ? (initial.source_refs ?? []).map((ref) => refKey(ref.source_key, ref.item_id))
      : defaultSourceKey && sources.length > 0
        ? sources
            .filter((source) => source.key === defaultSourceKey)
            .flatMap((source) =>
              (source.items ?? []).slice(0, 1).map((item) => refKey(source.key, item.item_id)),
            )
        : []
  );
  const [description, setDescription] = useState(initial?.payload?.description ?? "");
  const [bullets, setBullets] = useState<string[]>(() => {
    const texts = textsOf(initial?.payload);
    return texts.length ? texts : [""];
  });
  const [variantKey, setVariantKey] = useState(initial?.variant_key ?? "default");
  const [language, setLanguage] = useState(
    initial?.voice?.language ?? defaultLanguage
  );
  const [postingId, setPostingId] = useState(initial?.target_posting_id ?? "");
  const [loadedId, setLoadedId] = useState<string | null>(initial?.id ?? null);

  const [genAction, setGenAction] = useState<CvSynthAction>("detail");
  const [genTargetLanguage, setGenTargetLanguage] = useState("de");
  const [genTone, setGenTone] = useState("");
  const [genLength, setGenLength] = useState("standard");
  const [genInstruction, setGenInstruction] = useState("");
  const [genAdvanced, setGenAdvanced] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  const groupedOptions = useMemo(
    () =>
      sources
        .filter(
          (source) =>
            (source.items ?? []).length > 0 &&
            source.key !== "basics" &&
            source.key !== "summary",
        )
        .map((source) => ({
          label: source.label,
          options: (source.items ?? []).map((item) => ({
            key: refKey(source.key, item.item_id),
            label: item.label,
          })),
        })),
    [sources]
  );
  const refLabelLookup = useMemo(() => {
    const map = new Map<string, { label: string; source: string }>();
    for (const source of sources) {
      for (const item of source.items ?? []) {
        map.set(refKey(source.key, item.item_id), {
          label: item.label,
          source: source.label,
        });
      }
    }
    return map;
  }, [sources]);

  const slotRows = useMemo(() => {
    if (refs.length === 0) return [];
    const key = slotKeyOf(refs, variantKey.trim() || "default", postingId || "");
    return variants
      .filter((row) => rowSlotKeyOf(row) === key)
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  }, [refs, variantKey, postingId, variants]);
  const slotPos = useMemo(
    () => Math.max(
      0,
      loadedId
        ? slotRows.findIndex((row) => row.id === loadedId)
        : 0,
    ),
    [loadedId, slotRows],
  );
  function loadRow(row: CvSynthItem) {
    setLoadedId(row.id);
    setDescription(row.payload.description ?? "");
    const texts = textsOf(row.payload);
    setBullets(texts.length ? texts : [""]);
    setLanguage(row.voice.language ?? defaultLanguage);
    setPostingId(row.target_posting_id ?? "");
  }
  function stepSlot(delta: number) {
    if (slotRows.length === 0) return;
    const at = loadedId ? slotRows.findIndex((row) => row.id === loadedId) : 0;
    const next = Math.min(slotRows.length - 1, Math.max(0, at + delta));
    const row = slotRows[next];
    if (row && row.id !== loadedId) loadRow(row);
  }

  async function runGenerate() {
    if (!onGenerate || refs.length === 0 || generating) return;
    const dirty = hasText;
    if (dirty && !window.confirm(t("cvSynth.editor.generateOverwrite", {
      defaultValue: "Generate will replace the text you have typed — continue?",
    }))) {
      return;
    }
    setGenerating(true);
    try {
      const result = await onGenerate(
        {
          action: genAction,
          target_language:
            genAction === "translate" ? genTargetLanguage : undefined,
          tone: genTone === "none" ? undefined : genTone,
          length: genAdvanced ? genLength : undefined,
        },
        toOptions(refs)
      );
      setDescription(result.description ?? "");
      const texts = (result.achievements ?? []).map((entry) => (entry.text ?? "").trim());
      setBullets(texts.length ? texts : [""]);
      if (result.language) setLanguage(result.language);
      setLoadedId(result.id ?? null);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  function resolvedRefLabel(key: string): string {
    const found = refLabelLookup.get(key);
    if (found) return found.label;
    const [sourceKey] = key.split(":");
    return key.startsWith("summary:")
      ? t("cvSynth.sourceSummary")
      : `${t(`cvSynth.sources.${sourceKey}`) === `cvSynth.sources.${sourceKey}` ? sourceKey : t(`cvSynth.sources.${sourceKey}`)} · ${key.slice(-8)}`;
  }
  const optionCount = groupedOptions.reduce(
    (total, group) => total + group.options.length,
    0,
  );

  const hasText =
    description.trim() !== "" || bullets.some((bullet) => bullet.trim() !== "");
  const canSave = hasText && refs.length > 0;

  function buildBody(withTextOnly: boolean): VariantEditorBody | null {
    if (!withTextOnly) return null;
    const isSummary = refs.every((key) => key.startsWith("summary:"));
    return {
      refs: toOptions(refs),
      scope: isSummary ? "summary" : "item",
      payload: {
        description: description.trim(),
        achievements: bullets
          .map((bullet) => bullet.trim())
          .filter(Boolean)
          .map((text) => ({ text })),
      },
      variant_key: variantKey.trim() || "default",
      target_posting_id: postingId || null,
      voice: { language },
      persisted_id: loadedId,
    };
  }

  async function save() {
    const body = buildBody(canSave);
    if (!body) return;
    await onSubmit(body);
  }

  async function saveAndUse() {
    const body = buildBody(canSave);
    if (!body) return;
    await onUseSaved?.(body);
  }

  // Plan 103 2b: the letter currently applied for this slot — the slot's
  // active row, else the slot's newest row — against the form payload.
  const onCvRow = useMemo(() => {
    const pool = slotRows.length > 0 ? slotRows : loadedId && initial ? [initial] : [];
    return pool.find((row) => row.status === "active") ?? null;
  }, [slotRows, initial, loadedId]);
  const currentText = variantTextOf(onCvRow?.payload ?? ({} as CvSynthPayload));
  return (
    <Modal open={open} onOpenChange={(next) => !next && onClose()}>
      <ModalContent size="xl" className="gap-0 p-0">
        <ModalHeader className="border-b border-[var(--as-border)]">
          <ModalTitle>
            {editing ? t("cvSynth.editor.editTitle") : t("cvSynth.editor.addTitle")}
          </ModalTitle>
          {!editing && (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("cvSynth.editor.subtitle", {
                defaultValue:
                  "Write tailored text once — it applies to matching CVs automatically.",
              })}
            </p>
          )}
        </ModalHeader>
        <div className="flex flex-col gap-4 px-6 py-5 text-sm">
          {editing ? (
            <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-[var(--as-muted)] px-3 py-2 text-xs text-[var(--as-muted-fg)]">
              {(initial?.source_refs ?? []).map((ref) => {
                const key = refKey(ref.source_key, ref.item_id);
                return (
                  <span
                    key={`${ref.source_key}-${ref.item_id}`}
                    className="max-w-52 truncate rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5 text-[var(--as-fg)]"
                    title={refKey(ref.source_key, ref.item_id)}
                    data-testid={`synth-editor-ref-chip-${key}`}
                  >
                    {resolvedRefLabel(key)}
                  </span>
                );
              })}
              <span className="ml-1">{t("cvSynth.editor.refsReadonly")}</span>
            </div>
          ) : (
            <section>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {t("cvSynth.editor.refsLabel")}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums transition-colors ${
                    refs.length > 0
                      ? "bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] text-[var(--as-accent)]"
                      : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
                  }`}
                  data-testid="synth-editor-refs"
                >
                  {refs.length}/{MAX_REFS}
                </span>
              </div>
              {refs.length > 0 && (
                <div
                  className="mb-2 flex flex-wrap gap-1.5"
                  data-testid="synth-editor-selected-refs"
                >
                  {refs.map((key) => (
                    <span
                      key={key}
                      className="flex max-w-60 items-center gap-1 truncate rounded-full border border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)] px-2 py-0.5 text-[11px] text-[var(--as-accent)]"
                      title={`${refLabelLookup.get(key)?.source ?? ""} — ${refLabelLookup.get(key)?.label ?? key}`}
                      data-testid={`synth-editor-ref-chip-${key}`}
                    >
                      <span className="truncate">{resolvedRefLabel(key)}</span>
                      <button
                        type="button"
                        aria-label={t("cvSynth.editor.refChipRemove")}
                        data-testid={`synth-editor-ref-chip-remove-${key}`}
                        onClick={() =>
                          setRefs((current) =>
                            current.filter((entry) => entry !== key),
                          )
                        }
                        className="shrink-0 rounded-full hover:text-red-600"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {optionCount === 0 ? (
                <p className="rounded-lg border border-dashed border-[var(--as-border)] px-3 py-4 text-center text-xs text-[var(--as-muted-fg)]">
                  {t("cvSynth.editor.noRefs")}
                </p>
              ) : (
                <div className="grid max-h-52 grid-cols-1 gap-2 overflow-y-auto rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-2 sm:grid-cols-2">
                  {groupedOptions.map((group) => (
                    <fieldset
                      key={group.label}
                      className="min-w-0 rounded-lg border border-[var(--as-border)] p-1.5"
                    >
                      <legend className="px-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                        {group.label}
                      </legend>
                      <div className="max-h-24 space-y-0.5 overflow-y-auto">
                        {group.options.map((option) => {
                          const active = refs.includes(option.key);
                          const disabled = !active && refs.length >= MAX_REFS;
                          return (
                            <label
                              key={option.key}
                              className={`flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 transition-colors ${
                                disabled
                                  ? "opacity-40"
                                  : "hover:bg-[var(--as-muted)]"
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={active}
                                disabled={disabled}
                                onChange={() =>
                                  setRefs((current) =>
                                    current.includes(option.key)
                                      ? current.filter((entry) => entry !== option.key)
                                      : [...current, option.key],
                                  )
                                }
                                data-testid={`synth-editor-ref-${option.key}`}
                                className="h-3.5 w-3.5 shrink-0 accent-[var(--as-accent)]"
                              />
                              <span className="min-w-0 flex-1 truncate text-xs">
                                {option.label}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </fieldset>
                  ))}
                </div>
              )}
              {refs.length >= MAX_REFS && (
                <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
                  {t("cvSynth.editor.refsCap", { count: MAX_REFS })}
                </p>
              )}
            </section>
          )}

          {onGenerate && refs.length > 0 && (
            <section
              className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid="synth-editor-generate"
            >
              <div className="flex flex-wrap items-center gap-1.5">
                {GEN_ACTIONS.map((action) => (
                  <button
                    key={action}
                    type="button"
                    aria-pressed={genAction === action}
                    disabled={action === "posting_fit" && !initial?.target_posting_id && postingId === ""}
                    data-testid={`synth-editor-gen-action-${action}`}
                    onClick={() => setGenAction(action)}
                    className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      genAction === action
                        ? "border-transparent bg-[color-mix(in_srgb,var(--as-accent)_14%,transparent)] text-[var(--as-accent)]"
                        : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)]"
                    }`}
                  >
                    {t(`cvSynth.actions.${action}`)}
                  </button>
                ))}
                {genAction === "translate" && (
                  <select
                    value={genTargetLanguage}
                    onChange={(event) => setGenTargetLanguage(event.target.value)}
                    aria-label="Target language"
                    data-testid="synth-editor-gen-target-language"
                    className="w-24 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs outline-none"
                  >
                    {["en", "de", "fr", "es", "it", "el"].map((code) => (
                      <option key={code} value={code}>
                        {code.toUpperCase()}
                      </option>
                    ))}
                  </select>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={generating}
                  data-testid="synth-editor-gen-run"
                  onClick={() => void runGenerate()}
                >
                  <Sparkles className="h-3.5 w-3.5" />{" "}
                  {t("cvSynth.editor.generateFill", { defaultValue: "AI generate" })}
                </Button>
              </div>
              <button
                type="button"
                className="mt-2 text-[11px] text-[var(--as-muted-fg)] underline-offset-2 hover:underline"
                aria-expanded={genAdvanced}
                data-testid="synth-editor-gen-advanced-toggle"
                onClick={() => setGenAdvanced((previous) => !previous)}
              >
                {t("cvSynth.editor.advanced", { defaultValue: "Advanced" })}
              </button>
              {genAdvanced && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <input
                    value={genInstruction}
                    onChange={(event) => setGenInstruction(event.target.value)}
                    placeholder={t("cvSynth.editor.instructionLabel", {
                      defaultValue: "Custom instruction (e.g. emphasize teamwork)",
                    })}
                    aria-label={t("cvSynth.editor.instructionLabel", {
                      defaultValue: "Custom instruction",
                    })}
                    data-testid="synth-editor-gen-instruction"
                    className="min-w-40 flex-1 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs outline-none"
                  />
                  <select
                    value={genTone}
                    onChange={(event) => setGenTone(event.target.value)}
                    aria-label={t("cvSynth.editor.toneLabel", { defaultValue: "Tone" })}
                    data-testid="synth-editor-gen-tone"
                    className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs outline-none"
                  >
                    <option value="none">{t("cvSynth.editor.toneNone", { defaultValue: "No tone" })}</option>
                    <option value="professional">professional</option>
                    <option value="warm">warm</option>
                    <option value="concise">concise</option>
                    <option value="confident">confident</option>
                  </select>
                  <select
                    value={genLength}
                    onChange={(event) => setGenLength(event.target.value)}
                    aria-label="Length"
                    data-testid="synth-editor-gen-length"
                    className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs outline-none"
                  >
                    <option value="concise">{t("cvSynth.length.concise", { defaultValue: "Concise" })}</option>
                    <option value="standard">{t("cvSynth.length.standard", { defaultValue: "Standard" })}</option>
                    <option value="detailed">{t("cvSynth.length.detailed", { defaultValue: "Detailed" })}</option>
                  </select>
                </div>
              )}
            </section>
          )}

          {editing && initial?.status === "draft" && onActivate && (
            <div
              className="flex items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900"
              data-testid="synth-editor-draft-row"
            >
              <span>{t("cvSynth.editor.draftHint")}</span>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                data-testid="synth-editor-activate"
                onClick={() => void onActivate()}
              >
                {t("cvSynth.activate")}
              </Button>
            </div>
          )}

          <section className="space-y-2">
            {onCvRow && (
              <p
                className="truncate text-xs text-[var(--as-muted-fg)]"
                data-testid="synth-editor-preview"
              >
                <span
                  className={
                    onCvRow.stale ? "text-amber-700" : "text-[var(--as-fg)]"
                  }
                >
                  {t("cvSynth.editor.onCvNow", { defaultValue: "On the CV now" })}:
                </span>{" "}
                {currentText || "—"}
              </p>
            )}
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-[var(--as-muted-fg)]">
                {t("cvSynth.editor.textLabel")}
              </span>
              {slotRows.length > 0 && (
                <div className="flex items-center gap-1">
                  {compareOpen ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid="synth-editor-compare-close"
                      onClick={() => setCompareOpen(false)}
                    >
                      <List className="h-3.5 w-3.5" /> {t("cvSynth.editor.closeCompare", { defaultValue: "Close compare" })}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid="synth-editor-compare-open"
                      onClick={() => setCompareOpen(true)}
                    >
                      <List className="h-3 w-3" /> {t("cvSynth.editor.compare", { defaultValue: "Compare" })}{" "}
                      <span className="tabular-nums">({slotRows.length})</span>
                    </Button>
                  )}
                  {slotRows.length > 1 && (
                    <>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label="Previous variant"
                        data-testid="synth-editor-slot-prev"
                        onClick={() => stepSlot(-1)}
                      >
                        <ChevronLeft className="h-3.5 w-3.5" />
                      </Button>
                      <span
                        className="text-[11px] tabular-nums text-[var(--as-muted-fg)]"
                        data-testid="synth-editor-slot-pos"
                      >
                        {slotPos + 1}/{slotRows.length}
                      </span>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label="Next variant"
                        data-testid="synth-editor-slot-next"
                        onClick={() => stepSlot(1)}
                      >
                        <ChevronRight className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  )}
                </div>
              )}
            </div>
            {compareOpen ? (
              <div
                className="max-h-40 space-y-1 overflow-y-auto rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-2"
                data-testid="synth-editor-compare-list"
              >
                {slotRows.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors ${
                      loadedId === row.id
                        ? "bg-[color-mix(in_srgb,var(--as-accent)_10%,transparent)]"
                        : "hover:bg-[var(--as-muted)]"
                    }`}
                    data-testid={`synth-editor-compare-row-${row.id}`}
                    onClick={() => {
                      setLoadedId(row.id);
                      setDescription(row.payload?.description ?? "");
                      {
                        const texts = textsOf(row.payload);
                        setBullets(texts.length ? texts : [""]);
                      }
                      setLanguage(row.voice?.language ?? defaultLanguage);
                      setPostingId(row.target_posting_id ?? "");
                    }}
                  >
                    <span
                      className={`shrink-0 rounded-full px-1.5 text-[10px] font-medium ${
                        row.status === "active"
                          ? "bg-[color-mix(in_srgb,var(--as-accent)_14%,transparent)] text-[var(--as-accent)]"
                          : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
                      }`}
                    >
                      {row.status}
                    </span>
                    {row.stale && (
                      <span className="shrink-0 rounded-full bg-amber-100 px-1.5 text-[10px] font-medium text-amber-800">
                        stale
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs text-[var(--as-muted-fg)]">
                      {variantTextOf(row.payload)}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <CvRichTextEditor
                value={description}
                onChange={setDescription}
                ariaLabel={t("cvSynth.editor.textLabel")}
                testId="synth-editor-description-input"
              />
            )}
          </section>

          <section className="space-y-1">
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("cvSynth.editor.bulletsLabel")}
            </span>
            <div className="space-y-1.5" data-testid="synth-editor-bullets">
              {bullets.map((bullet, index) => (
                <div key={index} className="flex items-center gap-1">
                  <input
                    value={bullet}
                    placeholder={t("cvSynth.editor.bulletPlaceholder")}
                    aria-label={`${t("cvSynth.editor.bulletsLabel")} ${index + 1}`}
                    data-testid={`synth-editor-bullet-${index}`}
                    onChange={(event) =>
                      setBullets((current) =>
                        current.map((entry, position) =>
                          position === index ? event.target.value : entry,
                        ),
                      )
                    }
                    className={FIELD_CLASS}
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove bullet ${index + 1}`}
                    data-testid={`synth-editor-bullet-remove-${index}`}
                    onClick={() =>
                      setBullets((current) =>
                        current.length > 1
                          ? current.filter((_entry, position) => position !== index)
                          : [""],
                      )
                    }
                    className="shrink-0 text-[var(--as-muted-fg)]"
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
              <Button
                size="sm"
                variant="ghost"
                type="button"
                data-testid="synth-editor-bullet-add"
                onClick={() => setBullets((current) => [...current, ""])}
              >
                <Plus className="h-3 w-3" /> {t("cvSynth.editor.bulletAdd")}
              </Button>
            </div>
          </section>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <section className="space-y-1">
              <span className="text-xs text-[var(--as-muted-fg)]">
                {t("cvSynth.editor.variantKeyLabel")}
              </span>
              <input
                value={variantKey}
                onChange={(event) => setVariantKey(event.target.value)}
                aria-label={t("cvSynth.editor.variantKeyLabel")}
                data-testid="synth-editor-key-input"
                className={FIELD_CLASS}
              />
            </section>
            <section className="space-y-1">
              <span className="text-xs text-[var(--as-muted-fg)]">
                {t("cvSynth.editor.languageLabel")}
              </span>
              <select
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                aria-label={t("cvSynth.editor.languageLabel")}
                data-testid="synth-editor-language-input"
                className={`${FIELD_CLASS} cursor-pointer`}
              >
                {["en", "de", "fr", "es", "it", "el"].map((code) => (
                  <option key={code} value={code}>
                    {code.toUpperCase()}
                  </option>
                ))}
              </select>
              {editing ? (
                initial?.target_posting_id && savedPostings.length > 0 ? (
                  <p className="text-[11px] text-[var(--as-muted-fg)]">
                    {savedPostings.find((posting) => posting.id === initial.target_posting_id)
                      ?.title ?? t("cvSynth.editor.postingAny")}
                  </p>
                ) : null
              ) : (
                savedPostings.length > 0 && (
                  <select
                    value={String(postingId ?? "")}
                    onChange={(event) => setPostingId(event.target.value)}
                    aria-label={t("cvSynth.editor.postingLabel")}
                    data-testid="synth-editor-posting-input"
                    className={`${FIELD_CLASS} cursor-pointer`}
                  >
                    <option value="">{t("cvSynth.editor.postingAny")}</option>
                    {savedPostings.map((posting) => (
                      <option key={posting.id} value={posting.id}>
                        {posting.title}
                      </option>
                    ))}
                  </select>
                )
              )}
              <p className="text-[11px] text-[var(--as-muted-fg)]">
                {t("cvSynth.editor.languageHint")}
              </p>
            </section>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-[var(--as-border)] px-6 py-4">
          <Button variant="outline" onClick={onClose} data-testid="synth-editor-cancel">
            {t("common.cancel")}
          </Button>
          <Button
            disabled={!canSave || busy}
            data-testid="synth-editor-save"
            onClick={() => void save()}
          >
            {editing ? t("common.save") : t("cvSynth.editor.create")}
          </Button>
          {onUseSaved && (
            <Button
              disabled={!canSave || busy}
              data-testid="synth-editor-save-use"
              onClick={() => void saveAndUse()}
            >
              {t("cvSynth.editor.saveAndUse", { defaultValue: "Save & use this" })}
            </Button>
          )}
        </div>
      </ModalContent>
    </Modal>
  );
}