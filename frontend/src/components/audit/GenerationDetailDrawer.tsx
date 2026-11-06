import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  CopyButton,
  PanelModal,
  SegmentedTabs,
} from "@/components/ui";
import { formatLatency, formatTokensExact } from "@/config/auditVocab";
import type { AIGenerationRow } from "@/api/audit";

const metaClass = "text-[var(--as-muted-fg)]";
const valueClass = "font-medium text-[var(--as-fg)]";

type ParsedView =
  | { kind: "pairs"; entries: [string, string][] }
  | { kind: "items"; items: string[] }
  | { kind: "text"; text: string };

function parsedView(value: unknown): ParsedView {
  if (value != null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const scalar = entries.filter(
      ([, v]) => v == null || ["string", "number", "boolean"].includes(typeof v),
    );
    if (entries.length > 0 && scalar.length === entries.length) {
      return {
        kind: "pairs",
        entries: entries.map(([k, v]) => [k, v == null ? "—" : String(v)]),
      };
    }
    if (
      Array.isArray(value) &&
      value.every((v) => ["string", "number"].includes(typeof v))
    ) {
      return { kind: "items", items: value.map(String) };
    }
  }
  return {
    kind: "text",
    text: typeof value === "string" ? value : JSON.stringify(value, null, 2),
  };
}

