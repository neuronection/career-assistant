import { useState } from "react";
import { useTranslation } from "react-i18next";
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
import { AiSetupPrompt } from "@/components/ai/AiSetupPrompt";

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
    action: "summary" | "gaps" | "compaction" | "tailor" | "translate"
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
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          data-testid="ai-presets"
          aria-label={t("cvBuilder.ai.presetsAria")}
          title={t("cvBuilder.ai.presetsTitle", {
            tone: tone || t("cvBuilder.ai.default"),
            length: length || t("cvBuilder.ai.default"),
          })}
        >
          <SlidersHorizontal className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 space-y-2" data-testid="ai-presets-panel">
        <label className="block space-y-1 text-xs">
          <span className="text-[var(--as-muted-fg)]">{t("cvBuilder.ai.tone")}</span>
          <select
            aria-label={t("cvBuilder.ai.tone")}
            className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
            value={tone}
            onChange={(event) => onToneChange(event.target.value)}
            data-testid="tone-select"
          >
            <option value="">{t("cvBuilder.ai.default")}</option>
            {TONES.map((value) => (
              <option key={value} value={value}>
                {t(`cvBuilder.ai.tone.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1 text-xs">
          <span className="text-[var(--as-muted-fg)]">{t("cvBuilder.ai.length")}</span>
          <select
            aria-label={t("cvBuilder.ai.length")}
            className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1"
            value={length}
            onChange={(event) => onLengthChange(event.target.value)}
            data-testid="length-select"
          >
            <option value="">{t("cvBuilder.ai.default")}</option>
            {LENGTHS.map((value) => (
              <option key={value} value={value}>
                {t(`cvBuilder.ai.lengthValue.${value}`)}
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
  const { t } = useTranslation();
  const [tailorOpen, setTailorOpen] = useState(false);

  if (mode === "cover_letter") {
    return (
      <div className="flex items-center gap-2" data-testid="ai-toolbar-cluster">
        <AiSetupPrompt variant="inline" />
        <Button
          size="sm"
          disabled={!hasTargetPosting || busy === "ai:cover_letter"}
          onClick={onDraftLetter}
          data-testid="draft-letter"
          title={
            hasTargetPosting
              ? t("cvBuilder.ai.draftLetterTitle")
              : t("cvBuilder.ai.draftLetterDisabled")
          }
        >
          <Sparkles className="mr-1 h-4 w-4" />
          {busy === "ai:cover_letter" ? t("cvBuilder.ai.drafting") : t("cvBuilder.ai.draftWithAi")}
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
      <AiSetupPrompt variant="inline" />
      <Popover open={tailorOpen} onOpenChange={setTailorOpen}>
        <PopoverAnchor asChild>
          <div>
            <AiActionsDropdown
              label={t("cvBuilder.ai.actions")}
              title={t("cvBuilder.ai.actions")}
              busy={busy.startsWith("ai:")}
              error={null}
              primaryAction={{
                id: "summary",
                label: t("cvBuilder.ai.improveSummary"),
                icon: Sparkles,
              }}
              actions={[
                { id: "compaction", label: t("cvBuilder.ai.tighten"), icon: Scissors },
                { id: "gaps", label: t("cvBuilder.ai.findGaps"), icon: Eye },
                { id: "translate", label: translateLabel, icon: Languages },
                {
                  id: "tailor",
                  label: t("cvBuilder.ai.tailorSaved"),
                  icon: Target,
                  description: tailorPostingId
                    ? t("cvBuilder.ai.usesSelected")
                    : t("cvBuilder.ai.pickFirst"),
                },
              ]}
              moreLabel={t("cvBuilder.ai.more")}
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
          <p className="text-xs font-semibold text-[var(--as-muted-fg)]">
            {t("cvBuilder.ai.tailorTitle")}
          </p>
          {savedPostings.length > 0 ? (
            <div className="space-y-1.5" data-testid="tailor-picker">
              <select
                aria-label={t("cvBuilder.ai.targetPosting")}
                className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-sm"
                value={tailorPostingId}
                onChange={(event) => onTailorPostingChange(event.target.value)}
              >
                <option value="">{t("cvBuilder.ai.pickPosting")}</option>
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
                {t("cvBuilder.ai.tailor")}
              </Button>
            </div>
          ) : (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("cvBuilder.ai.noSavedPostings")}
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
