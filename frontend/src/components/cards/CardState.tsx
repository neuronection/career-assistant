import type { LucideIcon } from "lucide-react";
import { CheckCheck, Info, Lock } from "lucide-react";

export function SeenMark({ label, testId = "card-seen" }: { label: string; testId?: string }) {
  return (
    <span
      className="inline-flex items-center text-[var(--as-muted-fg)]"
      title={label}
      data-testid={testId}
    >
      <CheckCheck aria-hidden className="h-3 w-3" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function ClosedMark({
  label,
  title,
  testId = "posting-closed",
}: {
  label: string;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      className="inline-flex items-center justify-center gap-1.5 rounded-[7px] border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-1 text-[11.5px] font-semibold text-[var(--as-muted-fg)]"
      title={title}
      data-testid={testId}
      data-tone="muted"
    >
      <Lock aria-hidden className="h-3 w-3" />
      {label}
    </span>
  );
}

const TONE_COLOR: Record<string, string> = {
  muted: "var(--as-muted-fg)",
  success: "var(--as-success)",
  warning: "var(--as-warning)",
  danger: "var(--as-danger)",
};

export function CardStateMarker({
  icon: Icon = Info,
  label,
  title,
  tone = "muted",
  testId,
}: {
  icon?: LucideIcon;
  label?: string;
  title: string;
  tone?: "muted" | "success" | "warning" | "danger";
  testId?: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1"
      style={{ color: TONE_COLOR[tone] }}
      title={title}
      data-testid={testId}
      data-tone={tone}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {label ? <span className="text-[11px]">{label}</span> : null}
      {label ? null : <span className="sr-only">{title}</span>}
    </span>
  );
}
