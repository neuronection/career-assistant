import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import {
  IntegrationConfigForm,
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
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
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

  useEffect(() => {
    if (!source) return;
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

  const stageLabel = (stage: unknown): string => {
    if (stage === "fetching") return t("sourceDetail.stageFetching");
    if (stage === "ingesting") return t("sourceDetail.stageIngesting");
    if (stage === "enriching") return t("sourceDetail.stageEnriching");
    return typeof stage === "string" ? stage : "";
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
      try {
        for (let attempt = 0; attempt < 90; attempt += 1) {
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
            <div className="space-y-1">
              <label className="block text-sm" htmlFor="src-batch">
                {t("sourceDetail.batch")}
              </label>
              <select
                id="src-batch"
                className="w-full rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm"
                value={source.query_batch_size}
                onChange={(event) =>
                  void act(() =>
                    updateSource(sourceId, { query_batch_size: Number(event.target.value) }),
                  )
                }
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
                <option value={3}>3</option>
              </select>
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("toolsSettings.connectors.sources.queryBatchHint")}
              </p>
            </div>
          </div>
          {source.tool_config_schema ? (
            <IntegrationConfigForm
              fields={parseIntegrationConfigSchema(
                source.tool_config_schema as IntegrationConfigSchema,
              )}
              values={configValues}
              onValuesChange={setConfigValues}
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
                        query_batch_size: source.query_batch_size,
                      }),
                    t("sourceDetail.configSaved"),
                  );
                  void secrets;
                })()
              }
              busy={busy}
              error={notice || null}
              secretSlots={{}}
              labels={{
                submitLabel: t("sourceDetail.saveConfig"),
                cancelLabel: t("toolsSettings.connectors.sources.cancel"),
                secretSetLabel: t("toolsSettings.connectors.sources.secretSetShort"),
                secretHintLabel: t("toolsSettings.connectors.sources.secretMissingShort"),
                enumPlaceholder: t("toolsSettings.connectors.sources.select"),
              }}
              onCancel={() => reload()}
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
                          {run.status === "running"
                            ? `${t("sourceDetail.runRunning")}${stageLabel(run.report?.stage) ? ` · ${stageLabel(run.report?.stage)}` : ""}`
                            : run.status}
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
                          {run.error || "—"}
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
