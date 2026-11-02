/**
 * The Resolution section (plan 153 slice 4) — the extraction pipeline's
 * observability & tuning surface inside the admin Taxonomy page's
 * Relations tab: last-run + rolling KPIs from the POSTING_EXTRACT job
 * results, the `posting_resolve.thresholds` editor, and the wave
 * controls (bulk replay, skill-embedding reconcile; scheduler failures
 * only deep-link into /settings/automations — plan-152 D6, no second
 * scheduler UI).
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AlertTriangle, History, RefreshCw, Repeat } from "lucide-react";

import { apiDetail } from "@/api/client";
import { TaxonomyEmbeddingsCard } from "@/components/settings/TaxonomyEmbeddingsCard";
import {
  fetchResolutionStats,
  fetchResolutionThresholds,
  reconcileSkillEmbeddings,
  replayPostingResolution,
  saveResolutionThresholds,
  type EmbeddingReconcileReport,
  type ResolutionReplayReport,
  type ResolutionStats,
  type ResolutionThresholds,
} from "@/api/postingResolution";
import { Button, EmptyState, SegmentedTabs, Spinner } from "@/components/ui";
import { NumberField } from "@/features/cv/components/cv/formPrimitives";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";

export const RESOLUTION_WINDOWS = ["24h", "7d", "30d"] as const;

const THRESHOLD_FIELDS: {
  key: keyof ResolutionThresholds;
  min: number;
  max?: number;
}[] = [
  { key: "candidate_trigram_floor", min: 0, max: 1 },
  { key: "candidate_cosine_floor", min: 0, max: 1 },
  { key: "candidate_top_k", min: 1, max: 5 },
  { key: "dedup_trigram_bar", min: 0, max: 1 },
  { key: "dedup_cosine_bar", min: 0, max: 1 },
  { key: "corroboration_min_postings", min: 1 },
  { key: "corroboration_cap", min: 1 },
];

const percent = (rate: number): string => `${Math.round(rate * 100)}%`;

export function ResolutionSection() {
  const { t } = useTranslation();
  const [thresholds, setThresholds] = useState<ResolutionThresholds | null>(null);
  const [thresholdNote, setThresholdNote] = useState("");
  const [stats, setStats] = useState<ResolutionStats | null>(null);
  const [window, setWindow] = useState<(typeof RESOLUTION_WINDOWS)[number]>("7d");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [replayIds, setReplayIds] = useState("");
  const [replayReport, setReplayReport] = useState<ResolutionReplayReport | null>(null);
  const [reconcileReport, setReconcileReport] = useState<EmbeddingReconcileReport | null>(null);

  const load = useCallback(
    async (activeWindow: string) => {
      setLoading(true);
      try {
        const [loadedThresholds, loadedStats] = await Promise.all([
          fetchResolutionThresholds(),
          fetchResolutionStats(activeWindow),
        ]);
        setThresholds(loadedThresholds);
        setStats(loadedStats);
        setError("");
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(window);
  }, [load, window]);

  const onThresholdsSave = async () => {
    if (!thresholds) return;
    setThresholdNote("");
    try {
      setThresholds(await saveResolutionThresholds(thresholds));
      setThresholdNote(t("taxonomy.relations.resolution.thresholds.saved"));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const parseIds = (): string[] =>
    replayIds
      .split(/[\s,;]+/)
      .map((id) => id.trim())
      .filter(Boolean);

  const onReplay = async () => {
    const ids = parseIds();
    if (ids.length === 0) return;
    setBusy(true);
    setError("");
    setReplayReport(null);
    try {
      setReplayReport(await replayPostingResolution(ids.slice(0, 200)));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const onReconcile = async () => {
    setBusy(true);
    setError("");
    setReconcileReport(null);
    try {
      setReconcileReport(await reconcileSkillEmbeddings(200));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const lastRunTiles: StatTile[] = stats
    ? [
        {
          label: t("taxonomy.relations.resolution.stats.labels"),
          value: stats.last_run.labels,
          hint: stats.last_run.replay
            ? t("taxonomy.relations.resolution.stats.replayHint")
            : t("taxonomy.relations.resolution.stats.extractHint"),
        },
        {
          label: t("taxonomy.relations.resolution.stats.exact"),
          value: stats.last_run.exact_hits,
        },
        {
          label: t("taxonomy.relations.resolution.stats.pass2"),
          value: stats.last_run.pass2_matches,
        },
        {
          label: t("taxonomy.relations.resolution.stats.new"),
          value: stats.last_run.new_proposals,
        },
        {
          label: t("taxonomy.relations.resolution.stats.blocks"),
          value: stats.last_run.gate_blocks,
        },
      ]
    : [];

  const rollingTiles: StatTile[] = stats
    ? [
        {
          label: t("taxonomy.relations.resolution.stats.matchRate"),
          value: percent(stats.rolling.match_rate),
          hint: t("taxonomy.relations.resolution.stats.runsHint", {
            count: stats.rolling.runs,
          }),
        },
        {
          label: t("taxonomy.relations.resolution.stats.newRate"),
          value: percent(stats.rolling.new_rate),
        },
        {
          label: t("taxonomy.relations.resolution.stats.blockRate"),
          value: percent(stats.rolling.block_rate),
        },
        {
          label: t("taxonomy.relations.resolution.stats.replayRate"),
          value: percent(stats.rolling.replay_rate),
        },
        {
          label: t("taxonomy.relations.resolution.stats.degradeRate"),
          value: percent(stats.rolling.degrade_rate),
        },
      ]
    : [];

  return (
    <div className="space-y-4" data-testid="resolution-section">
      <p className="text-sm text-[var(--as-muted-fg)]">
        {t("taxonomy.relations.resolution.intro")}
      </p>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : (
        <>
          <section
            className="space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
            data-testid="resolution-stats"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-[var(--as-fg)]">
                {t("taxonomy.relations.resolution.stats.heading")}
              </p>
              <SegmentedTabs
                ariaLabel={t("taxonomy.relations.resolution.stats.windowsAria")}
                items={RESOLUTION_WINDOWS.map((value) => ({
                  value,
                  label: t(`taxonomy.relations.resolution.stats.window.${value}`),
                }))}
                value={window}
                onValueChange={(next) => setWindow(next as (typeof RESOLUTION_WINDOWS)[number])}
              />
            </div>
            {stats === null ? (
              <EmptyState
                icon={History}
                title={t("taxonomy.relations.resolution.stats.empty")}
                description={t("taxonomy.relations.resolution.stats.emptyBody")}
              />
            ) : (
              <>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {t("taxonomy.relations.resolution.stats.lastRunGroup")}
                </p>
                <StatTiles tiles={lastRunTiles} layout="auto" testId="resolution-stats-last-run" />
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {t("taxonomy.relations.resolution.stats.rollingGroup")}
                </p>
                <StatTiles
                  tiles={rollingTiles}
                  layout="auto"
                  testId="resolution-stats-rolling"
                />
                {stats.failing_schedules > 0 && (
                  <p
                    className="flex items-center gap-2 text-xs text-amber-700"
                    data-testid="resolution-failing-schedules"
                  >
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                    {t("taxonomy.relations.resolution.stats.failingSchedules", {
                      count: stats.failing_schedules,
                    })}{" "}
                    <Link
                      to="/settings/automations"
                      className="underline"
                      data-testid="resolution-schedules-link"
                    >
                      {t("taxonomy.relations.resolution.stats.openAutomations")}
                    </Link>
                  </p>
                )}
              </>
            )}
          </section>

          {thresholds && (
            <section
              className="max-w-xl space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
              data-testid="resolution-thresholds"
            >
              <p className="text-sm font-medium text-[var(--as-fg)]">
                {t("taxonomy.relations.resolution.thresholds.heading")}
              </p>
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("taxonomy.relations.resolution.thresholds.intro")}
              </p>
              {THRESHOLD_FIELDS.map(({ key, min, max }) => (
                <NumberField
                  key={key}
                  label={t(`taxonomy.relations.resolution.thresholds.field.${key}`)}
                  value={thresholds[key]}
                  min={min}
                  max={max}
                  onChange={(value) =>
                    setThresholds({ ...thresholds, [key]: value ?? min })
                  }
                  testId={`threshold-${key}`}
                />
              ))}
              <div className="flex items-center gap-3">
                <Button
                  size="sm"
                  onClick={() => void onThresholdsSave()}
                  data-testid="resolution-thresholds-save"
                >
                  {t("taxonomy.relations.resolution.thresholds.save")}
                </Button>
                {thresholdNote && <p className="text-xs text-emerald-700">{thresholdNote}</p>}
              </div>
            </section>
          )}

          <section
            className="space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
            data-testid="resolution-controls"
          >
            <p className="text-sm font-medium text-[var(--as-fg)]">
              {t("taxonomy.relations.resolution.controls.heading")}
            </p>
            <div className="space-y-1.5">
              <label
                className="text-xs font-medium text-[var(--as-fg)]"
                htmlFor="resolution-replay-ids"
              >
                {t("taxonomy.relations.resolution.controls.replayLabel")}
              </label>
              <textarea
                id="resolution-replay-ids"
                value={replayIds}
                onChange={(event) => setReplayIds(event.target.value)}
                placeholder={t("taxonomy.relations.resolution.controls.replayPlaceholder")}
                className="min-h-16 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 font-mono text-xs"
                data-testid="resolution-replay-ids"
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || parseIds().length === 0}
                  onClick={() => void onReplay()}
                  data-testid="resolution-replay-run"
                >
                  <Repeat className="h-3.5 w-3.5" aria-hidden />
                  {t("taxonomy.relations.resolution.controls.replayRun")}
                </Button>
                {replayReport && (
                  <p className="text-xs text-[var(--as-muted-fg)]" data-testid="resolution-replay-report">
                    {t("taxonomy.relations.resolution.controls.replayReport", {
                      queued: replayReport.queued,
                      skipped: replayReport.skipped,
                      missing: replayReport.missing.length,
                    })}
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void onReconcile()}
                data-testid="resolution-reconcile"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                {t("taxonomy.relations.resolution.controls.reconcile")}
              </Button>
              {reconcileReport && (
                <p
                  className="text-xs text-[var(--as-muted-fg)]"
                  data-testid="resolution-reconcile-report"
                >
                  {reconcileReport.degraded
                    ? t("taxonomy.relations.resolution.controls.reconcileDegraded")
                    : t("taxonomy.relations.resolution.controls.reconcileReport", {
                        embedded: reconcileReport.embedded,
                        candidates: reconcileReport.candidates,
                      })}
                </p>
              )}
            </div>
            <TaxonomyEmbeddingsCard />
          </section>
        </>
      )}
    </div>
  );
}
