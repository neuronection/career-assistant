import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui";
import { SaveStateIndicator, type SettingsSaveState } from "@/components/settings/saveState";

/** One settings section: icon tile + title + description over a body,
 * with the shared save-state indicator, status badges and an optional
 * collapsible body (cv-collapse). `variant="danger"` tints the card for
 * destructive zones. Testids: `settings-section-{name}` root,
 * `-toggle`, `-body` (when collapsible), `settings-save-state`. */
export function SettingsSectionCard({
  name,
  title,
  description,
  icon: Icon,
  variant = "default",
  adminOnly = false,
  badges,
  saveState = "idle",
  saveError,
  onRetrySave,
  summary,
  actions,
  footer,
  collapsible = false,
  defaultOpen = true,
  children,
}: {
  name: string;
  title: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  variant?: "default" | "danger";
  adminOnly?: boolean;
  badges?: ReactNode;
  saveState?: SettingsSaveState;
  saveError?: string;
  onRetrySave?: () => void;
  summary?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const danger = variant === "danger";
  const body = (
    <div
      className="pt-1"
      id={`settings-section-${name}-body`}
      data-testid={collapsible ? `settings-section-${name}-body` : undefined}
    >
      {children}
      {footer ? <div className="mt-3 flex flex-wrap items-center gap-2">{footer}</div> : null}
    </div>
  );
  return (
    <section
      className={`rounded-xl border bg-[var(--as-surface)] p-4 sm:p-5 ${
        danger
          ? "border-[color-mix(in_srgb,var(--as-danger)_38%,var(--as-border))]"
          : "border-[var(--as-border)]"
      }`}
      data-testid={`settings-section-${name}`}
      aria-labelledby={`settings-section-${name}-title`}
    >
      <div className="flex items-start gap-3">
        {Icon ? (
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
              danger
                ? "bg-[color-mix(in_srgb,var(--as-danger)_12%,var(--as-surface-raised))] text-[var(--as-danger)]"
                : "bg-[color-mix(in_srgb,var(--as-primary)_12%,var(--as-surface-raised))] text-[var(--as-primary)]"
            }`}
            aria-hidden
          >
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {collapsible ? (
              <button
                type="button"
                onClick={() => setOpen((prev) => !prev)}
                aria-expanded={open}
                aria-controls={`settings-section-${name}-body`}
                data-testid={`settings-section-${name}-toggle`}
                className="flex min-w-0 items-center gap-1 text-left text-sm font-semibold text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
              >
                <ChevronRight
                  className={`h-3.5 w-3.5 shrink-0 text-[var(--as-muted-fg)] transition-transform ${
                    open ? "rotate-90" : ""
                  }`}
                  aria-hidden
                />
                <span id={`settings-section-${name}-title`}>{title}</span>
              </button>
            ) : (
              <h3
                id={`settings-section-${name}-title`}
                className={`text-sm font-semibold ${danger ? "text-[var(--as-danger)]" : "text-[var(--as-fg)]"}`}
              >
                {title}
              </h3>
            )}
            {adminOnly ? (
              <Badge variant="outline" data-testid={`settings-section-${name}-admin`}>
                {t("settingsKit.adminBadge")}
              </Badge>
            ) : null}
            {badges}
          </div>
          {description ? (
            <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">{description}</p>
          ) : null}
          {summary ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">{summary}</div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {actions}
          <SaveStateIndicator state={saveState} error={saveError} onRetry={onRetrySave} />
        </div>
      </div>
      <div className="mt-2">
        {collapsible ? (
          <div className="cv-collapse" data-open={open}>
            <div>{body}</div>
          </div>
        ) : (
          body
        )}
      </div>
    </section>
  );
}
