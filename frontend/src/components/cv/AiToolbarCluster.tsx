import { useState } from "react";
import {
  AiActionsDropdown,
  PopoverAnchor,
  type AiAction,
} from "@neuronection/assistant-ui";
import {
  Eye,
  Languages,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Target,
} from "lucide-react";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";

const TONES = ["professional", "warm", "concise", "confident"];
const LENGTHS = ["short", "medium", "long"];

interface AiToolbarClusterProps {
  mode: "resume" | "cover_letter";
  busy: string;
  translateLabel: string;
  hasTargetPosting: boolean;
  savedPostings: { id: string; title: string; org: string }[];
  tailorPostingId: string;
  onTailorPostingChange: (postingId: string) => void;
  onTailorRequest: () => void;
  onRunAction: (
    action: "summary" | "bullet" | "gaps" | "compaction" | "tailor" | "translate"
  ) => void;
  onDraftLetter: () => void;
  tone: string;
  onToneChange: (tone: string) => void;
  length: string;
  onLengthChange: (length: string) => void;
}

function PresetsButton({
  tone,
  onToneChange,
  length,
  onLengthChange,
}: Pick<AiToolbarClusterProps, "tone" | "onToneChange" | "length" | "onLengthChange">) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          data-testid="ai-presets"
          aria-label="AI tone and length"
          title={`Tone: ${tone || "default"} · Length: ${length || "default"}`}
        >
          <SlidersHorizontal className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 space-y-2" data-testid="ai-presets-panel">
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
            {TONES.map((value) => (
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
            {LENGTHS.map((value) => (
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

export function AiToolbarCluster({
  mode,
  busy,
  translateLabel,
  hasTargetPosting,
  savedPostings,
  tailorPostingId,
  onTailorPostingChange,
  onTailorRequest,
  onRunAction,
  onDraftLetter,
  tone,
  onToneChange,
  length,
  onLengthChange,
}: AiToolbarClusterProps) {
  const [tailorOpen, setTailorOpen] = useState(false);

  if (mode === "cover_letter") {
    return (
      <div className="flex items-center gap-2" data-testid="ai-toolbar-cluster">
        <Button
          size="sm"
          disabled={!hasTargetPosting || busy === "ai:cover_letter"}
          onClick={onDraftLetter}
          data-testid="draft-letter"
          title={
            hasTargetPosting
              ? "Draft the letter with AI"
              : "This cover letter has no target posting yet — pick one in Explore"
          }
        >
          <Sparkles className="mr-1 h-4 w-4" />
          {busy === "ai:cover_letter" ? "Drafting…" : "Draft with AI"}
        </Button>
        <PresetsButton
          tone={tone}
          onToneChange={onToneChange}
          length={length}
          onLengthChange={onLengthChange}
        />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2" data-testid="ai-toolbar-cluster">
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
      <PresetsButton
        tone={tone}
        onToneChange={onToneChange}
        length={length}
        onLengthChange={onLengthChange}
      />
    </div>
  );
}
