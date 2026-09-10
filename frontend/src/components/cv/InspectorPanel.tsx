import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Eye,
  Languages,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import {
  AiActionsDropdown,
  PopoverAnchor,
  type AiAction,
} from "@neuronection/assistant-ui";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { PhotoPicker } from "@/components/cv/PhotoPicker";
import { SectionsPanel } from "@/components/cv/SectionsPanel";
import {
  LetterDraftSlideOver,
} from "@/components/cv/LetterDraftSlideOver";
import {
  LetterSectionsEditor,
  type LetterProps,
} from "@/components/cv/LetterSectionsEditor";
import type { GalleryPhoto } from "@/api/mePhoto";
import type {
  CoverLetterSuggestionOut,
  CvBlock,
  CvLintReport,
  CvProposal,
  CvSuggestionOut,
} from "@/types/cv";
import type { CvTemplateSummary } from "@/types/cvTemplate";

export type InspectorTab = "design" | "sections" | "ai" | "lint";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "design", label: "Design" },
  { id: "sections", label: "Sections" },
  { id: "ai", label: "AI" },
  { id: "lint", label: "Lint" },
];

interface InspectorPanelProps {
  tab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  mode?: "resume" | "cover_letter";
  letterProps: LetterProps | null;
  onUpdateLetterProps: (patch: Record<string, unknown>) => void;
  letterSuggestion: CoverLetterSuggestionOut | null;
  onCloseLetterSuggestion: () => void;
  onApplyLetterDraft: (
    paragraphs: string[],
    draft: CoverLetterSuggestionOut["draft"]
  ) => void;
  onDraftLetter: () => void;
  hasTargetPosting: boolean;

  templates: CvTemplateSummary[];
  templateId: string;
  onTemplate: (templateId: string) => void;
  onBrowseTemplates: () => void;
  onCustomizeTemplate: () => void;
  photos: GalleryPhoto[];
  photoId: string;
  onPhoto: (photoId: string) => void;
  photoUploading: boolean;
  onUploadPhoto: (file: File) => void;
  onError: (message: string) => void;

  blocks: CvBlock[];
  onDuplicateBlock: (index: number) => void;
  onAddBlock: (kind: string) => void;
  onMoveBlock: (index: number, delta: number) => void;
  onRemoveBlock: (index: number) => void;
  onUpdateBlockProps: (index: number, patch: Record<string, unknown>) => void;
  dragIndexRef: { current: number | null };
  onDragReorder: (target: number) => void;

  busy: string;
  tone: string;
  onToneChange: (tone: string) => void;
  length: string;
  onLengthChange: (length: string) => void;
  savedPostings: { id: string; title: string; org: string }[];
  tailorPostingId: string;
  onTailorPostingChange: (postingId: string) => void;
  onTailorRequest: () => void;
  translateLabel: string;
  onRunAction: (action: "summary" | "bullet" | "gaps" | "compaction" | "tailor" | "translate") => void;
  onDuplicate: () => void;
  suggestion: CvSuggestionOut | null;
  onCloseSuggestion: () => void;
  onApplyProposal: (entry: CvProposal) => void;

  lint: CvLintReport | null;
}

