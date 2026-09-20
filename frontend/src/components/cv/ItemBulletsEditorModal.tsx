import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Plus, RotateCcw, Sparkles, X } from "lucide-react";
import {
  Button,
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalTitle,
} from "@/components/ui";
import type { CvSynthBullet } from "@/types/cv";

export interface BulletsProposal {
  bullets: string[];
}

interface ItemBulletsEditorModalProps {
  sourceKey: string;
  itemId: string;
  /** Rendered item head lines (title/org), from the snapshot row. */
  head: { title: string; org: string };
  /** The pinned bullets variant's list ("Edited for this CV"). */
  override: CvSynthBullet[] | null;
  /** The resolved base (what renders now: variant bullets when pinned,
   * else the profile's). */
  base: CvSynthBullet[];
  /** AI-proposed bullets (plan 106 slice 4), shown as ✓/✕ chips. */
  proposal?: BulletsProposal | null;
  onProposalConsumed: () => void;
  /** Plan 106 slice 5: draft bullets from the item's evidence
   * (the `bullet` AI action). Resolves replacement bullet lines. */
  onGenerate?: () => Promise<string[]>;
  /** Persists the full list as the bullets variant (create + pin, or
   * patch the pinned one). */
  onSave: (entries: CvSynthBullet[]) => void;
  /** Unpins the bullets variant — the CV renders profile text again. */
  onReset: () => void;
  onClose: () => void;
}

const MAX_BULLETS = 12;

/** Plan 106 AD3/AD5/AD6: the bullets editor (two-layer model). Edits the
 * pinned bullets VARIANT against the resolved base; AI proposals ride
 * ephemeral ✓/✕ chips and never write until confirmed. */
