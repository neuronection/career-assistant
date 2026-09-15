import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Layers,
  LayoutList,
  Palette,
  X,
} from "lucide-react";
import { Button } from "@/components/ui";
import { PhotoPicker } from "@/components/cv/PhotoPicker";
import { SectionsPanel } from "@/components/cv/SectionsPanel";
import { DesignTokenEditor } from "@/components/cv/DesignTokenEditor";
import { SelectField } from "@/components/cv/formPrimitives";
import { useTranslation } from "react-i18next";
import {
  LetterDraftSlideOver,
} from "@/components/cv/LetterDraftSlideOver";
import {
  LetterSectionsEditor,
  type LetterProps,
} from "@/components/cv/LetterSectionsEditor";
import type { GalleryPhoto } from "@/api/mePhoto";
import type { CvArea, CvAreaId } from "@/components/cv/areas";
import type {
  CoverLetterSuggestionOut,
  CvBlock,
  CvProposal,
  CvSuggestionOut,
} from "@/types/cv";
import type { CvDesignTokens, CvTemplateSummary } from "@/types/cvTemplate";
import type { CvAssistantCritique } from "@/types/cvAssistant";
import { CritiqueCard } from "@/components/cv/CritiqueCard";
import { apiDetail } from "@/api/client";

export type InspectorTab = "context" | "design" | "sections";

const TABS: { id: InspectorTab; label: string; icon: typeof Layers }[] = [
  { id: "context", label: "Context", icon: Layers },
  { id: "design", label: "Design", icon: Palette },
  { id: "sections", label: "Sections", icon: LayoutList },
];

interface InspectorPanelProps {
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  /** The context slot: ContextPanel (resume) / LetterBriefPanel (letter). */
  context?: React.ReactNode;
  mode?: "resume" | "cover_letter";
  letterProps: LetterProps | null;
  onUpdateLetterProps: (patch: Record<string, unknown>) => void;
  letterSuggestion: CoverLetterSuggestionOut | null;
  onCloseLetterSuggestion: () => void;
  onApplyLetterDraft: (
    paragraphs: string[],
    draft: CoverLetterSuggestionOut["draft"]
  ) => void;

  templates: CvTemplateSummary[];
  templateId: string;
  onTemplate: (templateId: string) => void;
  onBrowseTemplates: () => void;
  onCustomizeTemplate: () => void;

  design: CvDesignTokens | null;
  designTemplateMeta: { id: string; title: string; owned: boolean; ats_safe: boolean } | null;
  designDirty: boolean;
  onDesignChange: (patch: Partial<CvDesignTokens>) => void;
  onDesignApply: () => void;
  onDesignReset: () => void;
  onPageSize: (pageSize: string) => void;
  pageSize: string;
  photos: GalleryPhoto[];
  photoId: string;
  onPhoto: (photoId: string) => void;
  photoUploading: boolean;
  onUploadPhoto: (file: File) => void;
  onError: (message: string) => void;

  blocks: CvBlock[];
  areas?: CvArea[];
  skillOptions?: { id: string; label: string }[];
  itemOptions?: Record<string, { id: string; label: string }[]>;
  synthOptions?: { id: string; label: string; stale?: boolean }[];
  onDuplicateBlock: (index: number) => void;
  onAddBlock: (kind: string, area?: CvAreaId) => void;
  onMoveBlock: (index: number, delta: number) => void;
  onAssignArea?: (index: number, area: CvAreaId) => void;
  onRemoveBlock: (index: number) => void;
  onUpdateBlockProps: (index: number, patch: Record<string, unknown>) => void;
  onSetBlockHidden: (index: number, hidden: boolean) => void;
  dragIndexRef: { current: number | null };
  onDragReorder: (target: number) => void;

  busy: string;
  suggestion: CvSuggestionOut | null;
  onCloseSuggestion: () => void;
  onApplyProposal: (entry: CvProposal) => void;
}

