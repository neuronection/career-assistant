import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import { ChevronRight, Languages } from "lucide-react";
import {
  Badge,
  Button,
  ConfirmationModal,
  EmptyState,
  SearchInput,
  Spinner,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  approveOverlay,
  bulkOverlayAction,
  draftOverlays,
  fetchOverlayQueue,
  rejectOverlay,
  updateOverlay,
  type OverlayBulkAction,
} from "@/api/i18n";
import type { LabelOverlay } from "@/types/wire";
import {
  OVERLAY_KIND_ICONS,
  overlayKindIcon,
} from "@/components/settings/taxonomyIcons";
import { CheckIndicator } from "@neuronection/assistant-ui";
import {
  SelectionEntry,
  SelectionToolbar,
  useListSelection,
  type BulkFailure,
} from "@/features/selection";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";

/** Overlay target locales: the supported registry minus the source
 * locale (overlays never target `en`). */
const TARGET_LOCALES = ["de", "el"] as const;

type StatusFilter = "all" | "draft" | "approved" | "rejected";
const STATUS_FILTERS: StatusFilter[] = ["all", "draft", "approved", "rejected"];

/** The review board fetches ONE bounded page (the queue endpoint's max,
 * all locales and statuses — see fetchOverlayQueue) and derives pill
 * counts, groups and search client-side. */
const FETCH_LIMIT = 500;

/** Review cards render incrementally: "Load more" extends the window by
 * this step, so a full 500-row page never mounts every card at once. */
const VISIBLE_STEP = 50;
const SEARCH_DEBOUNCE_MS = 200;

const PILL_ACTIVE =
  "border-[var(--as-accent)] bg-[var(--as-accent)] text-white";
const PILL_IDLE =
  "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]";

