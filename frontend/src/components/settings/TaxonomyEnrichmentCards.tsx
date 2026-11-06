import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, Clock, Sparkles } from "lucide-react";
import { Badge, Button, ConfirmationModal } from "@/components/ui";
import { CheckIndicator } from "@neuronection/assistant-ui";
import type { EnrichmentRow } from "@/api/taxonomy";
import {
  SelectionEntry,
  SelectionToolbar,
  useListSelection,
} from "@/features/selection";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";

/** The proposal keys produced by EnrichmentPatch today (catalog v2
 * patch + the model's note). */
const KNOWN_KEYS = new Set([
  "contract_type",
  "work_hours",
  "schedule_cues",
  "travel_required",
  "benefits_kinds",
  "note",
]);

type TFunc = (key: string, opts?: Record<string, unknown>) => string;

/** Enum chips reuse the translations the rest of the app already has:
 * benefits live under postingDetail.benefitKind, every other v2 value
 * under explore.facetValue. */
function valueLabel(value: string, benefits: boolean, t: TFunc): string {
  return benefits
    ? t(`postingDetail.benefitKind.${value}`, {
        defaultValue: value.replace(/_/g, " "),
      })
    : t(`explore.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") });
}

const VALUE_CHIP =
  "inline-flex max-w-full items-center rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[11px] text-[var(--as-fg)]";

/** Renders one known proposal key as a labeled row (chips for lists and
 * v2 dicts, plain text for the note); returns null for empty values so
 * absent fields take no space. */
function ProposalField({
  rowId,
  fieldKey,
  labelKey,
  value,
  t,
}: {
  rowId: string;
  fieldKey: string;
  labelKey: string;
  value: unknown;
  t: TFunc;
}) {
  const chips: string[] = [];
  let text: string | null = null;

  if (fieldKey === "note" && typeof value === "string" && value.trim()) {
    text = value;
  } else if (fieldKey === "contract_type" && typeof value === "string" && value) {
    chips.push(valueLabel(value, false, t));
  } else if (fieldKey === "work_hours" && value && typeof value === "object") {
    const hours = value as Record<string, unknown>;
    if (typeof hours.pattern === "string" && hours.pattern) {
      chips.push(valueLabel(hours.pattern, false, t));
    }
    const min = hours.hours_per_week_min;
    const max = hours.hours_per_week_max;
    if (min != null || max != null) {
      chips.push(
        t("postingDetail.hoursPerWeek", {
          range: [min, max].filter((v) => v != null).join("–"),
        }),
      );
    }
  } else if (fieldKey === "travel_required" && value && typeof value === "object") {
    const travel = value as Record<string, unknown>;
    if (typeof travel.level === "string" && travel.level) {
      chips.push(valueLabel(travel.level, false, t));
    }
    if (typeof travel.days_per_month === "number") {
      chips.push(t("postingDetail.travelDays", { count: travel.days_per_month }));
    }
  } else if (Array.isArray(value) && value.length > 0) {
    const benefits = fieldKey === "benefits_kinds";
    for (const entry of value) {
      if (typeof entry === "string" && entry) {
        chips.push(valueLabel(entry, benefits, t));
      }
    }
  }

  if (chips.length === 0 && !text) return null;
  return (
    <div
      className="grid gap-x-3 gap-y-0.5 sm:grid-cols-[9rem_1fr]"
      data-testid={`enrichment-field-${rowId}-${fieldKey}`}
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t(labelKey)}
      </span>
      {text ? (
        <span className="min-w-0 text-xs text-[var(--as-muted-fg)]">{text}</span>
      ) : (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {chips.map((chip, index) => (
            <span key={`${fieldKey}-${index}`} className={VALUE_CHIP}>
              {chip}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const PROPOSAL_FIELDS: Array<{ key: string; labelKey: string }> = [
  { key: "contract_type", labelKey: "taxonomy.enrich.contractType" },
  { key: "work_hours", labelKey: "taxonomy.enrich.workHours" },
  { key: "schedule_cues", labelKey: "taxonomy.enrich.schedule" },
  { key: "travel_required", labelKey: "taxonomy.enrich.travel" },
  { key: "benefits_kinds", labelKey: "taxonomy.enrich.benefits" },
  { key: "note", labelKey: "taxonomy.enrich.note" },
];

/** Enrichment review (plan 150 phase 3): typed proposal cards — known
 * keys as labeled rows (chips for lists), unknown keys collapsed into a
 * "Raw proposal" disclosure so nothing is hidden as debug JSON. Apply
 * merges immediately; discard is destructive and confirmed first. */
export function TaxonomyEnrichmentCards({
  rows,
  onModerate,
  onBulkModerate,
}: {
  rows: EnrichmentRow[];
  onModerate: (id: string, action: "apply" | "reject") => Promise<void>;
  onBulkModerate: (ids: string[], action: "apply" | "reject") => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [rawOpen, setRawOpen] = useState<Set<string>>(new Set());
  const [discarding, setDiscarding] = useState<EnrichmentRow | null>(null);
  const [confirmingBulkReject, setConfirmingBulkReject] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const ids = rows.map((row) => row.id);
  const selection = useListSelection({ allIds: ids, matchingIds: ids });

  const runBulk = async (action: "apply" | "reject") => {
    setBulkBusy(true);
    const applied = await onBulkModerate(Array.from(selection.ids), action);
    setBulkBusy(false);
    if (applied) selection.clear();
  };

  const toggleRaw = (id: string) =>
    setRawOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3" data-testid="enrichment-queue">
      <div className="flex items-center justify-end">
        <SelectionEntry prefix="enrichment" selection={selection} />
      </div>
      <SelectionToolbar
        prefix="enrichment"
        selection={selection}
        allIds={ids}
        matchingIds={ids}
        busy={bulkBusy}
        actions={
          <>
            <button
              type="button"
              onClick={() => void runBulk("apply")}
              disabled={bulkBusy || selection.count === 0}
              className="text-xs text-emerald-700 hover:text-emerald-600 disabled:opacity-40"
              data-testid="enrichment-bulk-apply"
            >
              {t("taxonomy.enrichmentApply")} ({selection.count})
            </button>
            <button
              type="button"
              onClick={() => setConfirmingBulkReject(true)}
              disabled={bulkBusy || selection.count === 0}
              className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
              data-testid="enrichment-bulk-reject"
            >
              {t("taxonomy.enrichmentReject")} ({selection.count})
            </button>
          </>
        }
      />
      {rows.map((row) => {
        const extra = Object.keys(row.proposal ?? {}).filter(
          (key) => !KNOWN_KEYS.has(key),
        );
        const rawOpenRow = rawOpen.has(row.id);
        const relative = formatRelativeTime(row.proposed_at);
        return (
          <div
            key={row.id}
            className="space-y-2.5 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid={`enrichment-row-${row.id}`}
          >
            <div className="flex items-start gap-3">
              {selection.active && (
                <div className="flex shrink-0 items-center pt-1.5">
                  <CheckIndicator
                    checked={selection.isSelected(row.id)}
                    label={t("taxonomy.bulk.selectOne", { label: row.title })}
                    onToggle={() => selection.toggle(row.id)}
                  />
                </div>
              )}
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                <Sparkles className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="truncate text-sm font-medium text-[var(--as-fg)]">
                    {row.title}
                  </span>
                  <Badge
                    variant="outline"
                    className="ca-tax-key font-mono text-[10px]"
                  >
                    {row.code}
                  </Badge>
                </div>
                {relative && (
                  <span
                    className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-[var(--as-muted-fg)]"
                    title={formatAbsolute(row.proposed_at)}
                    data-testid={`enrichment-proposed-${row.id}`}
                  >
                    <Clock className="h-3 w-3" aria-hidden />
                    {t(relative.key, { count: relative.count })}
                  </span>
                )}
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  onClick={() => void onModerate(row.id, "apply")}
                  data-testid={`enrichment-apply-${row.id}`}
                >
                  {t("taxonomy.enrichmentApply")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setDiscarding(row)}
                  data-testid={`enrichment-reject-${row.id}`}
                >
                  {t("taxonomy.enrichmentReject")}
                </Button>
              </div>
            </div>

            {row.proposal && (
              <div className="space-y-1.5 border-t border-[var(--as-border)] pt-2">
                {PROPOSAL_FIELDS.map((field) => (
                  <ProposalField
                    key={field.key}
                    rowId={row.id}
                    fieldKey={field.key}
                    labelKey={field.labelKey}
                    value={row.proposal?.[field.key]}
                    t={t}
                  />
                ))}
                {extra.length > 0 && (
                  <div>
                    <button
                      type="button"
                      aria-expanded={rawOpenRow}
                      onClick={() => toggleRaw(row.id)}
                      className="flex cursor-pointer items-center gap-1 text-xs text-[var(--as-accent)] hover:underline"
                      data-testid={`enrichment-raw-toggle-${row.id}`}
                    >
                      <ChevronRight
                        className={`h-3.5 w-3.5 transition-transform ${rawOpenRow ? "rotate-90" : ""}`}
                        aria-hidden
                      />
                      {t("taxonomy.enrich.rawProposal")}
                    </button>
                    {rawOpenRow && (
                      <pre
                        className="mt-1 max-h-40 overflow-auto rounded bg-[var(--as-muted)] p-2 text-[11px] text-[var(--as-fg)]"
                        data-testid={`enrichment-raw-${row.id}`}
                      >
                        {JSON.stringify(
                          Object.fromEntries(
                            extra.map((key) => [key, row.proposal?.[key]]),
                          ),
                          null,
                          2,
                        )}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}

      <ConfirmationModal
        open={confirmingBulkReject}
        onOpenChange={setConfirmingBulkReject}
        onConfirm={() => {
          setConfirmingBulkReject(false);
          void runBulk("reject");
        }}
        title={t("taxonomy.enrich.bulkRejectTitle", { count: selection.count })}
        description={t("taxonomy.enrich.bulkRejectBody")}
        confirmLabel={t("taxonomy.enrichmentReject")}
        destructive
      />

      <ConfirmationModal
        open={discarding !== null}
        onOpenChange={(open) => (!open ? setDiscarding(null) : undefined)}
        onConfirm={() => {
          if (discarding) void onModerate(discarding.id, "reject");
          setDiscarding(null);
        }}
        title={t("taxonomy.enrich.discardTitle")}
        description={t("taxonomy.enrich.discardBody")}
        confirmLabel={t("taxonomy.enrichmentReject")}
        destructive
      />
    </div>
  );
}
