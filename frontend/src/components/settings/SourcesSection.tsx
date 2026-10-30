import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BookOpen, Loader2, MoreHorizontal, Plus, Radar, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Badge,
  Button,
  ConfirmationModal,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
} from "@/components/ui";import { IntegrationInstancesList } from "@/components/ui/integrations";
import type { IntegrationExtensionGroupView } from "@/components/ui/integrations";
import { ConnectorDocsDialog } from "@/components/settings/ConnectorDocsDialog";
import { QueryPlanDialog } from "@/components/settings/QueryPlanDialog";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";
import { AddSourceWizard, type SourceWizardDraft } from "@/components/settings/connectors/AddSourceWizard";
import * as sourcesApi from "@/api/sources";
import type { ConnectorCatalogEntry, PostingSource, SourceProbe } from "@/api/sources";
import { apiDetail } from "@/api/client";

/**
 * Tools → Sources (ADR-0033 domain tools.sources, plan 154): posting-source
 * connector instances and Git extension sources. Source rows follow the
 * family provider-card grammar — status + enable toggle on the row, Test as
 * the primary action, everything else in the ⋯ overflow; add-source is a
 * catalog-tiles wizard in a modal. The MCP server surface lives in its own
 * ?section=mcp view.
 */

function sourceStatus(source: PostingSource) {
  if (source.last_status === "failed") return "failing" as const;
  if (source.last_status === "degraded") return "degraded" as const;
  if (source.error) return "failing" as const;
  return "ok" as const;
}

export function SourcesSection() {
  return (
    <div className="space-y-5" data-testid="sources-section">
      <JobSourceConnectors />
      <ExtensionSourcesSection />
    </div>
  );
}