export function InspectorPanel(props: InspectorPanelProps) {
  const { tab, onTabChange } = props;

  return (
    <div className="flex min-h-0 flex-col" data-testid="inspector-panel">
      <div
        role="tablist"
        aria-label="Inspector panels"
        className="mb-2 flex shrink-0 gap-1 rounded-lg bg-[var(--as-muted)] p-1"
      >
        {TABS.map((entry) => (
          <button
            key={entry.id}
            role="tab"
            type="button"
            aria-selected={tab === entry.id}
            onClick={() => onTabChange(entry.id)}
            data-testid={`inspector-tab-${entry.id}`}
            className={`flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors duration-150 ${
              tab === entry.id
                ? "bg-[var(--as-surface)] text-[var(--as-fg)] shadow-sm"
                : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div
        key={tab}
        className="cv-pane-enter min-h-0 flex-1 overflow-y-auto pr-0.5"
        data-testid={`inspector-body-${tab}`}
      >
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
        {tab === "ai" && <AiTab {...props} />}
        {tab === "lint" && <LintTab {...props} />}
      </div>
    </div>
  );
}

function DesignTab({
  templates,
  templateId,
  onTemplate,
  onBrowseTemplates,
  onCustomizeTemplate,
  photos,
  photoId,
  onPhoto,
  photoUploading,
  onUploadPhoto,
  onError,
  mode,
}: InspectorPanelProps) {
  return (
    <div className="space-y-4">
      <section className="space-y-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">Template</h3>
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
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">Profile photo</h3>
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
    </div>
  );
}

function AiTab(props: InspectorPanelProps) {
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [tailorOpen, setTailorOpen] = useState(false);
  if (props.mode === "cover_letter") return <LetterAiTab {...props} />;
  const {
    busy,
    tone,
    onToneChange,
    length,
    onLengthChange,
    savedPostings,
    tailorPostingId,
    onTailorPostingChange,
    onTailorRequest,
    translateLabel,
    onRunAction,
    onDuplicate,
    suggestion,
    onCloseSuggestion,
    onApplyProposal,
  } = props;

  return (
    <div className="space-y-3">
      <Popover open={tailorOpen} onOpenChange={setTailorOpen}>
        <PopoverAnchor asChild>
          <div>
            <AiActionsDropdown
              label="AI writing actions"
              title="AI writing actions"
              busy={busy.startsWith("ai:")}
              error={null}
              primaryAction={{ id: "summary", label: "Improve summary", icon: Sparkles }}
              actions={[
                { id: "compaction", label: "Tighten text", icon: Scissors },
                { id: "gaps", label: "Find gaps", icon: Eye },
                { id: "translate", label: translateLabel, icon: Languages },
                {
                  id: "tailor",
                  label: "Tailor to saved posting",
                  icon: Target,
                  description: tailorPostingId ? "Uses the selected posting" : "Pick a posting first",
                },
              ]}
              moreLabel="More AI actions"
              onAction={(action: AiAction) => {
                if (action.id === "tailor") {
                  setTailorOpen(true);
                  return;
                }
                onRunAction(action.id as "summary");
              }}
            />
          </div>
        </PopoverAnchor>
        <PopoverContent align="start" className="w-64 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            Tailor to posting
          </p>
          {savedPostings.length > 0 ? (
            <div className="space-y-1.5" data-testid="tailor-picker">
              <select
                aria-label="Target posting"
                className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-sm"
                value={tailorPostingId}
                onChange={(event) => onTailorPostingChange(event.target.value)}
              >
                <option value="">Pick a posting…</option>
                {savedPostings.map((posting) => (
                  <option key={posting.id} value={posting.id}>
                    {posting.title}
                    {posting.org ? ` — ${posting.org}` : ""}
                  </option>
                ))}
              </select>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={!tailorPostingId || busy === "ai:tailor"}
                onClick={onTailorRequest}
                data-testid="tailor-run"
              >
                Tailor
              </Button>
            </div>
          ) : (
            <p className="text-xs text-[var(--as-muted-fg)]">
              Save a posting in Explore to tailor this CV against it.
            </p>
          )}
        </PopoverContent>
      </Popover>

      <Popover open={presetsOpen} onOpenChange={setPresetsOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            data-testid="ai-presets"
            aria-expanded={presetsOpen}
            className="inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
            Tone: {tone || "default"} · Length: {length || "default"}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-56 space-y-2" data-testid="ai-presets-panel">
          <label className="block space-y-1 text-xs">
            <span className="text-[var(--as-muted-fg)]">Tone</span>
            <select
              aria-label="Tone"
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
              value={tone}
              onChange={(event) => onToneChange(event.target.value)}
              data-testid="tone-select"
            >
              <option value="">default</option>
              {["professional", "warm", "concise", "confident"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-xs">
            <span className="text-[var(--as-muted-fg)]">Length</span>
            <select
              aria-label="Length"
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
              value={length}
              onChange={(event) => onLengthChange(event.target.value)}
              data-testid="length-select"
            >
              <option value="">default</option>
              {["short", "medium", "long"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </PopoverContent>
      </Popover>

      <Button variant="outline" size="sm" className="w-full" onClick={onDuplicate}>
        Duplicate CV
      </Button>

      {suggestion && (
        <ProposalsSlideOver
          suggestion={suggestion}
          onClose={onCloseSuggestion}
          onApply={onApplyProposal}
        />
      )}
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

function PresetsPopover({
  tone,
  onToneChange,
  length,
  onLengthChange,
}: {
  tone: string;
  onToneChange: (tone: string) => void;
  length: string;
  onLengthChange: (length: string) => void;
}) {
  const [presetsOpen, setPresetsOpen] = useState(false);
  return (
    <Popover open={presetsOpen} onOpenChange={setPresetsOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="ai-presets"
          aria-expanded={presetsOpen}
          className="inline-flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-xs text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          Tone: {tone || "default"} · Length: {length || "default"}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 space-y-2" data-testid="ai-presets-panel">
        <label className="block space-y-1 text-xs">
          <span className="text-[var(--as-muted-fg)]">Tone</span>
          <select
            aria-label="Tone"
            className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
            value={tone}
            onChange={(event) => onToneChange(event.target.value)}
            data-testid="tone-select"
          >
            <option value="">default</option>
            {["professional", "warm", "concise", "confident"].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1 text-xs">
          <span className="text-[var(--as-muted-fg)]">Length</span>
          <select
            aria-label="Length"
            className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
            value={length}
            onChange={(event) => onLengthChange(event.target.value)}
            data-testid="length-select"
          >
            <option value="">default</option>
            {["short", "medium", "long"].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </PopoverContent>
    </Popover>
  );
}

function LetterAiTab({
  busy,
  tone,
  onToneChange,
  length,
  onLengthChange,
  onDuplicate,
  letterSuggestion,
  onCloseLetterSuggestion,
  onApplyLetterDraft,
  onDraftLetter,
  hasTargetPosting,
}: InspectorPanelProps) {
  return (
    <div className="space-y-3">
      <Button
        className="w-full"
        disabled={!hasTargetPosting || busy === "ai:cover_letter"}
        onClick={onDraftLetter}
        data-testid="draft-letter"
      >
        <Sparkles className="mr-1 h-4 w-4" />
        {busy === "ai:cover_letter" ? "Drafting…" : "Draft with AI"}
      </Button>
      {!hasTargetPosting && (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="draft-needs-posting">
          This cover letter has no target posting yet — the draft grounds on
          the posting&apos;s requirements.
        </p>
      )}
      <p className="text-xs text-[var(--as-muted-fg)]">
        Drafts cite your profile evidence per paragraph; anything unbacked is
        flagged before it can be applied.
      </p>
      <PresetsPopover
        tone={tone}
        onToneChange={onToneChange}
        length={length}
        onLengthChange={onLengthChange}
      />
      <Button variant="outline" size="sm" className="w-full" onClick={onDuplicate}>
        Duplicate letter
      </Button>
      {letterSuggestion && (
        <LetterDraftSlideOver
          suggestion={letterSuggestion}
          busy={busy === "ai:cover_letter"}
          onClose={onCloseLetterSuggestion}
          onApply={onApplyLetterDraft}
        />
      )}
    </div>
  );
}

function LintTab({ lint }: InspectorPanelProps) {
  if (!lint) {
    return <p className="text-xs text-[var(--as-muted-fg)]">Lint runs once the preview is compiled.</p>;
  }
  return (
    <div data-testid="lint-panel">
      <ul className="space-y-1 text-xs">
        {lint.checks.map((check) => (
          <li
            key={check.id}
            className={
              check.level === "fail"
                ? "text-red-700"
                : check.level === "warn"
                  ? "text-amber-700"
                  : "text-[var(--as-muted-fg)]"
            }
          >
            {check.level === "pass" ? "✓" : "•"} {check.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
