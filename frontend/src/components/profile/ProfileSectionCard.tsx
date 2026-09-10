import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export type SectionSaveState = "idle" | "dirty" | "saving" | "saved" | "error";

const STATE_LABEL_KEYS: Record<SectionSaveState, string> = {
  idle: "",
  dirty: "profile.save.dirty",
  saving: "common.saving",
  saved: "profile.save.saved",
  error: "profile.save.error",
};

export function SaveIndicator({
  state,
  error,
}: {
  state: SectionSaveState;
  error?: string;
}) {
  const { t } = useTranslation();
  if (state === "idle") return null;
  return (
    <span
      className={`text-xs ${
        state === "error"
          ? "font-medium text-[var(--as-danger)]"
          : state === "saved"
            ? "text-emerald-600"
            : "text-[var(--as-muted-fg)]"
      }`}
      data-testid="section-save-state"
      title={state === "error" ? error || t(STATE_LABEL_KEYS.error) : undefined}
    >
      {STATE_LABEL_KEYS[state] ? t(STATE_LABEL_KEYS[state]) : ""}
    </span>
  );
}

export function ProfileSectionCard({
  name,
  title,
  description,
  complete = null,
  saveState = "idle",
  error,
  actions,
  variant = "page",
  children,
}: {
  name: string;
  title: string;
  description?: string;
  complete?: boolean | null;
  saveState?: SectionSaveState;
  error?: string;
  actions?: ReactNode;
  variant?: "page" | "onboarding";
  children: ReactNode;
}) {
  return (
    <section
      className={
        variant === "page"
          ? "rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:p-5"
          : "flex min-h-0 flex-col"
      }
      data-testid={`profile-section-${name}`}
      data-complete={complete === null ? undefined : String(complete)}
      aria-labelledby={`profile-section-${name}-title`}
    >
      <div
        className={`flex items-start justify-between gap-3 ${
          variant === "page" ? "mb-3" : "mb-2"
        }`}
      >
        <div className="min-w-0">
          <h2
            id={`profile-section-${name}-title`}
            className={`flex items-center gap-2 font-semibold text-[var(--as-fg)] ${
              variant === "page" ? "text-sm" : "text-base"
            }`}
          >
            {complete !== null && (
              <span
                aria-hidden
                className={`inline-block size-2 shrink-0 rounded-full ${
                  complete
                    ? "bg-[var(--as-accent)]"
                    : "border border-[var(--as-border)] bg-transparent"
                }`}
                data-testid={`section-dot-${name}`}
              />
            )}
            {title}
          </h2>
          {description && (
            <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
              {description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          <SaveIndicator state={saveState} error={error} />
        </div>
      </div>
      {children}
    </section>
  );
}
