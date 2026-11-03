import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Spinner } from "@/components/ui";
import type { RetrievalGate } from "@/api/retrieval";
import { gateVariant } from "@/components/audit/retrieval/retrievalHelpers";

export function RetrievalLoading({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full flex-col items-center justify-center py-16">
      <Spinner size="lg" />
      <p className="mt-3 text-sm text-[var(--as-muted-fg)]">
        {label ?? t("common.loading")}
      </p>
    </div>
  );
}

export function RetrievalError({ message }: { message: string }) {
  return (
    <p
      className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700"
      role="alert"
    >
      {message}
    </p>
  );
}

export function RetrievalSectionHeader({
  title,
  hint,
  actions,
}: {
  title: string;
  hint?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-[var(--as-fg)]">{title}</h3>
        {hint ? (
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">{hint}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function GateBadge({ gate }: { gate: RetrievalGate }) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${gateClass(gate)}`}
      data-testid={`retrieval-gate-${gate}`}
    >
      {t(`retrieval.gate.${gate}`)}
    </span>
  );
}

function gateClass(gate: RetrievalGate): string {
  const variant = gateVariant(gate);
  if (variant === "success") return "bg-emerald-100 text-emerald-700";
  if (variant === "danger") return "bg-rose-100 text-rose-700";
  return "bg-[var(--as-muted)] text-[var(--as-muted-fg)]";
}

export function StateNote({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] p-3 text-xs text-[var(--as-muted-fg)]">
      {children}
    </p>
  );
}

export const tableClass =
  "w-full text-sm";
export const thClass =
  "px-3 py-2 text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]";
export const tdClass = "px-3 py-2 text-xs text-[var(--as-fg)]";
export const tableShellClass =
  "overflow-x-auto rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)]";