function Pill({
  active,
  onClick,
  testid,
  children,
}: {
  active: boolean;
  onClick: () => void;
  testid: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
        active ? PILL_ACTIVE : PILL_IDLE
      }`}
      data-testid={testid}
    >
      {children}
    </button>
  );
}

/**
 * Catalog translations review board (plan 150 phase 4) — the taxonomy
 * page's own "Translations" segment. Locale + status pills carry counts,
 * search runs across the base label and the drafted value, cards group
 * by entity kind, and multi-select batches approve/reject through the
 * per-id endpoints with per-item outcomes. Only an explicit approval
 * renders on catalog surfaces; the base label stays next to every draft
 * so reviewers judge against the source, never blind.
 */
export function TranslationsBoard() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<LabelOverlay[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkFailures, setBulkFailures] = useState<BulkFailure[]>([]);
  const [locale, setLocale] = useState<(typeof TARGET_LOCALES)[number]>("de");
  const [status, setStatus] = useState<StatusFilter>("draft");
  const [rawQuery, setRawQuery] = useState("");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(VISIBLE_STEP);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [confirmingReject, setConfirmingReject] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchOverlayQueue());
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // SearchInput has no internal debounce — debounce app-side (the
  // TaxonomyList recipe). The window reset keys on the SETTLED query,
  // not the debounce tick: a no-op settling (mount, retyping the same
  // text) must never clobber a "Load more" click that raced it.
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(rawQuery), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [rawQuery]);

  useEffect(() => {
    setVisibleCount(VISIBLE_STEP);
  }, [query, locale, status]);

  const localeRows = rows.filter((row) => row.locale === locale);
  const statusCount = (value: StatusFilter) =>
    value === "all"
      ? localeRows.length
      : localeRows.filter((row) => row.status === value).length;

  const searched = query.trim().toLowerCase();
  const filtered = localeRows.filter((row) => {
    if (status !== "all" && row.status !== status) return false;
    if (!searched) return true;
    return [row.base_value, row.value, row.entity_kind, row.field]
      .join(" ")
      .toLowerCase()
      .includes(searched);
  });
  const visible = filtered.slice(0, visibleCount);

  const localeIds = localeRows.map((row) => row.id);
  const matchingIds = filtered.map((row) => row.id);
  const selection = useListSelection({ allIds: localeIds, matchingIds });

  /** Groups in OVERLAY_KIND_ICONS order, unknown kinds appended — only
   * non-empty groups render. */
  const kinds = [
    ...Object.keys(OVERLAY_KIND_ICONS),
    ...[...new Set(visible.map((row) => row.entity_kind))].filter(
      (kind) => !(kind in OVERLAY_KIND_ICONS),
    ),
  ];
  const grouped = kinds
    .map((kind) => ({ kind, rows: visible.filter((row) => row.entity_kind === kind) }))
    .filter((entry) => entry.rows.length > 0);

  /** Only drafts are actionable; the count is derived from the selection,
   * so an approve/reject button never claims rows it would skip. */
  const batchIds = rows
    .filter((row) => selection.isSelected(row.id) && row.status === "draft")
    .map((row) => row.id);

  const pickLocale = (code: (typeof TARGET_LOCALES)[number]) => {
    setLocale(code);
    selection.clear();
    setBulkNote("");
    setBulkFailures([]);
  };

  const pickStatus = (value: StatusFilter) => {
    setStatus(value);
    setBulkNote("");
    setBulkFailures([]);
  };

  const draft = async () => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const result = await draftOverlays(locale);
      const total = Object.values(result.drafted).reduce((sum, value) => sum + value, 0);
      setNote(t("translations.drafted", { count: total }));
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async (row: LabelOverlay) => {
    const value = edits[row.id] ?? row.value;
    if (!value.trim() || value === row.value) return;
    setBusy(true);
    try {
      await updateOverlay(row.id, value.trim());
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const moderate = async (id: string, action: "approve" | "reject") => {
    setBusy(true);
    try {
      await (action === "approve" ? approveOverlay(id) : rejectOverlay(id));
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  /** Batch approve/reject through the server's bulk endpoint; successes
   * are summarized and failures keep their per-item reason (plan 200). */
  const runBatch = async (action: OverlayBulkAction, ids: string[]) => {
    if (ids.length === 0) return;
    setBusy(true);
    setError("");
    setBulkNote("");
    setBulkFailures([]);
    try {
      const result = await bulkOverlayAction(ids, action);
      setBulkFailures(
        result.failed.map((failure) => ({
          ...failure,
          key: rows.find((row) => row.id === failure.id)?.base_value || failure.id,
        })),
      );
      if (result.affected.length > 0) {
        setBulkNote(
          t(`translations.batch.${action}`, { count: result.affected.length }),
        );
      }
      selection.clear();
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ca-tax-list space-y-3" data-testid="translations-board">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">{t("translations.title")}</h2>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("translations.description")}
          </p>
        </div>
        <Button
          size="sm"
          disabled={busy}
          data-testid="translations-draft"
          onClick={() => void draft()}
        >
          {t("translations.draft")}
        </Button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}
      {note && (
        <p className="text-xs text-emerald-600" data-testid="translations-note">
          {note}
        </p>
      )}
      {(bulkNote || bulkFailures.length > 0) && (
        <div data-testid="translations-bulk-note">
          {bulkNote && <p className="text-xs text-emerald-700">{bulkNote}</p>}
          {bulkFailures.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-xs text-amber-600">
              {bulkFailures.map((failure) => (
                <li
                  key={failure.id}
                  data-testid={`translations-bulk-failure-${failure.id}`}
                >
                  {failure.key} — {failure.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1 basis-64" data-testid="translations-search">
          <SearchInput
            value={rawQuery}
            onChange={setRawQuery}
            placeholder={t("translations.searchPlaceholder")}
            ariaLabel={t("translations.searchPlaceholder")}
            clearLabel={t("common.clear")}
          />
        </div>
        <div className="flex flex-wrap gap-1.5" data-testid="translations-locales">
          {TARGET_LOCALES.map((code) => (
            <Pill
              key={code}
              active={locale === code}
              testid={`translations-locale-${code}`}
              onClick={() => pickLocale(code)}
            >
              {code.toUpperCase()}
              <span className="ml-1 tabular-nums opacity-80">
                {rows.filter((row) => row.locale === code).length}
              </span>
            </Pill>
          ))}
        </div>
        <div
          className="flex flex-wrap gap-1.5"
          data-testid="translations-status-filters"
        >
          {STATUS_FILTERS.map((value) => (
            <Pill
              key={value}
              active={status === value}
              testid={`translations-status-${value}`}
              onClick={() => pickStatus(value)}
            >
              {value === "all"
                ? t("taxonomy.filter.all")
                : t(`translations.status.${value}`)}
              <span className="ml-1 tabular-nums opacity-80">
                {statusCount(value)}
              </span>
            </Pill>
          ))}
        </div>
        <SelectionEntry
          prefix="translations"
          selection={selection}
          disabled={localeRows.length === 0}
        />
      </div>

      <SelectionToolbar
        prefix="translations"
        selection={selection}
        allIds={localeIds}
        matchingIds={matchingIds}
        loadedLabel={t("translations.scopeLocale", {
          count: localeRows.length,
          locale: locale.toUpperCase(),
        })}
        busy={busy}
        onShowHidden={() => {
          setRawQuery("");
          setQuery("");
          setStatus("all");
        }}
        actions={
          <>
            <button
              type="button"
              onClick={() => void runBatch("approve", batchIds)}
              disabled={batchIds.length === 0 || busy}
              className="text-xs text-emerald-700 hover:text-emerald-600 disabled:opacity-40"
              data-testid="translations-bulk-approve"
            >
              {t("translations.approve")} ({batchIds.length})
            </button>
            <button
              type="button"
              onClick={() => setConfirmingReject(true)}
              disabled={batchIds.length === 0 || busy}
              className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
              data-testid="translations-bulk-reject"
            >
              {t("translations.reject")} ({batchIds.length})
            </button>
          </>
        }
      />

      {loading ? (
        <div
          className="flex items-center gap-2 py-6 text-xs text-[var(--as-muted-fg)]"
          data-testid="translations-loading"
        >
          <Spinner size="sm" /> {t("common.loading")}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Languages}
          compact
          title={t("translations.emptyTitle")}
          description={t("translations.emptyBody")}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Languages}
          compact
          title={t("taxonomy.noMatch")}
          description={t("taxonomy.noMatchBody")}
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)]">
            {grouped.map(({ kind, rows: groupRows }, index) => {
              const GroupIcon = overlayKindIcon(kind);
              const isCollapsed = collapsed.has(kind);
              return (
                <div
                  key={kind}
                  className={
                    index > 0 ? "border-t border-[var(--as-border)]" : undefined
                  }
                  data-testid={`translations-group-${kind}`}
                >
                  <div className="flex items-center gap-2 bg-[var(--as-muted)] px-3 py-2">
                    {selection.active && (() => {
                      const kindIds = groupRows.map((row) => row.id);
                      const selectedInKind = kindIds.filter((id) =>
                        selection.isSelected(id),
                      ).length;
                      const allSelected =
                        kindIds.length > 0 && selectedInKind === kindIds.length;
                      return (
                        <span
                          className="flex shrink-0 items-center"
                          data-testid={`translations-group-select-${kind}`}
                        >
                          <CheckIndicator
                            checked={allSelected}
                            mixed={selectedInKind > 0 && !allSelected}
                            label={t("taxonomy.bulk.selectGroup", {
                              count: kindIds.length,
                              group: t(`translations.kind.${kind}`, {
                                defaultValue: kind,
                              }),
                            })}
                            onToggle={() =>
                              selection.setSelection(kindIds, !allSelected)
                            }
                          />
                        </span>
                      );
                    })()}
                    <button
                      type="button"
                      aria-expanded={!isCollapsed}
                      onClick={() =>
                        setCollapsed((prev) => {
                          const next = new Set(prev);
                          if (next.has(kind)) next.delete(kind);
                          else next.add(kind);
                          return next;
                        })
                      }
                      className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
                      data-testid={`translations-group-toggle-${kind}`}
                    >
                      <GroupIcon
                        className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]"
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--as-fg)]">
                        {t(`translations.kind.${kind}`, { defaultValue: kind })}
                      </span>
                      <span
                        className="rounded-full bg-[var(--as-surface)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]"
                        data-testid={`translations-group-count-${kind}`}
                      >
                        {groupRows.length}
                      </span>
                      <ChevronRight
                        className={`h-3.5 w-3.5 text-[var(--as-muted-fg)] transition-transform ${
                          isCollapsed ? "" : "rotate-90"
                        }`}
                        aria-hidden
                      />
                    </button>
                  </div>
                  {!isCollapsed && (
                    <ul className="divide-y divide-[var(--as-border)]">
                      {groupRows.map((row) => {
                        const RowIcon: LucideIcon = overlayKindIcon(row.entity_kind);
                        const relative = formatRelativeTime(row.created_at);
                        return (
                          <li
                            key={row.id}
                            className="flex items-start gap-2 px-3 py-2.5"
                            data-testid={`translations-card-${row.id}`}
                          >
                            {selection.active && (
                              <div className="flex shrink-0 items-center pt-1">
                                <CheckIndicator
                                  checked={selection.isSelected(row.id)}
                                  label={t("taxonomy.bulk.selectOne", {
                                    label: row.base_value || row.id,
                                  })}
                                  onToggle={() => selection.toggle(row.id)}
                                />
                              </div>
                            )}
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                              <RowIcon
                                className="h-4 w-4 text-[var(--as-accent)]"
                                aria-hidden
                              />
                            </span>
                            <div className="min-w-0 flex-1 space-y-1.5">
                              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                                  {t(`translations.kind.${row.entity_kind}`, {
                                    defaultValue: row.entity_kind,
                                  })}
                                </span>
                                <span className="text-[11px] text-[var(--as-muted-fg)]">
                                  ·{" "}
                                  {t(`translations.field.${row.field}`, {
                                    defaultValue: row.field,
                                  })}
                                </span>
                                {row.status !== "draft" && (
                                  <Badge
                                    variant={
                                      row.status === "approved" ? "success" : "warning"
                                    }
                                  >
                                    {t(`translations.status.${row.status}`)}
                                  </Badge>
                                )}
                                {relative && (
                                  <span
                                    className="ml-auto shrink-0 text-[11px] text-[var(--as-muted-fg)]"
                                    title={formatAbsolute(row.created_at)}
                                    data-testid={`translations-created-${row.id}`}
                                  >
                                    {t(relative.key, { count: relative.count })}
                                  </span>
                                )}
                              </div>
                              <p className="min-w-0 truncate text-xs text-[var(--as-muted-fg)]">
                                {t("translations.base")}:{" "}
                                <span className="font-medium text-[var(--as-fg)]">
                                  {row.base_value || "—"}
                                </span>
                              </p>
                              <div className="flex flex-wrap items-center gap-2">
                                <input
                                  value={edits[row.id] ?? row.value}
                                  onChange={(event) =>
                                    setEdits((current) => ({
                                      ...current,
                                      [row.id]: event.target.value,
                                    }))
                                  }
                                  className="min-w-0 flex-1 basis-48 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm text-[var(--as-fg)]"
                                  data-testid={`translations-value-${row.id}`}
                                />
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busy}
                                  onClick={() => void save(row)}
                                  data-testid={`translations-save-${row.id}`}
                                >
                                  {t("common.save")}
                                </Button>
                                {row.status === "draft" && (
                                  <>
                                    <Button
                                      size="sm"
                                      disabled={busy}
                                      data-testid={`translations-approve-${row.id}`}
                                      onClick={() => void moderate(row.id, "approve")}
                                    >
                                      {t("translations.approve")}
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      disabled={busy}
                                      data-testid={`translations-reject-${row.id}`}
                                      onClick={() => void moderate(row.id, "reject")}
                                    >
                                      {t("translations.reject")}
                                    </Button>
                                  </>
                                )}
                              </div>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>

          {visible.length < filtered.length && (
            <button
              type="button"
              onClick={() => setVisibleCount((count) => count + VISIBLE_STEP)}
              className="w-full cursor-pointer rounded-xl border border-dashed border-[var(--as-border)] py-2 text-xs text-[var(--as-accent)] hover:bg-[var(--as-muted)]"
              data-testid="translations-load-more"
            >
              {t("translations.loadMore", { count: filtered.length - visible.length })}
            </button>
          )}
          {rows.length >= FETCH_LIMIT && (
            <p
              className="text-[11px] text-[var(--as-muted-fg)]"
              data-testid="translations-truncated"
            >
              {t("translations.truncated", { limit: FETCH_LIMIT })}
            </p>
          )}
        </>
      )}

      <ConfirmationModal
        open={confirmingReject}
        onOpenChange={setConfirmingReject}
        onConfirm={() => {
          setConfirmingReject(false);
          void runBatch("reject", batchIds);
        }}
        title={t("translations.batch.rejectTitle", { count: batchIds.length })}
        description={`${t("translations.batch.rejectBody")}${
          selection.hiddenCount > 0
            ? ` ${t("selection.hiddenConfirm", { count: selection.hiddenCount })}`
            : ""
        }`}
        confirmLabel={t("translations.reject")}
        destructive
      />
    </div>
  );
}
