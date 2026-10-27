import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, SegmentedTabs } from "@/components/ui";
import {
  IntegrationConfigForm,
  integrationConfigPresets,
  parseIntegrationConfigSchema,
} from "@/components/ui/integrations";
import type {
  IntegrationConfigSchema,
  IntegrationConfigValues,
} from "@/components/ui/integrations";
import {
  deleteSource,
  fetchAdminSources,
  fetchSourceRuns,
  probeSource,
  reextractSourcePostings,
  syncSource,
  updateSource,
  type PostingSource,
  type SourceRun,
} from "@/api/sources";
import { fetchSystemSchedules } from "@/api/scheduler";
import { QueryPlanPanel } from "@/components/settings/QueryPlanPanel";
import { RunDetailsDialog } from "@/components/settings/RunDetailsDialog";

/**
 * Source management page (plan 134): one posting source, fully managed —
 * overview, the merged query plan, the configuration knobs and the run
 * ledger (what ran, when, how long, what landed, why it did not) with
 * per-run retry. Follows the app's settings page conventions.
 */

type Tab = "overview" | "plan" | "config" | "runs";

function fmtDuration(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function fmtWhen(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export function SourceDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const backTo =
    (location.state as { from?: string } | null)?.from ?? "/settings/tools";
  const { sourceId = "" } = useParams();
  const [source, setSource] = useState<PostingSource | null>(null);
  const [runs, setRuns] = useState<SourceRun[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [probeNote, setProbeNote] = useState("");
  const [cadenceEvery, setCadenceEvery] = useState<number | null>(null);
  const [detailsRun, setDetailsRun] = useState<SourceRun | null>(null);
  const [configValues, setConfigValues] = useState<IntegrationConfigValues>({});

  const dirtyRef = useRef(false);
  const updateValues = (next: IntegrationConfigValues) => {
    dirtyRef.current = true;
    setConfigValues(next);
  };
  const updateBatch = (count: number) => {
    dirtyRef.current = true;
    setLocalBatch(count);
  };

  useEffect(() => {
    if (!source || dirtyRef.current) return;
    try {
      const parsed = JSON.parse(String(source.config.options ?? "{}")) as Record<string, unknown>;
      setConfigValues(
        parsed && typeof parsed === "object"
          ? (Object.fromEntries(
              Object.entries(parsed).map(([key, value]) => [key, String(value)]),
            ) as IntegrationConfigValues)
          : {},
      );
    } catch {
      setConfigValues({});
    }
  }, [source]);

  const reload = useCallback(async () => {
    const [rows, runRows] = await Promise.all([
      fetchAdminSources(),
      fetchSourceRuns(sourceId),
    ]);
    setSource(rows.find((row) => row.id === sourceId) ?? null);
    setRuns(runRows);
  }, [sourceId]);

  useEffect(() => {
    void reload().catch(() => setNotice(t("sourceDetail.loadFailed")));
    fetchSystemSchedules()
      .then((rows) => {
        const row = rows.find((entry) => entry.kind === "system_source_sync");
        const params = (row?.trigger?.params ?? {}) as { every_minutes?: number };
        setCadenceEvery(params.every_minutes ?? null);
      })
      .catch(() => setCadenceEvery(null));
  }, [reload, t]);

  const [localBatch, setLocalBatch] = useState<number>(source?.query_batch_size ?? 1);
  useEffect(() => {
    if (source?.query_batch_size && !dirtyRef.current) setLocalBatch(source.query_batch_size);
  }, [source?.query_batch_size]);

  const stageLabel = (stage: unknown): string => {
    if (stage === "fetching") return t("sourceDetail.stageFetching");
    if (stage === "ingesting") return t("sourceDetail.stageIngesting");
    if (stage === "enriching") return t("sourceDetail.stageEnriching");
    return typeof stage === "string" ? stage : "";
  };
  const runStatusLabel = (run: SourceRun): string => {
    if (run.status === "running") {
      const stage = stageLabel(run.report?.stage);
      return stage ? `${t("sourceDetail.runRunning")} · ${stage}` : t("sourceDetail.runRunning");
    }
    if (run.status === "ok") return t("sourceDetail.runCompleted");
    if (run.status === "degraded") {
      const capped = (run.report?.errors ?? []).some((entry) => entry?.code === "budget");
      return capped
        ? t("sourceDetail.runCapped", { count: run.items_synced })
        : t("sourceDetail.runPartial");
    }
    if (run.status === "failed") return t("sourceDetail.runFailed");
    if (run.status === "skipped") return t("sourceDetail.runSkipped");
    return run.status;
  };

  const nextRun = useMemo(() => {
    if (!cadenceEvery || !source?.last_run_at) return null;
    return new Date(new Date(source.last_run_at).getTime() + cadenceEvery * 60_000);
  }, [cadenceEvery, source?.last_run_at]);

  const act = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setNotice("");
    try {
      await action();
      await reload();
      if (done) setNotice(done);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  // The ledger row opens at run START (status running + stage) and
  // settles at the end — poll while a run is live so the page follows
  // both moments without a manual reload.
  const pollingRef = useRef(false);
  const pollRuns = useCallback(
    async (previousId: string | null) => {
      if (pollingRef.current) return;
      pollingRef.current = true;
      const started = Date.now();
      try {
        while (Date.now() - started < 20 * 60_000) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          try {
            const rows = await fetchSourceRuns(sourceId);
            setRuns(rows);
            const landed = previousId === null || (rows[0]?.id ?? null) !== previousId;
            const live = rows.some((row) => row.status === "running");
            if (landed && !live) {
              await reload();
              return;
            }
          } catch {
            // transient — the next poll retries
          }
        }
      } finally {
        pollingRef.current = false;
      }
    },
    [sourceId, reload],
  );

  const activeRun = runs.find((run) => run.status === "running") ?? null;
  useEffect(() => {
    if (activeRun) void pollRuns(null);
  }, [activeRun, pollRuns]);

  const triggerRun = () => {
    const previousId = runs[0]?.id ?? null;
    void act(() => syncSource(sourceId), t("sourceDetail.runQueued"));
    void pollRuns(previousId);
  };

  const runNow = triggerRun;
  const retry = triggerRun;
  const reextract = () =>
    void (async () => {
      setBusy(true);
      setNotice("");
      try {
        const result = await reextractSourcePostings(sourceId);
        setNotice(t("sourceDetail.reextractQueued", { count: result.queued }));
      } catch (err) {
        setNotice(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    })();
  const test = () => {
    setBusy(true);
    setProbeNote("");
    probeSource(sourceId)
      .then((result) =>
        setProbeNote(
          result.ok
            ? t("sourceDetail.probeOk", { items: result.items ?? 0, ms: result.latency_ms ?? 0 })
            : t("sourceDetail.probeFail", {
                code: result.error?.code ?? "error",
                detail: result.error?.detail?.message ?? "",
              }),
        ),
      )
      .catch((err) => setProbeNote(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false));
  };
  const togglePause = () =>
    void act(() => updateSource(sourceId, { paused: Boolean(source?.paused_at) }));
  const remove = () =>
    void act(async () => {
      await deleteSource(sourceId);
      navigate(backTo);
    });

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: t("sourceDetail.tabOverview") },
    { id: "plan", label: t("sourceDetail.tabPlan") },
    { id: "config", label: t("sourceDetail.tabConfig") },
    { id: "runs", label: t("sourceDetail.tabRuns") },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6" data-testid="source-detail">
      <div className="space-y-1">
        <button
          type="button"
          className="text-sm text-[var(--as-muted-fg)] hover:underline"
          onClick={() => navigate(backTo)}
        >
          ← {t("sourceDetail.back")}
        </button>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-bold text-slate-900">{source?.key ?? sourceId}</h1>
          <span className="rounded-full border border-[var(--as-border)] px-2 py-0.5 text-xs">
            {source?.last_status ?? "…"}
          </span>
          {source?.paused_at ? (
            <span className="rounded-full border border-[var(--as-warning)] px-2 py-0.5 text-xs">
              {t("sourceDetail.paused")}
            </span>
          ) : null}
          <span className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" disabled={busy} onClick={runNow}>
              {t("sourceDetail.runNow")}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={test}>
              {t("sourceDetail.test")}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={togglePause}>
              {source?.paused_at ? t("sourceDetail.resume") : t("sourceDetail.pause")}
            </Button>
            <Button size="sm" variant="destructive" disabled={busy} onClick={remove}>
              {t("sourceDetail.remove")}
            </Button>
          </span>
        </div>
        {notice ? (
          <p role="status" className="text-sm text-[var(--as-muted-fg)]">
            {notice}
          </p>
        ) : null}
        {activeRun ? (
          <p
            role="status"
            className="flex items-center gap-2 text-sm text-[var(--as-fg)]"
            data-testid="running-now"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--as-info)] opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--as-info)]" />
            </span>
            <span className="font-medium">{t("sourceDetail.runningNow")}</span>
            <span className="text-[var(--as-muted-fg)]">
              {stageLabel(activeRun.report?.stage)}
              {" · "}
              {fmtDuration(
                Math.max(
                  0,
                  Date.now() - new Date(activeRun.started_at ?? Date.now()).getTime(),
                ),
              )}
              {typeof activeRun.report?.enriched === "number"
                ? ` · ${t("sourceDetail.enrichedCount", { count: activeRun.report.enriched })}`
                : ""}
            </span>
          </p>
        ) : null}
      </div>

      <div role="tablist" aria-label={t("sourceDetail.sections")} className="flex flex-wrap gap-2">
        {tabs.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-pressed={tab === entry.id}
            className={`rounded-[var(--as-radius-sm)] border px-3 py-1.5 text-sm ${
              tab === entry.id
                ? "border-[var(--as-focus-ring)] bg-[var(--as-surface-raised)] font-medium"
                : "border-[var(--as-border)] bg-[var(--as-muted)]"
            }`}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="space-y-3 rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-muted)] p-4">
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.connector")}
              </dt>
              <dd>{source?.connector_key ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.postings")}
              </dt>
              <dd>{source?.posting_count ?? 0}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.lastRun")}
              </dt>
              <dd>
                {fmtWhen(source?.last_run_at ?? null)}
                {cadenceEvery ? ` · ${t("sourceDetail.nextRun", {
                  time: nextRun ? nextRun.toLocaleTimeString() : "—",
                })}` : ""}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.queryMode")}
              </dt>
              <dd>
                {source?.query_mode === "radar"
                  ? t("sourceDetail.radarMode")
                  : t("sourceDetail.staticMode")}
              </dd>
            </div>
          </dl>
          {source?.error ? (
            <p role="alert" className="text-sm text-[var(--as-danger)]">
              {source.error}
            </p>
          ) : null}
          {probeNote ? (
            <p role="status" className="text-sm text-[var(--as-muted-fg)]">
              {probeNote}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--as-border)] pt-3">
            <div className="text-sm text-[var(--as-muted-fg)]">
              {t("sourceDetail.reextractHint")}
            </div>
            <Button size="sm" variant="outline" disabled={busy} onClick={reextract}>
              {t("sourceDetail.reextractBtn")}
            </Button>
          </div>
        </div>
      ) : null}

      {tab === "plan" && source ? (
        <div className="rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-muted)] p-4">
          <QueryPlanPanel source={source} />
        </div>
      ) : null}

      {tab === "config" && source ? (
        <div className="space-y-4 rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-muted)] p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="block text-sm" htmlFor="src-query-mode">
                {t("sourceDetail.queryMode")}
              </label>
              <select
                id="src-query-mode"
                className="w-full rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm"
                value={source.query_mode}
                onChange={(event) =>
                  void act(() =>
                    updateSource(sourceId, {
                      query_mode: event.target.value as "static" | "radar",
                    }),
                  )
                }
              >
                <option value="static">{t("sourceDetail.staticMode")}</option>
                <option value="radar">{t("sourceDetail.radarMode")}</option>
              </select>
            </div>
          </div>
          {source.tool_config_schema ? (
            <div
              className="space-y-3 rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid="pacing-card"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium">{t("sourceDetail.pacingTitle")}</div>
                <div className="text-xs text-[var(--as-muted-fg)]">
                  {t("sourceDetail.pacingHint")}
                </div>
              </div>
              {(
                [
                  {
                    label: t("sourceDetail.fetchDetails"),
                    items: [
                      { value: "off", label: t("sourceDetail.fetchOff") },
                      { value: "sample", label: t("sourceDetail.fetchSample") },
                      { value: "smart", label: t("sourceDetail.fetchSmart") },
                      { value: "all", label: t("sourceDetail.fetchAll") },
                    ],
                    selected: String(configValues.detail_mode ?? "off"),
                    select: (value: string) =>
                      updateValues({ ...configValues, detail_mode: value }),
                    hint: {
                      off: t("sourceDetail.fetchOffHint"),
                      sample: t("sourceDetail.fetchSampleHint"),
                      smart: t("sourceDetail.fetchSmartHint"),
                      all: t("sourceDetail.fetchAllHint"),
                    }[String(configValues.detail_mode ?? "off")],
                  },
                  {
                    label: t("sourceDetail.queriesPerSync"),
                    items: [1, 2, 3].map((count) => ({
                      value: String(count),
                      label: String(count),
                    })),
                    selected: String(localBatch),
                    select: (value: string) => updateBatch(Number(value)),
                    hint: t("sourceDetail.batchHint"),
                  },
                  {
                    label: t("sourceDetail.timeBudget"),
                    items: (() => {
                      const stored = String(configValues.budget_seconds ?? 80);
                      const presets = [
                        { value: "30", label: t("sourceDetail.budgetQuick") },
                        { value: "60", label: t("sourceDetail.budgetBalanced") },
                        { value: "90", label: t("sourceDetail.budgetThorough") },
                      ];
                      // a stored value outside the presets stays visible —
                      // never a verdict against an invisible number
                      return presets.some((item) => item.value === stored)
                        ? presets
                        : [
                            {
                              value: stored,
                              label: t("sourceDetail.budgetCustom", { seconds: stored }),
                            },
                            ...presets,
                          ];
                    })(),
                    selected: String(configValues.budget_seconds ?? 80),
                    select: (value: string) =>
                      updateValues({ ...configValues, budget_seconds: Number(value) }),
                    hint: t("sourceDetail.budgetHint"),
                  },
                ] as {
                  label: string;
                  items: { value: string; label: string }[];
                  selected: string;
                  select: (value: string) => void;
                  hint: string;
                }[]
              ).map((row) => (
                <div key={row.label} className="space-y-1.5">
                  <div className="text-sm">{row.label}</div>
                  <SegmentedTabs
                    items={row.items}
                    value={row.selected}
                    onValueChange={row.select}
                    ariaLabel={row.label}
                  />
                  {row.hint ? (
                    <p className="text-xs text-[var(--as-muted-fg)]">{row.hint}</p>
                  ) : null}
                </div>
              ))}
              {(() => {
                const pages = Number(configValues.max_pages ?? 2);
                const nav = Number(configValues.nav_delay_seconds ?? 2.5);
                const detailLimit = Number(configValues.detail_limit ?? 5);
                const mode = String(configValues.detail_mode ?? "off");
                const perGroup = pages * (nav + 7) + 5;
                let estimate = Math.round(
                  localBatch * perGroup + (localBatch > 1 ? (localBatch - 1) * 8 : 0),
                );
                // sample visits detail pages inline — the only mode that
                // lengthens the sync itself (smart/all run in the background)
                if (mode === "sample") estimate += detailLimit * 12;
                const budget = Number(configValues.budget_seconds ?? 80);
                const [tone, key] =
                  estimate <= budget * 0.75
                    ? ["text-[var(--as-success)]", "sourceDetail.paceFits"]
                    : estimate <= budget
                      ? ["text-[var(--as-warning)]", "sourceDetail.paceTight"]
                      : ["text-[var(--as-danger)]", "sourceDetail.paceOver"];
                return (
                  <p className={`text-sm ${tone}`} data-testid="pacing-estimate">
                    {key === "sourceDetail.paceFits"
                      ? t("sourceDetail.paceFits", { estimate })
                      : key === "sourceDetail.paceTight"
                        ? t("sourceDetail.paceTight", { estimate, budget })
                        : t("sourceDetail.paceOver", { estimate, budget })}
                  </p>
                );
              })()}
            </div>
          ) : null}
          {source.tool_config_schema ? (
            <IntegrationConfigForm
              presets={integrationConfigPresets(
                source.tool_config_schema as IntegrationConfigSchema,
              )}
              fields={parseIntegrationConfigSchema(
                source.tool_config_schema as IntegrationConfigSchema,
              ).filter((field) => field.name !== "budget_seconds" && field.name !== "detail_mode")}
              values={configValues}
              onValuesChange={updateValues}
              onSave={({ secrets }) =>
                void (async () => {
                  const packed = Object.fromEntries(
                    Object.entries(configValues)
                      .filter(([, value]) => value !== null && value !== undefined && value !== "")
                      .map(([key, value]) => [
                        key,
                        Array.isArray(value) ? value.join(",") : value,
                      ]),
                  );
                  await act(
                    () =>
                      updateSource(sourceId, {
                        config: {
                          ...(source.config as Record<string, unknown>),
                          options: JSON.stringify(packed),
                        },
                        query_mode: source.query_mode,
                        query_batch_size: localBatch,
                      }),
                    t("sourceDetail.configSaved"),
                  );
                  dirtyRef.current = false;
                  void secrets;
                })()
              }
              busy={busy}
              error={notice || null}
              secretSlots={{}}
              labels={{
                presetLabel: t("sourceDetail.presetLabel"),
                advancedLabel: t("sourceDetail.advancedLabel"),
                submitLabel: t("sourceDetail.saveConfig"),
                cancelLabel: t("toolsSettings.connectors.sources.cancel"),
                secretSetLabel: t("toolsSettings.connectors.sources.secretSetShort"),
                secretHintLabel: t("toolsSettings.connectors.sources.secretMissingShort"),
                enumPlaceholder: t("toolsSettings.connectors.sources.select"),
              }}
              onCancel={() => {
                dirtyRef.current = false;
                void reload();
              }}
            />
          ) : (
            <p className="text-xs text-[var(--as-muted-fg)]">{t("sourceDetail.configHint")}</p>
          )}
        </div>
      ) : null}

      {tab === "runs" ? (
        <div className="space-y-3 rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-muted)] p-4">
          {runs.length === 0 ? (
            <p className="text-sm text-[var(--as-muted-fg)]" data-testid="runs-empty">
              {t("sourceDetail.runsEmpty")}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-[var(--as-muted-fg)]">
                    <th className="p-2">{t("sourceDetail.runStarted")}</th>
                    <th className="p-2">{t("sourceDetail.runTrigger")}</th>
                    <th className="p-2">{t("sourceDetail.runStatus")}</th>
                    <th className="p-2">{t("sourceDetail.runDuration")}</th>
                    <th className="p-2">{t("sourceDetail.runItems")}</th>
                    <th className="p-2">{t("sourceDetail.runError")}</th>
                    <th className="p-2" />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.id}
                      className="border-t border-[var(--as-border)]"
                      data-testid={`run-${run.id}`}
                    >
                      <td className="p-2">{fmtWhen(run.started_at)}</td>
                      <td className="p-2">{run.trigger}</td>
                      <td className="p-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            run.status === "ok"
                              ? "bg-[var(--as-success)]/15"
                              : run.status === "failed"
                                ? "bg-[var(--as-danger)]/15"
                                : run.status === "running"
                                  ? "bg-[var(--as-info)]/15"
                                  : "bg-[var(--as-warning)]/15"
                          }`}
                        >
                          {runStatusLabel(run)}
                        </span>
                      </td>
                      <td className="p-2">
                        {run.status === "running"
                          ? fmtDuration(
                              Math.max(
                                0,
                                Date.now() - new Date(run.started_at ?? Date.now()).getTime(),
                              ),
                            )
                          : fmtDuration(run.duration_ms)}
                      </td>
                      <td className="p-2">{run.items_synced}</td>
                      <td className="p-2">
                        <span
                          className="line-clamp-3 max-w-md text-xs"
                          title={run.error}
                          data-testid={`run-error-${run.id}`}
                        >
                          {run.status === "degraded" &&
                          (run.report?.errors ?? []).some((entry) => entry?.code === "budget")
                            ? t("sourceDetail.budgetKept", { count: run.items_synced })
                            : run.error || "—"}
                        </span>
                      </td>
                      <td className="p-2">
                        <div className="flex gap-2">
                          {run.error ? (
                            <Button
                              size="sm"
                              variant="outline"
                              data-testid={`run-details-${run.id}`}
                              onClick={() => setDetailsRun(run)}
                            >
                              {t("sourceDetail.runDetails")}
                            </Button>
                          ) : null}
                          <Button size="sm" variant="outline" disabled={busy} onClick={retry}>
                            {t("sourceDetail.runAgain")}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      {detailsRun !== null ? (
        <RunDetailsDialog run={detailsRun} onClose={() => setDetailsRun(null)} />
      ) : null}
    </div>
  );
}
