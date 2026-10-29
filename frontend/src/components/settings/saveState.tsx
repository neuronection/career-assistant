import { useTranslation } from "react-i18next";
import { Check, Loader2, RotateCw } from "lucide-react";

/** Save-state vocabulary shared by every settings section card (the
 * profile `SectionSaveState` contract, plan 148's hybrid save semantics:
 * switches save instantly, forms save explicitly, every card shows state). */
export type SettingsSaveState = "idle" | "dirty" | "saving" | "saved" | "error";

/** Per-card save indicator (aria-live): Saved ✓ / Saving… / Unsaved
 * changes / Couldn't save — Retry. `idle` renders nothing. */
export function SaveStateIndicator({
  state,
  error,
  onRetry,
}: {
  state: SettingsSaveState;
  error?: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation();
  if (state === "idle") return null;
  if (state === "error") {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--as-danger)]"
        data-testid="settings-save-state"
        aria-live="polite"
      >
        {t("settingsKit.save.error")}
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold underline decoration-transparent transition-colors hover:decoration-current focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-focus-ring)]"
          >
            <RotateCw className="h-3 w-3" aria-hidden />
            {t("settingsKit.save.retry")}
          </button>
        ) : null}
        {error ? <span className="sr-only">{error}</span> : null}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${
        state === "saved"
          ? "text-emerald-600"
          : "text-[var(--as-muted-fg)]"
      }`}
      data-testid="settings-save-state"
      aria-live="polite"
    >
      {state === "saved" ? (
        <>
          <Check className="h-3 w-3" aria-hidden />
          {t("settingsKit.save.saved")}
        </>
      ) : state === "saving" ? (
        <>
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          {t("settingsKit.save.saving")}
        </>
      ) : (
        t("settingsKit.save.dirty")
      )}
    </span>
  );
}
