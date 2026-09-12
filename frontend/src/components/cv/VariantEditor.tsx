import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";
import {
  Button,
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import type { CvSynthItem } from "@/types/cv";
import type { CvContextSourceOut } from "@/types/cv";

const MAX_REFS = 5;

export interface VariantEditorBody {
  refs: { source_key: string; item_id: string }[];
  scope: "item" | "summary";
  payload: { description: string; bullets: string[] };
  variant_key: string;
  target_posting_id?: string | null;
  voice: { language: string };
}

interface VariantEditorProps {
  open: boolean;
  sources: CvContextSourceOut[];
  savedPostings?: { id: string; title: string }[];
  initial?: CvSynthItem | null;
  defaultLanguage?: string;
  defaultSourceKey?: string;
  busy?: boolean;
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

const FIELD_CLASS =
  "w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--as-accent)]";

export function VariantEditor({
  open,
  sources,
  savedPostings = [],
  initial = null,
  defaultLanguage = "en",
  defaultSourceKey,
  busy = false,
  onClose,
  onSubmit,
}: VariantEditorProps) {
  const { t } = useTranslation();
  const editing = initial !== null;
  const [refs, setRefs] = useState<string[]>(
    initial
      ? initial.source_refs.map((ref) => refKey(ref.source_key, ref.item_id))
      : defaultSourceKey && sources.length > 0
        ? sources
            .filter((source) => source.key === defaultSourceKey)
            .flatMap((source) =>
              (source.items ?? []).slice(0, 1).map((item) => refKey(source.key, item.item_id)),
            )
        : []
  );
  const [description, setDescription] = useState(initial?.payload.description ?? "");
  const [bullets, setBullets] = useState<string[]>(() =>
    initial?.payload.bullets?.length ? initial.payload.bullets : [""],
  );
  const [variantKey, setVariantKey] = useState(initial?.variant_key ?? "default");
  const [language, setLanguage] = useState(
    initial?.voice.language ?? defaultLanguage
  );
  const [postingId, setPostingId] = useState(initial?.target_posting_id ?? "");

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
  const optionCount = groupedOptions.reduce(
    (total, group) => total + group.options.length,
    0,
  );

  const hasText =
    description.trim() !== "" || bullets.some((bullet) => bullet.trim() !== "");
  const canSave = hasText && refs.length > 0;

  async function save() {
    if (!canSave) return;
    const isSummary = refs.every((key) => key.startsWith("summary:"));
    await onSubmit({
      refs: toOptions(refs),
      scope: isSummary ? "summary" : "item",
      payload: {
        description: description.trim(),
        bullets: bullets.map((bullet) => bullet.trim()).filter(Boolean),
      },
      variant_key: variantKey.trim() || "default",
      target_posting_id: postingId || null,
      voice: { language },
    });
  }

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
            <div
              className="flex items-center gap-2 rounded-lg bg-[var(--as-muted)] px-3 py-2 text-xs text-[var(--as-muted-fg)]"
              data-testid="synth-editor-refs-readonly"
            >
              {initial?.source_refs.map((ref) => (
                <span
                  key={`${ref.source_key}-${ref.item_id}`}
                  className="rounded-full border border-[var(--as-border)] px-2 py-0.5"
                >
                  {ref.source_key}
                </span>
              ))}
              <span className="flex-1">{t("cvSynth.editor.refsReadonly")}</span>
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

          <section className="space-y-1">
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("cvSynth.editor.textLabel")}
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              aria-label={t("cvSynth.editor.textLabel")}
              data-testid="synth-editor-description-input"
              rows={4}
              className={`${FIELD_CLASS} resize-y leading-relaxed`}
            />
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
        </div>
      </ModalContent>
    </Modal>
  );
}
