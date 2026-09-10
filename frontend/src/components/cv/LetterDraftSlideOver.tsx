import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, X } from "lucide-react";
import { Button } from "@/components/ui";
import type { CoverLetterSuggestionOut } from "@/types/cv";

export function LetterDraftSlideOver({
  suggestion,
  busy,
  onClose,
  onApply,
}: {
  suggestion: CoverLetterSuggestionOut;
  busy: boolean;
  onClose: () => void;
  onApply: (paragraphs: string[], draft: CoverLetterSuggestionOut["draft"]) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const [included, setIncluded] = useState<boolean[]>(() =>
    suggestion.paragraphs.map((paragraph) => paragraph.verified)
  );

  useEffect(() => {
    setIncluded(suggestion.paragraphs.map((paragraph) => paragraph.verified));
  }, [suggestion]);

  const chosen = suggestion.paragraphs.filter((_, index) => included[index]);
  const canApply = chosen.length > 0 && !busy;

  const toggle = (index: number) =>
    setIncluded((values) =>
      values.map((value, position) => (position === index ? !value : value))
    );

  return (
    <div className="fixed inset-0 z-[var(--as-z-modal)]">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-label="Cover-letter draft — review then apply"
        className="cv-slideover-in absolute inset-y-0 right-0 flex w-full max-w-sm flex-col border-l border-[var(--as-border)] bg-[var(--as-surface)] shadow-xl"
        data-testid="letter-slideover"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--as-border)] p-3">
          <p className="text-xs font-semibold uppercase text-[var(--as-muted-fg)]">
            Draft paragraphs — untick what to leave out
          </p>
          <button
            type="button"
            aria-label="Close draft review"
            onClick={onClose}
            className="rounded p-0.5 hover:bg-[var(--as-muted)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3" data-testid="letter-paragraphs">
          {suggestion.paragraphs.map((paragraph, index) => (
            <div
              key={index}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2.5"
              data-testid={`letter-paragraph-${index}`}
            >
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={included[index] ?? false}
                  disabled={!paragraph.verified}
                  onChange={() => toggle(index)}
                  aria-label={`Include paragraph ${index + 1}`}
                  data-testid={`include-paragraph-${index}`}
                />
                <span>{paragraph.text}</span>
              </label>
              {!paragraph.verified && (
                <p className="mt-1 text-xs text-amber-700" data-testid={`letter-flag-${index}`}>
                  <AlertTriangle className="mr-1 inline h-3 w-3" />
                  {paragraph.evidence_refs.length > 0
                    ? "Flagged: cites items outside your profile."
                    : "Flagged: no evidence behind this paragraph."}
                </p>
              )}
            </div>
          ))}
          {suggestion.paragraphs.length === 0 && (
            <p className="text-xs text-[var(--as-muted-fg)]">
              The model returned nothing grounded — try again or write the
              letter manually.
            </p>
          )}
        </div>
        <div className="shrink-0 border-t border-[var(--as-border)] p-3">
          <Button
            className="w-full"
            disabled={!canApply}
            onClick={() => onApply(chosen.map((entry) => entry.text), suggestion.draft)}
            data-testid="apply-letter-draft"
          >
            <Check className="mr-1 h-4 w-4" />
            Apply {chosen.length} paragraph{chosen.length === 1 ? "" : "s"}
          </Button>
        </div>
      </div>
    </div>
  );
}
