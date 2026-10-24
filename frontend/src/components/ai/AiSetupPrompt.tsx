import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";

import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AiStatus } from "@/types/wire";

/** The one place a provider-less app offers setup (plan 118). */
export const AI_SETUP_ROUTE = "/onboarding/setup";

export type AiSetupPromptVariant = "banner" | "card" | "inline";

const SHELL: Record<AiSetupPromptVariant, string> = {
  banner:
    "flex flex-col gap-2 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between",
  card:
    "flex flex-col gap-3 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-5",
  inline: "flex flex-wrap items-center gap-2 text-sm text-[var(--as-muted-fg)]",
};

const CTA =
  "inline-flex shrink-0 items-center gap-1 rounded-[var(--as-radius-sm)] bg-[var(--as-primary)] px-2.5 py-1.5 text-xs font-medium text-[var(--as-primary-fg)] transition-opacity hover:opacity-90";

/** Read the bootstrap's AI status (null until the payload lands). */
export function useAiStatus(): AiStatus | null {
  return useBootstrapStore((state) => state.bootstrap?.ai ?? null);
}

/** Setup affordance for every surface that needs a provider.
 *
 * Renders nothing once AI is configured (or before the bootstrap lands),
 * so it never competes with a working feature. The link goes to the
 * first-run setup route, which is also what a skipped first run links
 * back to.
 *
 * @param variant - `banner` (page header strip), `card` (empty states),
 *   or `inline` (toolbar/copy rows).
 * @param className - Extra classes merged onto the shell.
 */
export function AiSetupPrompt({
  variant = "card",
  className = "",
}: {
  variant?: AiSetupPromptVariant;
  className?: string;
}) {
  const { t } = useTranslation();
  const ai = useAiStatus();
  if (!ai || ai.configured) return null;

  const cta = (
    <Link to={AI_SETUP_ROUTE} className={CTA} data-testid="ai-setup-open">
      <Sparkles className="size-3.5" aria-hidden />
      {t("aiSetup.cta")}
    </Link>
  );

  if (variant === "inline") {
    return (
      <div
        className={`${SHELL.inline} ${className}`}
        data-testid="ai-setup-prompt-inline"
      >
        <span className="min-w-0">{t("aiSetup.inlineBody")}</span>
        {cta}
      </div>
    );
  }

  if (variant === "banner") {
    return (
      <div
        className={`${SHELL.banner} ${className}`}
        data-testid="ai-setup-prompt-banner"
      >
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="size-4 shrink-0 text-[var(--as-accent)]" aria-hidden />
          <p className="truncate text-sm font-medium text-[var(--as-fg)]">
            {t("aiSetup.bannerTitle")}
          </p>
        </div>
        {cta}
      </div>
    );
  }

  return (
    <div className={`${SHELL.card} ${className}`} data-testid="ai-setup-prompt-card">
      <span className="flex size-9 items-center justify-center rounded-full bg-[var(--as-muted)]">
        <Sparkles className="size-4 text-[var(--as-accent)]" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-semibold text-[var(--as-fg)]">{t("aiSetup.title")}</p>
        <p className="text-sm text-[var(--as-muted-fg)]">{t("aiSetup.body")}</p>
      </div>
      <div>{cta}</div>
    </div>
  );
}

/** Visible "mock provider active — dev only" marker (plan 118.3).
 *
 * A mock provider is never silent: whenever one resolves for any slot the
 * shell shows this chip, in every mode.
 */
export function AiMockChip({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  const ai = useAiStatus();
  if (!ai?.mock_active) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ${className}`}
      data-testid="ai-mock-chip"
      title={t("aiSetup.mockHint")}
    >
      {t("aiSetup.mockActive")}
    </span>
  );
}