function InspectorTabs({
  active,
  onChange,
}: {
  active: InspectorTab;
  onChange: (tab: InspectorTab) => void;
}) {
  const activeIndex = Math.max(
    0,
    TABS.findIndex((entry) => entry.id === active)
  );
  const handleKeyDown = (event: React.KeyboardEvent, index: number) => {
    const delta =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (!delta) return;
    event.preventDefault();
    const next = TABS[(index + delta + TABS.length) % TABS.length];
    onChange(next.id);
    const list = event.currentTarget.closest('[role="tablist"]');
    list?.querySelector<HTMLButtonElement>(`[data-testid="inspector-tab-${next.id}"]`)?.focus();
  };
  return (
    <div
      role="tablist"
      aria-label="Inspector panels"
      className="relative mb-2 grid auto-cols-fr grid-flow-col rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] p-0.5"
      data-testid="inspector-tab-menu"
    >
      <span
        aria-hidden
        className="cv-tab-thumb absolute inset-y-0.5 left-0.5 rounded-full border border-[var(--as-border)] bg-[var(--as-surface-raised)] shadow-sm"
        style={{
          width: `calc((100% - 4px) / ${TABS.length})`,
          transform: `translateX(${activeIndex * 100}%)`,
        }}
      />
      {TABS.map((entry, index) => {
        const selected = entry.id === active;
        const Icon = entry.icon;
        return (
          <button
            key={entry.id}
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            data-testid={`inspector-tab-${entry.id}`}
            onClick={() => onChange(entry.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`relative z-[1] flex cursor-pointer items-center justify-center gap-1 rounded-full px-1 py-1.5 text-xs font-medium transition-colors duration-150 ${
              selected
                ? "text-[var(--as-fg)]"
                : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            }`}
          >
            <Icon
              className={`h-3.5 w-3.5 ${selected ? "text-[var(--as-accent)]" : ""}`}
              aria-hidden
            />
            {entry.label}
          </button>
        );
      })}
    </div>
  );
}

export function InspectorPanel(props: InspectorPanelProps) {
  const { tab, onTabChange } = props;

  return (
    <div className="flex min-h-0 flex-col" data-testid="inspector-panel">
      <InspectorTabs active={tab} onChange={onTabChange} />

      <div
        key={tab}
        className={`cv-pane-enter min-h-0 flex-1 pr-0.5 ${
          tab === "design" ? "flex flex-col overflow-hidden" : "overflow-y-auto"
        }`}
        data-testid={`inspector-body-${tab}`}
      >
        {tab === "context" && (props.context ?? null)}
        {tab === "design" && <DesignTab {...props} />}
        {tab === "sections" &&
          (props.mode === "cover_letter" ? (
            props.letterProps && (
              <LetterSectionsEditor
                props={props.letterProps}
                onChange={props.onUpdateLetterProps}
              />
            )
          ) : (
            <SectionsPanel {...props} />
          ))}
      </div>

      {props.suggestion && (
        <ProposalsSlideOver
          suggestion={props.suggestion}
          onClose={props.onCloseSuggestion}
          onApply={props.onApplyProposal}
        />
      )}
      {props.letterSuggestion && (
        <LetterDraftSlideOver
          suggestion={props.letterSuggestion}
          busy={props.busy === "ai:cover_letter"}
          onClose={props.onCloseLetterSuggestion}
          onApply={props.onApplyLetterDraft}
        />
      )}
    </div>
  );
}

function DesignTab({
  templates,
  templateId,
  onTemplate,
  onBrowseTemplates,
  onCustomizeTemplate,
  design,
  designTemplateMeta,
  designDirty,
  onDesignChange,
  onDesignApply,
  onDesignReset,
  onPageSize,
  pageSize,
  photos,
  photoId,
  onPhoto,
  photoUploading,
  onUploadPhoto,
  onError,
  mode,
}: InspectorPanelProps) {
  const { t } = useTranslation();
  const [reviewFiles, setReviewFiles] = useState<File[]>([]);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewCritique, setReviewCritique] = useState<CvAssistantCritique | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  if (!design) {
    return (
      <p className="text-sm text-[var(--as-muted-fg)]" data-testid="design-loading">
        {t("cvBuilder.templateLoading", { defaultValue: "Loading template…" })}
      </p>
    );
  }
  const runReview = async () => {
    if (!designTemplateMeta || reviewFiles.length === 0) return;
    setReviewBusy(true);
    setReviewNote("");
    try {
      const { reviewTemplatePages } = await import("@/api/cvTemplates");
      const out = await reviewTemplatePages(designTemplateMeta.id, reviewFiles);
      setReviewCritique(
        out.critique
          ? {
              summary: out.critique.summary,
              issues: out.critique.issues as CvAssistantCritique["issues"],
              safe_token_fixes: out.critique.safe_token_fixes,
            }
          : null
      );
      setReviewNote(out.note ?? "");
    } catch (err) {
      onError(apiDetail(err));
    } finally {
      setReviewBusy(false);
    }
  };
  const sectionLabel =
    "text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-0.5"
        data-testid="design-scroll"
      >
        <section className="space-y-1.5">
          <h3 className={sectionLabel}>Template</h3>
          {designTemplateMeta && (
            <div
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2 text-xs"
              data-testid="template-meta"
            >
              <p className="font-medium text-[var(--as-fg)]">{designTemplateMeta.title}</p>
              <p className="mt-0.5 text-[var(--as-muted-fg)]">
                {designTemplateMeta.owned
                  ? t("cvBuilder.templateOwned", { defaultValue: "Your customized template" })
                  : t("cvBuilder.templateBank", { defaultValue: "Applying changes creates your own copy" })}
                {designTemplateMeta.ats_safe ? "" : ` · ${t("cvBuilder.notAtsSafe", { defaultValue: "not ATS-safe" })}`}
              </p>
            </div>
          )}
          <select
            aria-label="CV template"
            className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-sm"
            value={templateId}
            onChange={(event) => onTemplate(event.target.value)}
            data-testid="template-picker"
          >
            <option value="">Bank default</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.title}
                {template.ats_safe ? "" : " (not ATS-safe)"}
              </option>
            ))}
          </select>
          <div className="flex gap-1.5">
            <Button variant="outline" size="sm" className="flex-1" onClick={onBrowseTemplates} data-testid="browse-templates">
              Browse…
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={onCustomizeTemplate}
              disabled={!templateId}
              title={templateId ? "Open this template in the style editor" : "Pick a template first"}
              data-testid="customize-template"
            >
              Customize
            </Button>
          </div>
        </section>

        {mode !== "cover_letter" && (
          <section className="space-y-1.5">
            <h3 className={sectionLabel}>Photo</h3>
            <PhotoPicker
              photos={photos}
              photoId={photoId}
              uploading={photoUploading}
              onSelect={onPhoto}
              onUpload={onUploadPhoto}
              onError={onError}
            />
          </section>
        )}

        <section className="space-y-1.5">
          <h3 className={sectionLabel}>Style</h3>
          <DesignTokenEditor design={design} onChange={onDesignChange} />
          <SelectField
            label={t("cvBuilder.pageSize", { defaultValue: "Page size" })}
            value={pageSize}
            onChange={onPageSize}
            options={[
              { value: "a4", label: "A4" },
              { value: "letter", label: "Letter" },
            ]}
            testId="page-size-select"
          />
        </section>

        {designTemplateMeta && (
          <div className="space-y-2 rounded-lg border border-[var(--as-border)] p-2.5" data-testid="printed-review">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("cvBuilder.printedReview", { defaultValue: "Check a printed copy" })}
            </p>
            <input
              type="file"
              accept="image/png,image/jpeg"
              multiple
              aria-label={t("cvBuilder.printedReviewUpload", { defaultValue: "Upload printed page photos" })}
              onChange={(event) => setReviewFiles(Array.from(event.target.files ?? []))}
              data-testid="printed-review-input"
            />
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              disabled={reviewBusy || reviewFiles.length === 0}
              onClick={() => void runReview()}
              data-testid="printed-review-run"
            >
              {reviewBusy
                ? t("cvBuilder.printedReviewRunning", { defaultValue: "Reviewing…" })
                : t("cvBuilder.printedReviewRun", { defaultValue: "Review pages" })}
            </Button>
            {reviewNote && (
              <p className="text-xs text-[var(--as-muted-fg)]" data-testid="printed-review-note">
                {reviewNote}
              </p>
            )}
            {reviewCritique && (
              <CritiqueCard critique={reviewCritique} />
            )}
          </div>
        )}
      </div>
      <div
        className="mt-2 flex shrink-0 items-center gap-2 border-t border-[var(--as-border)] bg-[var(--as-surface)] pt-2"
        data-testid="design-footer"
      >
        <Button
          variant="default"
          size="sm"
          className="flex-1"
          disabled={!designDirty}
          onClick={onDesignApply}
          data-testid="apply-design"
        >
          {designDirty
            ? t("cvBuilder.applyDesign", { defaultValue: "Apply changes" })
            : t("cvBuilder.designSaved", { defaultValue: "Saved" })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={!designDirty}
          onClick={onDesignReset}
          data-testid="reset-design"
        >
          {t("common.reset", { defaultValue: "Reset" })}
        </Button>
      </div>
    </div>
  );
}