export function ItemBulletsEditorModal({
  sourceKey,
  itemId,
  head,
  override,
  base,
  proposal = null,
  onProposalConsumed,
  onGenerate,
  onSave,
  onReset,
  onClose,
}: ItemBulletsEditorModalProps) {
  const { t } = useTranslation();
  const initial = useMemo(
    () => (override ?? base).map((entry) => (entry.text ?? "").trim()),
    [override, base]
  );
  const baseTexts = useMemo(
    () => base.map((entry) => (entry.text ?? "").trim()),
    [base]
  );
  const [bullets, setBullets] = useState<string[]>(() =>
    initial.length ? initial : [""]
  );
  const [generated, setGenerated] = useState<string[] | null>(null);
  const [generating, setGenerating] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const pendingProposals = useMemo(() => {
    const source = generated ?? proposal?.bullets ?? [];
    return source.map((text) => text.trim()).filter(Boolean);
  }, [generated, proposal]);
  const dirty =
    pendingProposals.length > 0 ||
    bullets.join("\u0000") !== initial.join("\u0000");

  const requestClose = () => {
    if (dirty) setConfirmDiscard(true);
    else onClose();
  };

  const setText = (index: number, text: string) =>
    setBullets((prev) => prev.map((b, i) => (i === index ? text : b)));
  const remove = (index: number) =>
    setBullets((prev) =>
      prev.length === 1 ? [""] : prev.filter((_, i) => i !== index)
    );
  const move = (index: number, delta: -1 | 1) =>
    setBullets((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });

  const cleaned = () =>
    bullets.map((b) => b.trim()).filter(Boolean);

  const save = () => {
    onSave(cleaned().map((text) => ({ text })));
  };

  const clearProposals = () => {
    setGenerated(null);
    onProposalConsumed();
  };

  const confirmProposals = () => {
    setBullets((prev) => {
      const kept = prev.map((b) => b.trim()).filter(Boolean);
      return [...kept, ...pendingProposals].slice(0, MAX_BULLETS);
    });
    clearProposals();
  };

  const generate = async () => {
    if (!onGenerate || generating) return;
    if (
      dirty &&
      !window.confirm(
        t("cvBuilder.generateOverwrite", {
          defaultValue:
            "Generating replaces your unsaved edits — continue?",
        })
      )
    ) {
      return;
    }
    setGenerating(true);
    try {
      const bullets = (await onGenerate()).map((b) => b.trim()).filter(Boolean);
      setGenerated(bullets.length ? bullets : null);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  };

  const reset = () => {
    setConfirmReset(false);
    setBullets(baseTexts.length ? baseTexts : [""]);
    onReset();
  };

  return (
    <Modal open onOpenChange={(open) => !open && requestClose()}>
      <ModalContent
        size="xl"
        aria-describedby={undefined}
        aria-label={t("cvBuilder.bulletsTitle")}
        data-testid="bullets-editor-modal"
        className="max-w-none max-w-2xl"
      >
        <ModalTitle className="sr-only">
          {t("cvBuilder.bulletsTitle")}
        </ModalTitle>
        <div className="flex flex-col gap-3 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p
                className="truncate text-sm font-semibold text-[var(--as-fg)]"
                data-testid="bullets-editor-head"
              >
                {[head.title, head.org].filter(Boolean).join(" · ") ||
                  `${sourceKey}:${itemId}`}
              </p>
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("cvBuilder.bulletsSubtitle")}
              </p>
            </div>
            {override !== null && (
              <span
                className="shrink-0 rounded-full bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-accent)]"
                data-testid="bullets-edited-chip"
              >
                {t("cvBuilder.editedForThisCv")}
              </span>
            )}
          </div>

          {pendingProposals.length > 0 && (
            <div
              className="rounded-xl border border-dashed border-[var(--as-accent)] p-3"
              data-testid="bullet-proposals"
            >
              <p className="mb-1.5 text-xs font-semibold text-[var(--as-fg)]">
                {t("cvBuilder.proposedBullets")}
              </p>
              <ul className="space-y-1">
                {pendingProposals.map((text, index) => (
                  <li
                    key={index}
                    className="flex items-start gap-2 rounded px-1 py-1 text-sm hover:bg-[var(--as-muted)]"
                    data-testid={`bullet-chip-${index}`}
                  >
                    <span className="min-w-0 flex-1">{text}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex justify-end gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearProposals}
                  data-testid="bullet-chips-discard"
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={confirmProposals}
                  data-testid="bullet-chips-confirm"
                >
                  {t("cvBuilder.keepSelected")}
                </Button>
              </div>
            </div>
          )}

          <div className="space-y-1.5" data-testid="bullets-editor-list">
            {bullets.map((bullet, index) => (
              <div key={index} className="flex items-center gap-1.5">
                <input
                  value={bullet}
                  onChange={(e) => setText(index, e.target.value)}
                  maxLength={500}
                  aria-label={`${t("cvBuilder.bulletsLabel")} ${index + 1}`}
                  data-testid={`bullets-row-${index}`}
                  className={FIELD_CLASS}
                />
                <button
                  type="button"
                  aria-label={t("cvBuilder.moveUp", { index: index + 1 })}
                  disabled={index === 0}
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:opacity-40"
                  data-testid={`bullets-up-${index}`}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                </button>
                <button
                  type="button"
                  aria-label={t("cvBuilder.moveDown", { index: index + 1 })}
                  disabled={index === bullets.length - 1}
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:opacity-40"
                  data-testid={`bullets-down-${index}`}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                </button>
                <button
                  type="button"
                  aria-label={t("cvBuilder.removeBullet", { index: index + 1 })}
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-danger)]"
                  data-testid={`bullets-remove-${index}`}
                  onClick={() => remove(index)}
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="flex items-center gap-1 rounded p-1 text-xs text-[var(--as-accent)] transition-colors hover:underline"
              data-testid="bullets-add"
              onClick={() => setBullets((prev) => [...prev, ""])}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden />
              {t("cvBuilder.addBullet")}
            </button>
          </div>
        </div>
        <div className="sticky bottom-0 flex items-center justify-between gap-2 border-t border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-3">
          <div className="flex items-center gap-2">
            {onGenerate && (
              <Button
                variant="outline"
                size="sm"
                disabled={generating}
                onClick={() => void generate()}
                data-testid="bullets-editor-generate"
              >
                <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {generating
                  ? t("common.saving", { defaultValue: "Working…" })
                  : t("cvBuilder.generateBullets")}
              </Button>
            )}
          </div>
          {override !== null ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmReset(true)}
              data-testid="bullets-editor-reset"
            >
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
              {t("cvBuilder.resetToProfile")}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={requestClose} data-testid="bullets-editor-cancel">
              {t("common.cancel")}
            </Button>
            <Button variant="default" onClick={save} data-testid="bullets-editor-save">
              {t("common.save")}
            </Button>
          </div>
        </div>
      </ModalContent>
      <ConfirmationModal
        open={confirmDiscard}
        onOpenChange={(open) => !open && setConfirmDiscard(false)}
        title={t("experience.discardTitle")}
        description={t("experience.discardBody")}
        confirmLabel={t("experience.discard")}
        destructive
        onConfirm={() => {
          setConfirmDiscard(false);
          onClose();
        }}
      />
      <ConfirmationModal
        open={confirmReset}
        onOpenChange={(open) => !open && setConfirmReset(false)}
        title={t("cvBuilder.resetTitle")}
        description={t("cvBuilder.resetBody")}
        confirmLabel={t("cvBuilder.resetToProfile")}
        destructive
        onConfirm={reset}
      />
    </Modal>
  );
}

const FIELD_CLASS =
  "w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--as-accent)]";
