import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Clock,
  FileSearch,
  RefreshCw,
  Sparkles,
  Tags,
  User,
  type LucideIcon,
} from "lucide-react";

import { api } from "@/api/client";
import { Badge } from "@/components/ui";
import { formatAbsolute } from "@/lib/time";

/** One journal row from `GET /postings/{ref}/history` (plan 142). The
 * diff is already capped server-side; values render as-is, dicts as
 * compact JSON. */
export interface PostingChangeEntry {
  id: string;
  occurred_at: string;
  actor_kind: string;
  actor_ref: Record<string, unknown>;
  operation: Record<string, unknown>;
  duration_ms: number | null;
  diff: Record<string, unknown>;
  outcome: string;
}

interface HistoryResponse {
  items: PostingChangeEntry[];
  total: number;
  limit: number;
  offset: number;
  posting_id: string;
}

const KIND_ICON: Record<string, LucideIcon> = {
  sync_run: RefreshCw,
  extract_llm: Sparkles,
  detail_fetch: FileSearch,
  company_match: Building2,
  retag: Tags,
  manual: User,
  expiry: Clock,
};

const ACTOR_REF_KEYS = ["trigger", "mode", "model", "prompt_version"] as const;

function durationChip(ms: number | null): string {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function valueText(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function dayKey(iso: string): string {
  return new Date(iso).toDateString();
}

function DiffValue({ field, change }: { field: string; change: { from?: unknown; to?: unknown } }) {
  const { t } = useTranslation();
  if (field === "skills") {
    const skills = change as unknown as {
      added?: string[];
      removed?: string[];
      changed?: Record<string, Record<string, { from: unknown; to: unknown }>>;
    };
    if (skills.added || skills.removed || skills.changed) {
      return (
        <div className="space-y-1">
          {skills.added?.length ? (
            <p className="text-xs text-emerald-700">+ {skills.added.join(", ")}</p>
          ) : null}
          {skills.removed?.length ? (
            <p className="text-xs text-rose-600">− {skills.removed.join(", ")}</p>
          ) : null}
          {Object.entries(skills.changed ?? {}).map(([key, fields]) => (
            <p key={key} className="text-xs text-slate-600">
              {key}:{" "}
              {Object.entries(fields)
                .map(([name, mv]) => `${name} ${valueText(mv.from)} → ${valueText(mv.to)}`)
                .join(" · ")}
            </p>
          ))}
        </div>
      );
    }
  }
  return (
    <p className="text-xs text-slate-600 break-all">
      <span className="text-[var(--as-muted-fg)]">{t("postingDetail.history.from")}</span>{" "}
      {valueText(change.from)}{" "}
      <span className="text-[var(--as-muted-fg)]">{t("postingDetail.history.to")}</span>{" "}
      {valueText(change.to)}
    </p>
  );
}

function HistoryRow({ entry }: { entry: PostingChangeEntry }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const Icon = KIND_ICON[entry.actor_kind] ?? Clock;
  const duration = durationChip(entry.duration_ms);
  const diffEntries = Object.entries(entry.diff ?? {});
  const actorChips = ACTOR_REF_KEYS.filter((key) => entry.actor_ref?.[key] != null);

  return (
    <li className="relative pl-5">
      <span
        className="absolute left-0 top-1.5 h-2 w-2 rounded-full bg-[var(--as-accent)]"
        aria-hidden
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={entry.actor_kind === "extract_llm" ? "success" : "secondary"}>
          <Icon aria-hidden className="mr-1 h-3 w-3" />
          {t(`postingDetail.history.kind.${entry.actor_kind}`, {
            defaultValue: entry.actor_kind.replace(/_/g, " "),
          })}
        </Badge>
        {duration ? (
          <span
            className="text-[11px] tabular-nums text-[var(--as-muted-fg)]"
            data-testid="history-duration"
          >
            {duration}
          </span>
        ) : null}
        {actorChips.map((key) => (
          <span
            key={key}
            className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]"
            data-testid={`history-actor-${key}`}
          >
            {String(entry.actor_ref[key])}
          </span>
        ))}
        <span className="ml-auto text-[11px] text-[var(--as-muted-fg)]" title={formatAbsolute(entry.occurred_at)}>
          {new Date(entry.occurred_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
      {diffEntries.length > 0 ? (
        <>
          <button
            type="button"
            className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-primary-700 hover:underline"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            data-testid={`history-toggle-${entry.id}`}
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {open
              ? t("postingDetail.history.hideDiff")
              : t("postingDetail.history.showDiff", { count: diffEntries.length })}
          </button>
          {open ? (
            <div className="mt-1 space-y-1 border-l border-[var(--as-border)] pl-3">
              {diffEntries.map(([field, change]) => (
                <div key={field} data-testid={`history-diff-${field}`}>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {field}
                  </span>
                  <DiffValue field={field} change={change as { from?: unknown; to?: unknown }} />
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

/** The History section of the posting page's right rail (plan 142):
 * the change journal as a day-grouped vertical timeline — kind badges,
 * duration chips, expandable capped diffs. Empty state is honest about
 * where the record begins. */
export function PostingHistory({
  postingRef,
  createdAt,
}: {
  postingRef: string;
  createdAt: string | null | undefined;
}) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<PostingChangeEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setEntries(null);
    setError("");
    void api
      .get<HistoryResponse>(`/postings/${postingRef}/history`, { params: { limit: 50 } })
      .then((resp) => {
        if (alive) setEntries(resp.data.items ?? []);
      })
      .catch(() => {
        if (alive) setError(t("postingDetail.history.error"));
      });
    return () => {
      alive = false;
    };
  }, [postingRef, t]);

  const groups = useMemo(() => {
    const byDay = new Map<string, PostingChangeEntry[]>();
    for (const entry of entries ?? []) {
      const key = dayKey(entry.occurred_at);
      const bucket = byDay.get(key);
      if (bucket) {
        bucket.push(entry);
      } else {
        byDay.set(key, [entry]);
      }
    }
    return [...byDay.entries()];
  }, [entries]);

  return (
    <section
      className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-[var(--as-radius-lg)] p-4 space-y-2"
      data-testid="posting-history"
    >
      <h2 className="text-sm font-semibold text-[var(--as-fg)]">
        {t("postingDetail.history.heading")}
      </h2>
      {error ? (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="posting-history-error">
          {error}
        </p>
      ) : entries === null ? (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="posting-history-loading">
          {t("postingDetail.history.loading")}
        </p>
      ) : entries.length === 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="posting-history-empty">
          {createdAt
            ? t("postingDetail.history.empty", {
                date: new Date(createdAt).toLocaleDateString(),
              })
            : t("postingDetail.history.emptyNoDate")}
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map(([day, dayEntries]) => (
            <div key={day} className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
                {new Date(day).toLocaleDateString()}
              </p>
              <ul className="space-y-2" data-testid="posting-history-list">
                {dayEntries.map((entry) => (
                  <HistoryRow key={entry.id} entry={entry} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
