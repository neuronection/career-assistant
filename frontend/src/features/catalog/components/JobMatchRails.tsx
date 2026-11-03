import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

import { fetchJobLivePostings, fetchSimilarJobs } from "@/api/jobs";
import { PanelModal } from "@/components/ui";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import type {
  JobPostingMatch,
  JobPostings,
  SimilarJob,
  SimilarJobs,
} from "@/types/wire";

type Selected =
  | { kind: "job"; item: SimilarJob }
  | { kind: "posting"; item: JobPostingMatch }
  | null;

function SourcePill({ source }: { source: string }) {
  const { t } = useTranslation();
  return (
    <span
      className="inline-flex items-center rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
      data-testid={`match-source-${source}`}
    >
      {t(`jobDetail.matchSource.${source}`, { defaultValue: source })}
    </span>
  );
}

function Score({ value }: { value: number }) {
  return (
    <span className="font-mono text-xs text-[var(--as-muted-fg)]" data-testid="match-score">
      {Number(value).toFixed(2)}
    </span>
  );
}

function DegradedNotice({
  source,
  degraded,
  testId,
}: {
  source: string;
  degraded: string | null | undefined;
  testId: string;
}) {
  const { t } = useTranslation();
  if (source !== "skill_overlap" && source !== "catalog") return null;
  return (
    <p
      className="rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-2.5 py-1.5 text-[11px] text-[var(--as-muted-fg)]"
      data-testid={testId}
    >
      {t("jobDetail.matchDegraded", {
        reason: degraded
          ? t(`jobDetail.degradedReason.${degraded}`, { defaultValue: degraded })
          : t("jobDetail.degradedReason.unknown"),
      })}
    </p>
  );
}