function ProposalsSlideOver({
  suggestion,
  onClose,
  onApply,
}: {
  suggestion: CvSuggestionOut;
  onClose: () => void;
  onApply: (entry: CvProposal) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLButtonElement>("[data-testid='apply-proposal']")
      ?.focus();
  }, []);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>("[data-testid='apply-proposal']") ?? []
    );
    if (buttons.length === 0) return;
    event.preventDefault();
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "ArrowDown"
        ? Math.min(current + 1, buttons.length - 1)
        : Math.max(current - 1, 0);
    buttons[current === -1 ? 0 : next]?.focus();
  };

  return (
    <div className="fixed inset-0 z-[var(--as-z-modal)]">
      <div
        className="absolute inset-0 bg-black/20"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-label={`${suggestion.action} proposals — review then apply`}
        onKeyDown={handleKeyDown}
        className="cv-slideover-in absolute inset-y-0 right-0 flex w-full max-w-sm flex-col border-l border-[var(--as-border)] bg-[var(--as-surface)] shadow-xl"
        data-testid="proposals-slideover"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--as-border)] p-3">
          <p className="text-xs font-semibold uppercase text-[var(--as-muted-fg)]">
            {suggestion.action} proposals — ↑/↓ + Enter to apply
          </p>
          <button
            type="button"
            aria-label="Close proposals"
            onClick={onClose}
            className="rounded p-0.5 hover:bg-[var(--as-muted)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3" data-testid="proposals">
          {suggestion.gaps.map((gap) => (
            <p key={gap.source_key} className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2 text-xs">
              <AlertTriangle className="mr-1 inline h-3 w-3 text-amber-500" />
              {gap.message}
            </p>
          ))}
          {suggestion.proposals.map((entry, index) => (
            <div
              key={index}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2.5"
              data-testid="proposal-card"
            >
              <p className="text-sm">{entry.proposal.text}</p>
              {entry.proposal.rationale && (
                <p className="mt-1 text-xs text-[var(--as-muted-fg)]">{entry.proposal.rationale}</p>
              )}
              {!entry.verified && (
                <p className="mt-1 text-xs text-amber-700">Flagged: cites items not in this CV&apos;s context.</p>
              )}
              <div className="mt-2 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="apply-proposal"
                  disabled={!entry.verified}
                  onClick={() => onApply(entry.proposal)}
                >
                  <Check className="mr-1 h-3 w-3" /> Apply
                </Button>
              </div>
            </div>
          ))}
          {suggestion.proposals.length === 0 && suggestion.gaps.length === 0 && (
            <p className="text-xs text-[var(--as-muted-fg)]">No proposals for this action.</p>
          )}
        </div>
      </div>
    </div>
  );
}