function JobSourceConnectors() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [draft, setDraft] = useState<SourceWizardDraft | null>(null);
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
    const onChange = () => {
      void refresh();
    };
    window.addEventListener("ca:job-sources-changed", onChange);
    return () => window.removeEventListener("ca:job-sources-changed", onChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void refresh();
    sourcesApi.fetchConnectorCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, [refresh]);

  const catalogByKey = useMemo(
    () => Object.fromEntries(catalog.map((entry) => [entry.key, entry])),
    [catalog]
  );

  const save = async (form: SourceWizardDraft, secrets: Record<string, string>) => {
    setBusy(true);
    setNotice("");
    try {
      const values = Object.fromEntries(
        Object.entries(form.config)
          .filter(([, value]) => value !== null && value !== undefined && value !== "")
          .map(([key, value]) => [
            key,
            Array.isArray(value) ? value.join(",") : value,
          ])
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
      if (form.id) {
        await sourcesApi.updateSource(form.id, {
          config,
          query_mode: form.query_mode,
          query_batch_size: form.query_batch_size,
          secrets,
        });
      } else {
        await sourcesApi.createSource({
          key: form.key.trim(),
          connector_key: form.connector_key,
          config,
          query_mode: form.query_mode,
          query_batch_size: form.query_batch_size,
          secrets,
        });
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
                ([slot, hint]) =>
                  connector?.secret_fields.includes(slot) && !hint.set
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
        })
      )
      .filter((group) => group.instances.length > 0);
  }, [sources, catalogByKey, t]);

  const draftEntry = draft ? catalogByKey[draft.connector_key] : undefined;
  const draftSource = draft?.id ? sources.find((row) => row.id === draft.id) : undefined;
  const managedSchema = draftSource?.managed ? draftSource.tool_config_schema : null;
  const radarCapable =
    draftEntry?.capabilities?.dynamic_queries === true ||
    draft?.query_mode === "radar" ||
    Boolean(draftSource?.query_mode === "radar");
  const draftSecretSlots = useMemo(() => {
    if (!draft?.id) return {};
    const source = sources.find((row) => row.id === draft.id);
    if (!source) return {};
    return Object.fromEntries(
      Object.entries(source.secret_hints).map(([slot, hint]) => [
        slot,
        { set: hint.set, hint: hint.hint ?? null },
      ])
    );
  }, [draft, sources]);
  const queryInfoNote = useMemo(() => {
    const existing = draft?.id ? sources.find((row) => row.id === draft.id) : undefined;
    const info = existing?.query_info;
    if (!info?.keywords) return "";
    return `${t("toolsSettings.connectors.sources.queryModeRadarHint")} ${t(
      "toolsSettings.connectors.sources.queryNext",
      { rotation: info.rotation, keywords: info.keywords }
    )}`;
  }, [draft?.id, sources, t]);

  const failing = sources.filter((s) => sourceStatus(s) === "failing").length;
  const degraded = sources.filter((s) => sourceStatus(s) === "degraded").length;
  const active = sources.filter((s) => s.enabled && !s.paused_at).length;
  const lastSync = sources
    .map((s) => s.last_run_at)
    .filter((run): run is string => Boolean(run))
    .sort()
    .slice(-1)[0];

  return (
    <div className="space-y-4" data-testid="job-sources-block">
      <section
        className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:p-5"
        data-testid="settings-section-job-sources"
        aria-labelledby="settings-section-job-sources-title"
      >
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2
                id="settings-section-job-sources-title"
                className="text-sm font-semibold text-[var(--as-fg)]"
              >
                {t("toolsSettings.connectors.sources.title")}
              </h2>
              {failing > 0 ? (
                <Badge variant="danger" data-testid="job-sources-failing">
                  {t("toolsSettings.connectors.sources.healthFailing", { count: failing })}
                </Badge>
              ) : null}
              {degraded > 0 ? (
                <Badge variant="warning">
                  {t("toolsSettings.connectors.sources.healthDegraded", { count: degraded })}
                </Badge>
              ) : null}
            </div>
            <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
              {t("toolsSettings.connectors.sources.hint")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="flex items-center gap-1.5 text-xs text-[var(--as-muted-fg)]">
              <Badge variant="secondary" data-testid="job-sources-count">
                {t("toolsSettings.connectors.sources.healthActive", { count: active })}
              </Badge>
              {lastSync
                ? t("toolsSettings.connectors.sources.lastSync", {
                    date: new Date(lastSync).toLocaleString(),
                  })
                : null}
            </span>
            <Button
              size="sm"
              onClick={() =>
                setDraft({
                  id: null,
                  key: "",
                  connector_key: "",
                  config: {},
                  query_mode: "static",
                  query_batch_size: 1,
                })
              }
              data-testid="add-job-source"
            >
              <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.connectors.sources.add")}
            </Button>
          </div>
        </div>

        <div className="mt-3">
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
                      next ? { enabled: true, paused: false } : { paused: true }
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
              const connector = catalogByKey[source.connector_key];
              const isPosting = (source.kind || "posting") === "posting";
              return (
                <span className="flex flex-wrap items-center justify-end gap-1.5">
                  {result ? (
                    <span
                      className={
                        result.ok
                          ? "text-xs text-emerald-600"
                          : "text-xs text-amber-600"
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
                  {isPosting ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={probingId === source.id}
                      onClick={() => void probe(source)}
                    >
                      {probingId === source.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Radar className="h-3.5 w-3.5" />
                      )}
                      {t("toolsSettings.connectors.sources.test")}
                    </Button>
                  ) : null}
                  <Menu>
                    <MenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`${t("toolsSettings.connectors.sources.actions")}: ${source.key}`}
                        data-testid={`source-actions-${source.key}`}
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </MenuTrigger>
                    <MenuContent align="end">
                      {isPosting ? (
                        <MenuItem
                          data-testid={`sync-source-${source.key}`}
                          disabled={busy}
                          onSelect={() => void sync(source)}
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                          {t("toolsSettings.connectors.sources.sync")}
                        </MenuItem>
                      ) : null}
                      {connector?.manifest?.docs ? (
                        <MenuItem
                          data-testid={`connector-docs-${source.connector_key}`}
                          onSelect={() => setDocsKey(source.connector_key)}
                        >
                          <BookOpen className="h-3.5 w-3.5" />
                          {t("toolsSettings.connectors.docs.open", "Docs")}
                        </MenuItem>
                      ) : null}
                      <MenuItem
                        data-testid={`query-plan-${source.key}`}
                        onSelect={() => setPlanTarget(source.id)}
                      >
                        {t("toolsSettings.connectors.sources.plan")}
                      </MenuItem>
                      <MenuItem
                        data-testid={`manage-source-${source.key}`}
                        onSelect={() =>
                          navigate(`/sources/${source.id}`, {
                            state: {
                              from: `${location.pathname}${location.search}`,
                            },
                          })
                        }
                      >
                        {t("toolsSettings.connectors.sources.manage")}
                      </MenuItem>
                      <MenuItem
                        data-testid={`remove-source-${source.key}`}
                        disabled={busy}
                        onSelect={() => setRemoveTarget(source)}
                      >
                        {t("toolsSettings.connectors.sources.remove")}
                      </MenuItem>
                    </MenuContent>
                  </Menu>
                </span>
              );
            }}
          />
        </div>

        {notice ? (
          <p
            className="mt-2 rounded-lg bg-[var(--as-muted)] px-2.5 py-1.5 text-xs text-[var(--as-fg)]"
            data-testid="job-sources-notice"
          >
            {notice}
          </p>
        ) : null}

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

        {draft !== null ? (
          <div className="mt-3">
            <AddSourceWizard
              catalog={catalog}
              existingKeys={sources.map((row) => row.key)}
              busy={busy}
              error={notice || null}
              secretSlots={draftSecretSlots}
              managedSchema={managedSchema as never}
              radarCapable={radarCapable}
              queryInfoNote={queryInfoNote}
              draft={draft}
              onPick={(connector) =>
                setDraft({ ...draft, connector_key: connector.key, config: {} })
              }
              onBack={() => setDraft({ ...draft, connector_key: "", config: {} })}
              onDraftChange={setDraft}
              onSave={(secrets) => void save(draft, secrets)}
              onCancel={() => setDraft(null)}
              onDocs={(key) => setDocsKey(key)}
            />
          </div>
        ) : null}
      </section>
    </div>
  );
}
