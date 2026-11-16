import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, EmptyState, Table } from "@/components/ui";
import { CopyButton } from "@/components/ui/copy-button";
import type { PostingGapOut, PostingGapRow } from "@/types/wire";

const GROUPS = ["must_have", "nice_to_have", "bonus"] as const;

const QUOTE_PREVIEW_CHARS = 140;

function QuoteText({ quote }: { quote: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const text = quote.trim();
  if (!text) return <span className="text-[var(--as-muted-fg)]">—</span>;
  const capped = open || text.length <= QUOTE_PREVIEW_CHARS ? text : `${text.slice(0, QUOTE_PREVIEW_CHARS)}…`;
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span
        className="text-[var(--as-muted-fg)] italic"
        title={text}
        data-testid="gap-quote"
      >
        “{capped}”
      </span>
      {text.length > QUOTE_PREVIEW_CHARS && (
        <button
          type="button"
          className="text-xs text-[var(--as-accent)] hover:underline"
          onClick={() => setOpen((v) => !v)}
          data-testid="gap-quote-toggle"
        >
          {open ? t("postingDetail.gap.showLessQuote") : t("postingDetail.gap.showMoreQuote")}
        </button>
      )}
      <CopyButton value={text} label={t("postingDetail.gap.copyQuote")} size={12} />
    </span>
  );
}

function StatusBadge({ status }: { status: PostingGapRow["status"] }) {
  const { t } = useTranslation();
  const variant =
    status === "met" ? "success" : status === "partial" ? "warning" : "secondary";
  return (
    <Badge variant={variant} data-testid={`gap-status-${status}`}>
      {t(`postingDetail.gap.status.${status}`)}
    </Badge>
  );
}

function rowCells(row: PostingGapRow, t: (key: string, opts?: Record<string, unknown>) => string) {
  const requirement = (
    <span className="space-y-1">
      <span className="block font-medium text-[var(--as-fg)]" data-testid="gap-requirement">
        {row.raw_label}
      </span>
      {!row.skill_key && (
        <span className="text-xs text-[var(--as-muted-fg)]" data-testid="gap-unresolved">
          {t("postingDetail.gap.notInTaxonomy")}
        </span>
      )}
    </span>
  );
  const asks =
    row.required_level != null && row.required_level > 0
      ? t("postingDetail.gap.asksLevel", { level: row.required_level })
      : "—";
  const you =
    row.user_level != null && row.user_level > 0
      ? t("postingDetail.gap.youLevel", { level: row.user_level })
      : t("postingDetail.gap.noLevel");
  const userEvidence = (row.user_evidence ?? []).map((ref) => ref.label || ref.source);
  const evidence = (
    <span className="space-y-1">
      <QuoteText quote={row.evidence_quote ?? ""} />
      {userEvidence.length > 0 && (
        <span className="block text-xs text-[var(--as-muted-fg)]" data-testid="gap-user-evidence">
          {userEvidence.join(" · ")}
        </span>
      )}
      {(row.evidence_quote ?? "").trim() === "" && userEvidence.length === 0 && (
        <span className="block text-xs text-[var(--as-muted-fg)]">{t("postingDetail.gap.noEvidence")}</span>
      )}
    </span>
  );
  return [
    <span key="req" className="flex items-center gap-2">
      {requirement}
    </span>,
    <span key="asks" className="whitespace-nowrap tabular-nums">
      {asks}
    </span>,
    <span key="you" className="flex flex-wrap items-center gap-1.5 whitespace-nowrap">
      <span className="tabular-nums">{you}</span>
      <StatusBadge status={row.status} />
    </span>,
    <span key="ev">{evidence}</span>,
  ];
}

/**
 * "What's missing" (plan 212 S1.1): the evidence-first gap report under
 * the match card — rows grouped must-have / nice-to-have / bonus, each
 * with the posting's verbatim words and the user's evidence. There is
 * deliberately no percentage here; the match score stays on its card.
 */
export function GapCard({ gap }: { gap: PostingGapOut | null }) {
  const { t } = useTranslation();
  if (gap === null) {
    return (
      <section
        className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4 space-y-2"
        data-testid="gap-card"
      >
        <h2 className="text-sm font-semibold text-[var(--as-fg)]">{t("postingDetail.gap.heading")}</h2>
        <EmptyState
          title={t("postingDetail.gap.noExtractTitle")}
          description={t("postingDetail.gap.noExtractBody")}
        />
      </section>
    );
  }
  const groups = GROUPS.map((group) => ({ group, rows: gap[group] ?? [] })).filter(
    ({ rows }) => rows.length > 0,
  );
  if (groups.length === 0) {
    return (
      <section
        className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4 space-y-2"
        data-testid="gap-card"
      >
        <h2 className="text-sm font-semibold text-[var(--as-fg)]">{t("postingDetail.gap.heading")}</h2>
        <EmptyState
          title={t("postingDetail.gap.noRequirementsTitle")}
          description={t("postingDetail.gap.noRequirementsBody")}
        />
      </section>
    );
  }
  return (
    <section
      className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4 space-y-3"
      data-testid="gap-card"
    >
      <div className="space-y-0.5">
        <h2 className="text-sm font-semibold text-[var(--as-fg)]">{t("postingDetail.gap.heading")}</h2>
        <p className="text-xs text-[var(--as-muted-fg)]">{t("postingDetail.gap.note")}</p>
      </div>
      {groups.map(({ group, rows }) => (
        <div key={group} className="space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
            {t(`postingDetail.priority.${group}`, { defaultValue: group.replace(/_/g, " ") })}
          </p>
          <Table
            headers={[
              t("postingDetail.gap.col.requirement"),
              t("postingDetail.gap.col.asks"),
              t("postingDetail.gap.col.you"),
              t("postingDetail.gap.col.evidence"),
            ]}
            rows={rows.map((row) => rowCells(row, t))}
          />
        </div>
      ))}
    </section>
  );
}