function DrawerBody({ selected }: { selected: NonNullable<Selected> }) {
  const { t } = useTranslation();
  const perView = selected.item.per_view ?? {};
  const views = Object.entries(perView).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="space-y-4" data-testid="job-match-drawer-body">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs uppercase tracking-wide text-[var(--as-muted-fg)]">
          {t("jobDetail.matchDrawer.score")}
        </span>
        <span className="text-lg font-semibold text-[var(--as-fg)]">
          {Number(selected.item.score).toFixed(2)}
        </span>
        <SourcePill source={selected.item.source} />
      </div>

      {selected.kind === "job" ? (
        <div className="grid gap-1 text-sm text-[var(--as-fg)]">
          <p>
            <span className="text-[var(--as-muted-fg)]">
              {t("jobDetail.matchDrawer.family")}:{" "}
            </span>
            {selected.item.family_label ??
              selected.item.family_key ??
              t("jobDetail.matchDrawer.noFamily")}
          </p>
          <p className="font-mono text-xs text-[var(--as-muted-fg)]">
            {selected.item.code}
          </p>
        </div>
      ) : (
        <div className="grid gap-1 text-sm text-[var(--as-fg)]">
          <p>
            <span className="text-[var(--as-muted-fg)]">
              {t("jobDetail.matchDrawer.org")}:{" "}
            </span>
            {selected.item.org || "—"}
          </p>
          <p>
            <span className="text-[var(--as-muted-fg)]">
              {t("jobDetail.matchDrawer.status")}:{" "}
            </span>
            {t(`jobDetail.livePostingsForJob.status.${selected.item.status}`, {
              defaultValue: selected.item.status,
            })}
          </p>
          <p className="font-mono text-xs text-[var(--as-muted-fg)]">
            {selected.item.ref}
          </p>
        </div>
      )}

      {views.length > 0 ? (
        <section className="space-y-2" data-testid="match-drawer-per-view">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("jobDetail.matchDrawer.perView")}
          </h4>
          {views.map(([key, value]) => {
            const width = Math.max(0, Math.min(1, Number(value))) * 100;
            return (
              <div key={key} data-testid={`match-view-${key}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--as-fg)]">
                    {t(`jobDetail.matchView.${key}`, { defaultValue: key })}
                  </span>
                  <span className="font-mono text-[var(--as-muted-fg)]">
                    {Number(value).toFixed(3)}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--as-muted)]">
                  <div
                    className="h-full rounded-full bg-[var(--as-accent)]"
                    style={{ width: `${width}%` }}
                  />
                </div>
              </div>
            );
          })}
        </section>
      ) : (
        <p
          className="text-xs text-[var(--as-muted-fg)]"
          data-testid="match-drawer-no-per-view"
        >
          {t("jobDetail.matchDrawer.noPerView")}
        </p>
      )}
    </div>
  );
}

/** The job-detail match rails (plan 50 §7.3): similar catalog jobs and the
 * live postings for this job, each opening a per-view score drawer. The
 * endpoint's lexical fallback is labelled, never hidden. */
export function JobMatchRails({ jobCode }: { jobCode: string }) {
  const { t } = useTranslation();
  const [similar, setSimilar] = useState<SimilarJobs | null>(null);
  const [live, setLive] = useState<JobPostings | null>(null);
  const [selected, setSelected] = useState<Selected>(null);

  useEffect(() => {
    let cancelled = false;
    setSimilar(null);
    setLive(null);
    void fetchSimilarJobs(jobCode, { limit: 6 })
      .then((payload) => {
        if (!cancelled) setSimilar(payload);
      })
      .catch(() => {
        if (!cancelled) setSimilar(null);
      });
    void fetchJobLivePostings(jobCode, { limit: 6 })
      .then((payload) => {
        if (!cancelled) setLive(payload);
      })
      .catch(() => {
        if (!cancelled) setLive(null);
      });
    return () => {
      cancelled = true;
    };
  }, [jobCode]);

  const showSimilar = (similar?.items?.length ?? 0) > 0;
  const showLive = (live?.items?.length ?? 0) > 0;
  if (!showSimilar && !showLive) return null;
  const similarItems = similar?.items ?? [];
  const liveItems = live?.items ?? [];

  return (
    <>
      {showSimilar && (
        <section className="space-y-2" data-testid="job-similar-jobs">
          <h3 className="font-medium">{t("jobDetail.similarJobs.title")}</h3>
          <DegradedNotice
            source={similar!.source}
            degraded={similar!.degraded}
            testId="similar-jobs-degraded"
          />
          <div className="grid gap-2 md:grid-cols-2">
            {similarItems.map((item) => (
              <div
                key={item.code}
                className="flex items-start gap-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
                data-testid={`similar-job-row-${item.code}`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => setSelected({ kind: "job", item })}
                  data-testid={`similar-job-${item.code}`}
                >
                  <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
                    {item.title}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
                    {item.family_label ?? item.family_key ?? t("jobDetail.matchDrawer.noFamily")}
                  </span>
                  <span className="mt-0.5 block truncate font-mono text-[10px] text-[var(--as-muted-fg)]">
                    {item.code}
                  </span>
                  <span className="mt-1 flex items-center gap-2">
                    <Score value={item.score} />
                    <SourcePill source={item.source} />
                  </span>
                </button>
                <Link
                  to={`/jobs/${item.code}`}
                  className="shrink-0 rounded-md p-1 text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                  aria-label={t("jobDetail.similarJobs.open", { title: item.title })}
                  data-testid={`similar-job-open-${item.code}`}
                >
                  <ArrowUpRight className="h-4 w-4" aria-hidden />
                </Link>
              </div>
            ))}
          </div>
        </section>
      )}

      {showLive && (
        <section className="space-y-2" data-testid="job-live-postings">
          <h3 className="font-medium">{t("jobDetail.livePostingsForJob.title")}</h3>
          <DegradedNotice
            source={live!.source}
            degraded={live!.degraded}
            testId="live-postings-degraded"
          />
          <div className="grid gap-2 md:grid-cols-2">
            {liveItems.map((item) => {
              const relative = formatRelativeTime(item.posted_at);
              return (
                <div
                  key={item.id}
                  className="flex items-start gap-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
                  data-testid={`live-posting-row-${item.ref}`}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setSelected({ kind: "posting", item })}
                    data-testid={`live-posting-${item.ref}`}
                  >
                    <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
                      {item.title}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
                      {item.org || "—"} · {item.ref}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-[var(--as-muted-fg)]">
                      {relative
                        ? t(relative.key, { count: relative.count })
                        : formatAbsolute(item.posted_at) ||
                          t("jobDetail.livePostingsForJob.noDate")}
                      {" · "}
                      {t(`jobDetail.livePostingsForJob.status.${item.status}`, {
                        defaultValue: item.status,
                      })}
                    </span>
                    <span className="mt-1 flex items-center gap-2">
                      <Score value={item.score} />
                      <SourcePill source={item.source} />
                    </span>
                  </button>
                  <Link
                    to={`/postings/${item.ref}`}
                    className="shrink-0 rounded-md p-1 text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                    aria-label={t("jobDetail.livePostingsForJob.open", {
                      title: item.title,
                    })}
                    data-testid={`live-posting-open-${item.ref}`}
                  >
                    <ArrowUpRight className="h-4 w-4" aria-hidden />
                  </Link>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <PanelModal
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.item.title}
        size="md"
        data-testid="job-match-drawer"
        footer={
          selected ? (
            <div className="flex justify-end">
              <Link
                to={
                  selected.kind === "job"
                    ? `/jobs/${selected.item.code}`
                    : `/postings/${selected.item.ref}`
                }
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--as-border)] px-3 py-1.5 text-sm text-[var(--as-fg)] hover:bg-[var(--as-muted)]"
                onClick={() => setSelected(null)}
                data-testid="job-match-drawer-open"
              >
                {selected.kind === "job"
                  ? t("jobDetail.similarJobs.open", { title: selected.item.title })
                  : t("jobDetail.livePostingsForJob.open", {
                      title: selected.item.title,
                    })}
                <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </div>
          ) : null
        }
      >
        {selected ? <DrawerBody selected={selected} /> : null}
      </PanelModal>
    </>
  );
}
