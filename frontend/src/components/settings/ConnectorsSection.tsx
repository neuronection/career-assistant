import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Loader2, RefreshCw, Save, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import * as aiApi from "@/api/ai";
import type { WebSettings } from "@/api/ai";
import * as sourcesApi from "@/api/sources";
import type { ConnectorCatalogEntry, PostingSource, SourceProbe } from "@/api/sources";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";
import {
  IntegrationConfigForm,
  IntegrationInstancesList,
  parseIntegrationConfigSchema,
} from "@/components/ui/integrations";
import { ConfirmationModal } from "@/components/ui";
import type {
  IntegrationConfigSchema,
  IntegrationConfigValues,
  IntegrationExtensionGroupView,
} from "@/components/ui/integrations";
import { ConnectorDocsDialog } from "@/components/settings/ConnectorDocsDialog";
import { QueryPlanDialog } from "@/components/settings/QueryPlanDialog";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";
import { McpServerSection } from "@/components/settings/McpServerSection";

/**
 * Tools → connectors (ADR-0033, domain tools.connectors — broadened by
 * plan 32 Phase 1 to job-source connectors): external-service credentials
 * for the chat tools (MCP GitHub token) AND posting-source connector
 * instances. Plan 33 Phase B: the rows render through the family kit
 * (IntegrationInstancesList — probe/sync stay app-owned domain actions)
 * and the catalog-driven form is IntegrationConfigForm (sealed x-secret
 * slots, never echoed; values out, the host validates at save).
 */

type SourceDraft = {
  id: string | null;
  key: string;
  connector_key: string;
  config: IntegrationConfigValues;
  query_mode: string;
  query_batch_size: number;
};

