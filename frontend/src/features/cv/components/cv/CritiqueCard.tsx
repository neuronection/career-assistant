import { useTranslation } from "react-i18next";
import { AlertTriangle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import type { CvAssistantCritique } from "@/types/cvAssistant";

export function CritiqueCard({
  critique,
  onApplyFixes,
  busy = false,
}: {
  critique: CvAssistantCritique;
  onApplyFixes?: (fixes: Record<string, string>) => void;
  busy?: boolean;
}) {
  const { t } = useTranslation();
  const fixes = Object.entries(critique.safe_token_fixes ?? {});
  return (
    <div className="space-y-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-3" data-testid="critique-card">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t("cvBuilder.critiqueTitle", { defaultValue: "Visual review" })}
      </p>
      {critique.summary && (
        <p className="text-xs text-[var(--as-fg)]">{critique.summary}</p>
      )}
      <ul className="space-y-1.5">
        {critique.issues.map((issue, index) => (
          <li key={index} className="flex items-start gap-1.5 text-xs" data-testid={`critique-issue-${index}`}>
            <AlertTriangle
              className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                issue.severity === "major" ? "text-amber-600" : "text-[var(--as-muted-fg)]"
              }`}
              aria-hidden
            />
            <span className="min-w-0">
              <span className="font-medium text-[var(--as-fg)]">{issue.area}</span>
              <span className="text-[var(--as-muted-fg)]"> — {issue.message}</span>
            </span>
          </li>
        ))}
      </ul>
      {fixes.length > 0 && onApplyFixes && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => onApplyFixes(critique.safe_token_fixes ?? {})}
          data-testid="apply-critique-fixes"
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
          {t("cvBuilder.applyCritiqueFixes", { defaultValue: "Apply suggested fixes" })}
        </Button>
      )}
    </div>
  );
}