function ParsedValue({ value }: { value: unknown }) {
  const view = useMemo(() => parsedView(value), [value]);
  if (view.kind === "pairs") {
    return (
      <dl className="space-y-0.5" data-testid="audit-parsed-pairs">
        {view.entries.map(([key, entryValue]) => (
          <div
            key={key}
            className="flex items-baseline justify-between gap-2 rounded-md bg-[var(--as-muted)] px-2 py-1"
          >
            <dt
              className="max-w-1/3 shrink-0 truncate text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]"
              title={key}
            >
              {key}
            </dt>
            <dd className="min-w-0 break-words text-right text-[11px] font-medium text-[var(--as-fg)]">
              {entryValue}
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  if (view.kind === "items") {
    return (
      <ul className="flex flex-wrap gap-1" data-testid="audit-parsed-items">
        {view.items.map((item, index) => (
          <li
            key={`${item}-${index}`}
            className="break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] px-2 py-0.5 text-[11px] font-medium text-[var(--as-fg)]"
          >
            {item}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2 font-mono text-[11px] leading-relaxed text-[var(--as-fg)]">
      {view.text}
    </pre>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0">
      <h3 className="mb-1 flex items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
        <span>{label}</span>
      </h3>
      {children}
    </section>
  );
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <dt className={metaClass}>{label}</dt>
      <dd className={`min-w-0 break-words text-right ${valueClass}`}>{children}</dd>
    </div>
  );
}

/** The AI-call detail drawer (plan 154): parsed + raw views over one
 * ledger row, deep-linkable via ?detail=<id>, with prev/next stepping
 * through the loaded page. */
export function GenerationDetailDrawer({
  row,
  onClose,
  onNavigate,
  hasPrev,
  hasNext,
  position,
}: {
  row: AIGenerationRow | null;
  onClose: () => void;
  onNavigate?: (delta: -1 | 1) => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  position?: string;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<"parsed" | "raw">("parsed");
  const output = row?.output ?? null;
  const rawOutput = useMemo(
    () => (output ? JSON.stringify(output, null, 2) : ""),
    [output],
  );

  return (
    <PanelModal
      open={row !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        <span className="inline-flex min-w-0 items-center gap-2">
          <span
            className={`text-xs font-semibold ${
              row?.status === "ok" ? "text-emerald-600" : "text-rose-600"
            }`}
          >
            {t(`aiSettings.status.${row?.status ?? "ok"}`, {
              defaultValue: row?.status ?? "",
            })}
          </span>
          <span className="truncate">
            {row
              ? t(`aiSettings.task.${row.task_type}`, {
                  defaultValue: row.task_type.replace(/_/g, " "),
                })
              : ""}
          </span>
          {row?.provider === "mock" && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
              {t("audit.ai.simulated")}
            </span>
          )}
        </span>
      }
      size="xl"
      data-testid="audit-gen-drawer"
    >
      {row && (
        <div className="space-y-4">
          <dl className="space-y-1" data-testid="audit-gen-meta">
            <MetaRow label={t("audit.ai.drawer.model")}>
              {row.provider}/{row.model}
            </MetaRow>
            <MetaRow label={t("audit.ai.drawer.tokens")}>
              {row.tokens_in == null && row.tokens_out == null
                ? "—"
                : `${formatTokensExact(row.tokens_in ?? 0)} → ${formatTokensExact(row.tokens_out ?? 0)}`}
            </MetaRow>
            <MetaRow label={t("audit.ai.colLatency")}>
              {formatLatency(row.latency_ms)}
            </MetaRow>
            {row.task_tier && (
              <MetaRow label={t("audit.ai.colTier")}>{row.task_tier}</MetaRow>
            )}
            {row.prompt_version && (
              <MetaRow label={t("audit.ai.drawer.promptVersion")}>
                {row.prompt_version}
              </MetaRow>
            )}
            {row.pack_key && (
              <MetaRow label={t("audit.ai.drawer.pack")}>
                {row.pack_key}
                {row.pack_version != null ? ` v${row.pack_version}` : ""}
              </MetaRow>
            )}
            {row.run_id && (
              <MetaRow label={t("audit.ai.drawer.run")}>
                <span className="inline-flex items-center gap-1">
                  <span className="font-mono text-[11px]">{row.run_id.slice(0, 8)}…</span>
                  <CopyButton value={row.run_id} className="size-5" />
                </span>
              </MetaRow>
            )}
            {row.run_stage && (
              <MetaRow label={t("audit.ai.drawer.stage")}>{row.run_stage}</MetaRow>
            )}
            {row.user_id && (
              <MetaRow label={t("audit.ai.drawer.user")}>
                <span className="font-mono text-[11px]">{row.user_id.slice(0, 8)}…</span>
              </MetaRow>
            )}
          </dl>

          {row.error && (
            <p
              className="break-all rounded-[var(--as-radius)] bg-rose-50 p-2 text-xs font-medium text-rose-700"
              data-testid="audit-gen-error"
            >
              {row.error}
            </p>
          )}

          <SegmentedTabs
            ariaLabel={t("audit.ai.drawer.viewAria")}
            items={[
              { value: "parsed", label: t("audit.ai.drawer.parsed") },
              { value: "raw", label: t("audit.ai.drawer.raw") },
            ]}
            value={view}
            onValueChange={(next) => setView(next as "parsed" | "raw")}
          />

          {view === "parsed" ? (
            <div className="space-y-4">
              <Section label={t("audit.ai.drawer.prompt")}>
                <div className="relative">
                  <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2 pr-8 font-mono text-[11px] leading-relaxed text-[var(--as-fg)]">
                    {row.prompt || "—"}
                  </pre>
                  {row.prompt && (
                    <CopyButton
                      value={row.prompt}
                      size={14}
                      className="absolute right-1.5 top-1.5"
                    />
                  )}
                </div>
              </Section>
              <Section label={t("audit.ai.drawer.output")}>
                {output ? (
                  <ParsedValue value={output} />
                ) : (
                  <p className="text-xs text-[var(--as-muted-fg)]">—</p>
                )}
              </Section>
            </div>
          ) : (
            <div className="space-y-4">
              <Section
                label={t("audit.ai.drawer.prompt")}
              >
                <div className="flex items-center justify-between gap-2">
                  <CopyButton value={row.prompt} size={14} />
                </div>
                <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2 font-mono text-[11px] leading-relaxed text-[var(--as-fg)]">
                  {row.prompt || "—"}
                </pre>
              </Section>
              <Section label={t("audit.ai.drawer.output")}>
                <div className="flex items-center justify-end gap-2">
                  {output && <CopyButton value={rawOutput} size={14} />}
                </div>
                {output ? (
                  <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap break-all rounded-[var(--as-radius)] bg-[var(--as-muted)] p-2 font-mono text-[11px] leading-relaxed text-[var(--as-fg)]">
                    {rawOutput}
                  </pre>
                ) : (
                  <p className="text-xs text-[var(--as-muted-fg)]">—</p>
                )}
              </Section>
            </div>
          )}

          {(hasPrev || hasNext) && (
            <div className="flex items-center justify-between border-t border-[var(--as-border)] pt-3 text-xs">
              <button
                type="button"
                className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
                disabled={!hasPrev}
                onClick={() => onNavigate?.(-1)}
                data-testid="audit-gen-drawer-prev"
              >
                <ChevronLeft className="mr-0.5 inline size-3" aria-hidden />
                {t("audit.prev")}
              </button>
              <span className="tabular-nums text-[var(--as-muted-fg)]">{position}</span>
              <button
                type="button"
                className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 disabled:opacity-40"
                disabled={!hasNext}
                onClick={() => onNavigate?.(1)}
                data-testid="audit-gen-drawer-next"
              >
                {t("audit.next")}
                <ChevronRight className="ml-0.5 inline size-3" aria-hidden />
              </button>
            </div>
          )}
        </div>
      )}
    </PanelModal>
  );
}