export function ConnectorsSection() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<WebSettings | null>(null);
  const [githubToken, setGithubToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");

  useEffect(() => {
    aiApi
      .fetchWebSettings()
      .then(setSettings)
      .catch((err) => setError(apiDetail(err)));
  }, []);

  const save = async (payload: { github_token?: string }) => {
    setBusy(true);
    setError("");
    setSavedNote("");
    try {
      const data = await aiApi.updateWebSettings(payload);
      setSettings(data);
      setGithubToken("");
      setSavedNote(t("toolsSettings.connectors.saved"));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !error) return null;

  return (
    <div className="space-y-8" data-testid="connectors-section">
      <div className="space-y-3" data-testid="github-token-field">
        <h3 className="text-sm font-semibold">{t("toolsSettings.connectors.mcpTitle")}</h3>
        <p className="text-sm text-slate-500">{t("toolsSettings.connectors.mcpHint")}</p>
        <div className="space-y-1">
          <label className="text-sm font-medium" htmlFor="github-token">
            {t("toolsSettings.connectors.githubToken")}{" "}
            {settings?.github_token_set
              ? `(${t("toolsSettings.connectors.tokenSet")})`
              : `(${t("toolsSettings.connectors.tokenOptional")})`}
          </label>
          <input
            id="github-token"
            data-testid="github-token-input"
            type="password"
            value={githubToken}
            onChange={(e) => setGithubToken(e.target.value)}
            placeholder={t("toolsSettings.connectors.sources.githubTokenPlaceholder")}
            autoComplete="off"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <Button
          size="sm"
          disabled={busy || githubToken.length === 0}
          data-testid="save-github-token"
          onClick={() => void save({ github_token: githubToken })}
        >
          <Save className="w-4 h-4" />
          {t("toolsSettings.connectors.saveToken")}
        </Button>
      </div>

      {savedNote ? (
        <p className="text-xs text-emerald-600" data-testid="connectors-saved-note">
          {savedNote}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-red-600" data-testid="connectors-error">
          {error}
        </p>
      ) : null}

      <McpServerSection />
      <JobSourceConnectors />
      <ExtensionSourcesSection />
    </div>
  );
}

function JobSourceConnectors() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  useEffect(() => {
    const onChange = () => {
      void refresh();
    };
    window.addEventListener("ca:job-sources-changed", onChange);
    return () => window.removeEventListener("ca:job-sources-changed", onChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [draft, setDraft] = useState<SourceDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [probingId, setProbingId] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, SourceProbe>>({});
  const [docsKey, setDocsKey] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<PostingSource | null>(null);
  const [planTarget, setPlanTarget] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSources(await sourcesApi.fetchAdminSources());
    } catch (err) {
      setNotice(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    sourcesApi.fetchConnectorCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, [refresh]);

  const catalogByKey = useMemo(
    () => Object.fromEntries(catalog.map((entry) => [entry.key, entry])),
    [catalog],
  );

  const save = async (form: SourceDraft, secrets: Record<string, string>) => {
    setBusy(true);
    setNotice("");
    try {
      const values = Object.fromEntries(
        Object.entries(form.config)
          .filter(([, value]) => value !== null && value !== undefined && value !== "")
          .map(([key, value]) => [key, Array.isArray(value) ? value.join(",") : value]),
      ) as Record<string, string | number | boolean>;
      const managedSource = form.id
        ? sources.find((row) => row.id === form.id && row.managed)
        : undefined;
      const config = managedSource
        ? {
            transport: managedSource.config.transport ?? "stdio",
            command: managedSource.config.command ?? "",
            url: managedSource.config.url ?? "",
            tool: managedSource.config.tool ?? "fetch_postings",
            allowed_tools: managedSource.config.allowed_tools ?? "",
            timeout_seconds: managedSource.config.timeout_seconds ?? 120,
            options: JSON.stringify(values),
          }
        : values;
      const payload = {
        key: form.key.trim(),
        connector_key: form.connector_key,
        config,
        query_mode: form.query_mode,
        query_batch_size: form.query_batch_size,
        secrets,
      };
      if (form.id) {
        await sourcesApi.updateSource(form.id, {
          config: payload.config,
          query_mode: form.query_mode,
          query_batch_size: form.query_batch_size,
          secrets,
        });
      } else {
        await sourcesApi.createSource(payload);
      }
      setDraft(null);
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const removeSource = async (source: PostingSource) => {
    setBusy(true);
    setNotice("");
    try {
      await sourcesApi.deleteSource(source.id);
      setRemoveTarget(null);
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const probe = async (source: PostingSource) => {
    setProbingId(source.id);
    try {
      const result = await sourcesApi.probeSource(source.id);
      setProbes((current) => ({ ...current, [source.id]: result }));
    } catch (err) {
      setProbes((current) => ({
        ...current,
        [source.id]: {
          ok: false,
          error: { code: "error", detail: { message: apiDetail(err) }, retryable: "no" },
        },
      }));
    } finally {
      setProbingId(null);
    }
  };

  const sync = async (source: PostingSource) => {
    setBusy(true);
    try {
      await sourcesApi.syncSource(source.id);
      setNotice(t("toolsSettings.connectors.sources.syncQueued", { key: source.key }));
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const sourceStatus = (source: PostingSource) => {
    if (source.last_status === "failed") return "failing" as const;
    if (source.last_status === "degraded") return "degraded" as const;
    if (source.error) return "failing" as const;
    return "ok" as const;
  };

  const groups = useMemo<IntegrationExtensionGroupView[]>(() => {
    const kinds = ["posting", "market", "university", "search", "webhook_in"];
    return kinds
      .map(
        (kind): IntegrationExtensionGroupView => ({
          extension: {
            id: `job-sources-${kind}`,
            name: t(`toolsSettings.connectors.sources.kind.${kind}`),
            originClass: "bundled",
            tier: "T1",
            categories: ["data"],
          },
          instances: sources
            .filter((source) => (source.kind || "posting") === kind)
            .map((source) => {
              const connector = catalogByKey[source.connector_key];
              const needsSecret = Object.entries(source.secret_hints).some(
                ([slot, hint]) => connector?.secret_fields.includes(slot) && !hint.set,
              );
              return {
                id: source.id,
                extensionId: source.connector_key,
                name: source.key,
                enabled: source.enabled && !source.paused_at,
                status: sourceStatus(source),
                lastSuccessAt: source.last_run_at,
                conditions: needsSecret ? (["needs-secret"] as const) : [],
                parked: Boolean(source.paused_at),
                originClass: "bundled" as const,
                tier: "T1" as const,
                digest: null,
                update: null,
              };
            }),
        }),
      )
      .filter((group) => group.instances.length > 0);
  }, [sources, catalogByKey, t]);

  const draftEntry = draft ? catalogByKey[draft.connector_key] : undefined;
  const draftSource = draft?.id ? sources.find((row) => row.id === draft.id) : undefined;
  const managedSchema = draftSource?.managed ? draftSource.tool_config_schema : null;
  const draftFields = useMemo(
    () =>
      managedSchema
        ? parseIntegrationConfigSchema(managedSchema as IntegrationConfigSchema)
        : draftEntry
          ? parseIntegrationConfigSchema(draftEntry.config_schema as IntegrationConfigSchema)
          : [],
    [draftEntry, managedSchema],
  );

  const draftSecretSlots = useMemo(() => {
    if (!draft?.id) return {};
    const source = sources.find((row) => row.id === draft.id);
    if (!source) return {};
    return Object.fromEntries(
      Object.entries(source.secret_hints).map(([slot, hint]) => [
        slot,
        { set: hint.set, hint: hint.hint ?? null },
      ]),
    );
  }, [draft, sources]);

  return (
    <div className="space-y-3" data-testid="job-sources-block">
      <h3 className="text-sm font-semibold">{t("toolsSettings.connectors.sources.title")}</h3>
      <p className="text-sm text-slate-500">{t("toolsSettings.connectors.sources.hint")}</p>

      <IntegrationInstancesList
        groups={groups}
        busy={busy || probingId !== null}
        labels={{
          emptyLabel: t("toolsSettings.connectors.sources.empty"),
          enableAriaLabel: t("toolsSettings.connectors.sources.enabledAria"),
          configureLabel: t("toolsSettings.connectors.sources.edit"),
          lastSuccessLabel: t("toolsSettings.connectors.sources.lastSuccess"),
          statusLabels: {
            ok: t("toolsSettings.connectors.sources.statusOk"),
            degraded: t("toolsSettings.connectors.sources.statusDegraded"),
            failing: t("toolsSettings.connectors.sources.statusFailing"),
          },
          conditionLabels: {
            "needs-config": t("toolsSettings.connectors.sources.needsConfig"),
            "needs-secret": t("toolsSettings.connectors.sources.needsSecret"),
          },
        }}
        onToggleEnabled={(instance, next) => {
          const source = sources.find((row) => row.id === instance.id);
          if (source) {
            void (async () => {
              setBusy(true);
              try {
                await sourcesApi.updateSource(
                  source.id,
                  next ? { enabled: true, paused: false } : { paused: true },
                );
                await refresh();
              } catch (err) {
                setNotice(apiDetail(err));
              } finally {
                setBusy(false);
              }
            })();
          }
        }}
        renderInstanceActions={(instance) => {
          const source = sources.find((row) => row.id === instance.id);
          if (!source) return null;
          const result = probes[source.id];
          return (
            <span className="flex flex-wrap items-center gap-2">
              {result ? (
                <span
                  className={
                    result.ok ? "text-xs text-emerald-600" : "text-xs text-amber-600"
                  }
                  data-testid={`job-source-probe-${source.key}`}
                >
                  {result.ok
                    ? t("toolsSettings.connectors.sources.probeOk", {
                        items: result.items ?? 0,
                        latency: result.latency_ms ?? 0,
                      })
                    : t("toolsSettings.connectors.sources.probeError", {
                        code: result.error?.code ?? "error",
                        detail: result.error?.detail ?? "",
                      })}
                </span>
              ) : null}
              {(source.kind || "posting") === "posting" ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={probingId === source.id}
                    onClick={() => void probe(source)}
                  >
                    {probingId === source.id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : null}
                    {t("toolsSettings.connectors.sources.test")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => void sync(source)}
                  >
                    <RefreshCw className="w-4 h-4" />
                    {t("toolsSettings.connectors.sources.sync")}
                  </Button>
                </>
              ) : null}
              {catalogByKey[source.connector_key]?.manifest?.docs ? (
                <Button
                  variant="outline"
                  size="sm"
                  data-testid={`connector-docs-${source.connector_key}`}
                  onClick={() => setDocsKey(source.connector_key)}
                >
                  <BookOpen className="w-4 h-4" />
                  {t("toolsSettings.connectors.docs.open", "Docs")}
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                data-testid={`query-plan-${source.key}`}
                onClick={() => setPlanTarget(source.id)}
              >
                {t("toolsSettings.connectors.sources.plan")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid={`manage-source-${source.key}`}
                onClick={() => navigate(`/sources/${source.id}`)}
              >
                {t("toolsSettings.connectors.sources.manage")}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                disabled={busy}
                aria-label={`${t("toolsSettings.connectors.sources.remove")}: ${source.key}`}
                data-testid={`remove-source-${source.key}`}
                onClick={() => setRemoveTarget(source)}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </span>
          );
        }}
      />

      <ConfirmationModal
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null);
        }}
        title={t("toolsSettings.connectors.sources.removeTitle", {
          key: removeTarget?.key ?? "",
        })}
        description={t("toolsSettings.connectors.sources.removeBody", {
          count: removeTarget?.posting_count ?? 0,
        })}
        confirmLabel={t("toolsSettings.connectors.sources.removeConfirm")}
        destructive
        busy={busy}
        onConfirm={() => {
          if (removeTarget) void removeSource(removeTarget);
        }}
      />

      {docsKey !== null ? (
        <ConnectorDocsDialog connectorKey={docsKey} onClose={() => setDocsKey(null)} />
      ) : null}
      {planTarget !== null ? (
        <QueryPlanDialog sourceId={planTarget} onClose={() => setPlanTarget(null)} />
      ) : null}

      {draft === null ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            setDraft({
              id: null,
              key: "",
              connector_key: catalog[0]?.key ?? "",
              config: {},
              query_mode: "static",
              query_batch_size: 1,
            })
          }
          data-testid="add-job-source"
        >
          {t("toolsSettings.connectors.sources.add")}
        </Button>
      ) : (
        <div
          className="space-y-2 rounded-md border border-slate-300 p-3"
          data-testid="job-source-form"
        >
          <div className="flex flex-wrap gap-2">
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm sm:w-auto"
              value={draft.connector_key}
              disabled={draft.id !== null}
              aria-label={t("toolsSettings.connectors.sources.connector")}
              onChange={(event) =>
                setDraft({ ...draft, connector_key: event.target.value, config: {} })
              }
            >
              {catalog.map((connector) => (
                <option key={connector.key} value={connector.key}>
                  {connector.title}
                </option>
              ))}
            </select>
            <input
              className="w-full flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={t("toolsSettings.connectors.sources.key")}
              value={draft.key}
              disabled={draft.id !== null}
              onChange={(event) => setDraft({ ...draft, key: event.target.value })}
            />
          </div>
          {catalogByKey[draft.connector_key]?.capabilities?.dynamic_queries ||
          draft.query_mode === "radar" ? (
            <div className="space-y-1">
              <label className="block text-sm" htmlFor="job-source-query-mode">
                {t("toolsSettings.connectors.sources.queryMode")}
              </label>
              <select
                id="job-source-query-mode"
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                value={draft.query_mode}
                onChange={(event) => setDraft({ ...draft, query_mode: event.target.value })}
              >
                <option value="static">
                  {t("toolsSettings.connectors.sources.queryModeStatic")}
                </option>
                <option value="radar">
                  {t("toolsSettings.connectors.sources.queryModeRadar")}
                </option>
              </select>
              {draft.query_mode === "radar" ? (
                <>
                  <p className="text-xs text-slate-600" data-testid="job-source-query-info">
                    {t("toolsSettings.connectors.sources.queryModeRadarHint")}
                    {(() => {
                      const existing = sources.find((row) => row.id === draft.id);
                      const info = existing?.query_info;
                      return info?.keywords
                        ? ` ${t("toolsSettings.connectors.sources.queryNext", {
                            rotation: info.rotation,
                            keywords: info.keywords,
                          })}`
                        : "";
                    })()}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-sm" htmlFor="job-source-batch">
                      {t("toolsSettings.connectors.sources.queryBatch")}
                    </label>
                    <select
                      id="job-source-batch"
                      className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                      value={draft.query_batch_size}
                      aria-label={t("toolsSettings.connectors.sources.queryBatch")}
                      onChange={(event) =>
                        setDraft({ ...draft, query_batch_size: Number(event.target.value) })
                      }
                    >
                      <option value={1}>1</option>
                      <option value={2}>2</option>
                      <option value={3}>3</option>
                    </select>
                    <span className="text-xs text-slate-600">
                      {t("toolsSettings.connectors.sources.queryBatchHint")}
                    </span>
                  </div>
                </>
              ) : null}
            </div>
          ) : null}
          <IntegrationConfigForm
            fields={draftFields}
            values={draft.config}
            onValuesChange={(values) => setDraft({ ...draft, config: values })}
            onSave={({ secrets }) => void save(draft, secrets)}
            busy={busy}
            error={notice || null}
            secretSlots={draftSecretSlots}
            conditions={[]}
            labels={{
              submitLabel: t("toolsSettings.connectors.sources.save"),
              cancelLabel: t("toolsSettings.connectors.sources.cancel"),
              secretSetLabel: t("toolsSettings.connectors.sources.secretSetShort"),
              secretHintLabel: t("toolsSettings.connectors.sources.secretMissingShort"),
              enumPlaceholder: t("toolsSettings.connectors.sources.select"),
            }}
            onCancel={() => setDraft(null)}
          />
        </div>
      )}
    </div>
  );
}
