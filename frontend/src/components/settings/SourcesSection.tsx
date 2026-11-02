import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BookOpen, Globe, Loader2, MoreHorizontal, Pencil, Plus, Radar, RefreshCw } from "lucide-react";
import { SwitchRow } from "@/components/ui/switch-row";
import { SearchInput } from "@/components/ui";
import { BulkBar, SelectionToggle } from "@/features/profile/components/profile/BulkTools";
import { useTranslation } from "react-i18next";
import {
  Badge,
  Button,
  ConfirmationModal,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
} from "@/components/ui";
import { ItemCardShell } from "@/components/cards/ItemCardShell";
import { ConnectorDocsDialog } from "@/components/settings/ConnectorDocsDialog";
import { QueryPlanDialog } from "@/components/settings/QueryPlanDialog";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";
import { AddSourceWizard, type SourceWizardDraft } from "@/components/settings/connectors/AddSourceWizard";
import { JobSourcePresetDialog } from "@/components/settings/connectors/JobSourcePresetDialog";
import { PresetLogo } from "@/components/settings/connectors/PresetLogo";
import {
  JOB_SOURCE_PRESETS,
  type JobSourcePreset,
} from "@/config/jobSourcePresets";
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

const STATUS_TONE: Record<string, { dot: string; labelKey: string }> = {
  ok: { dot: "bg-emerald-500", labelKey: "toolsSettings.connectors.sources.statusOk" },
  degraded: { dot: "bg-[var(--as-warning)]", labelKey: "toolsSettings.connectors.sources.statusDegraded" },
  failing: { dot: "bg-[var(--as-danger)]", labelKey: "toolsSettings.connectors.sources.statusFailing" },
};

function shortTime(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function JobSourceCard({
  source,
  connector,
  probe,
  probing,
  busy,
  needsSecret,
  onToggle,
  onTest,
  onSync,
  onDocs,
  onPlan,
  onManage,
  onEdit,
  onRemove,
  selected,
  onSelect,
}: {
  source: PostingSource;
  connector?: ConnectorCatalogEntry;
  probe?: SourceProbe;
  probing: boolean;
  busy: boolean;
  needsSecret: boolean;
  onToggle: (next: boolean) => void;
  onTest: () => void;
  onSync: () => void;
  onDocs: () => void;
  onPlan: () => void;
  onManage: () => void;
  onEdit: () => void;
  onRemove: () => void;
  selected?: boolean;
  onSelect?: (next: boolean) => void;
}) {
  const { t } = useTranslation();
  const paused = Boolean(source.paused_at);
  const active = source.enabled && !paused;
  const tone = STATUS_TONE[sourceStatus(source)] ?? STATUS_TONE.ok;
  const isPosting = (source.kind || "posting") === "posting";
  const lastSuccess = shortTime(source.last_run_at);
  const Icon = source.kind === "market" ? Globe : Radar;
  const preset = JOB_SOURCE_PRESETS.find((entry) => entry.slug === source.key);

  return (
    <ItemCardShell
      testId={`integration-instance-${source.id}`}
      density="compact"
      onOpen={onManage}
      className="gap-3 p-3.5"
      actions={
        <>
          {onSelect ? (
            <span
              className="shrink-0"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <SelectionToggle
                selected={selected ?? false}
                label={`${t("toolsSettings.connectors.sources.selectAria")}: ${source.key}`}
                onToggle={() => onSelect(!selected)}
              />
            </span>
          ) : null}
          {isPosting ? (
            <Button size="sm" variant="outline" disabled={probing} onClick={onTest}>
              {probing ? (
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
              <MenuItem data-testid={`edit-source-${source.key}`} disabled={busy} onSelect={onEdit}>
                <Pencil className="h-3.5 w-3.5" />
                {t("toolsSettings.connectors.sources.edit")}
              </MenuItem>
              {isPosting ? (
                <MenuItem
                  data-testid={`sync-source-${source.key}`}
                  disabled={busy}
                  onSelect={onSync}
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  {t("toolsSettings.connectors.sources.sync")}
                </MenuItem>
              ) : null}
              {connector?.manifest?.docs ? (
                <MenuItem
                  data-testid={`connector-docs-${source.connector_key}`}
                  onSelect={onDocs}
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  {t("toolsSettings.connectors.docs.open", "Docs")}
                </MenuItem>
              ) : null}
              <MenuItem data-testid={`query-plan-${source.key}`} onSelect={onPlan}>
                {t("toolsSettings.connectors.sources.plan")}
              </MenuItem>
              <MenuItem data-testid={`manage-source-${source.key}`} onSelect={onManage}>
                {t("toolsSettings.connectors.sources.manage")}
              </MenuItem>
              <MenuItem
                data-testid={`remove-source-${source.key}`}
                disabled={busy}
                onSelect={onRemove}
              >
                {t("toolsSettings.connectors.sources.remove")}
              </MenuItem>
            </MenuContent>
          </Menu>
        </>
      }
    >
      <div className="flex min-w-0 flex-1 items-start gap-2.5">
        {preset ? (
          <span className="shrink-0" aria-hidden>
            <PresetLogo preset={preset} size={32} />
          </span>
        ) : (
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--as-primary)_10%,var(--as-surface-raised))] text-[var(--as-primary)]"
            aria-hidden
          >
            <Icon className="h-4 w-4" />
          </span>
        )}
        <div className="min-w-0 flex-1 space-y-1.5">
          <button
            type="button"
            className="block w-full min-w-0 truncate text-left text-sm font-semibold text-[var(--as-fg)] hover:text-[var(--as-accent)]"
            title={t("sourceDetail.openSource")}
            data-testid={`job-source-name-${source.key}`}
          >
            {source.key}
          </button>
          <p className="truncate text-xs text-[var(--as-muted-fg)]">
            {connector?.title ?? source.connector_key}
          </p>

          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--as-muted)] px-2 py-0.5">
              <span
                className={`h-1.5 w-1.5 rounded-full ${active ? tone.dot : "bg-[var(--as-muted-fg)]"}`}
                aria-hidden
              />
              <span className="text-[var(--as-fg)]">
                {paused
                  ? t("toolsSettings.connectors.sources.paused")
                  : active
                    ? t(tone.labelKey)
                    : t("toolsSettings.connectors.sources.paused")}
              </span>
            </span>
            <span className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[var(--as-muted-fg)]">
              {source.managed
                ? t("toolsSettings.connectors.sources.originMcp")
                : t("toolsSettings.connectors.sources.originBundled")}
            </span>
            <span className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[var(--as-muted-fg)]">
              T1
            </span>
            {needsSecret ? (
              <span
                className="rounded-full bg-[color-mix(in_srgb,var(--as-warning)_18%,transparent)] px-2 py-0.5 font-medium text-[var(--as-fg)]"
                data-testid={`integration-condition-${source.id}-needs-secret`}
              >
                {t("toolsSettings.connectors.sources.needsSecret")}
              </span>
            ) : null}
          </div>

          <p className="text-xs text-[var(--as-muted-fg)]">
            {source.posting_count != null
              ? t("companies.openPostings", { count: source.posting_count })
              : null}
            {lastSuccess
              ? ` · ${t("toolsSettings.connectors.sources.lastSuccess")} ${lastSuccess}`
              : ""}
            {source.error ? (
              <span className="block truncate text-[var(--as-danger)]">{source.error}</span>
            ) : null}
          </p>

          {probe ? (
            <p
              className={probe.ok ? "text-xs text-emerald-600" : "text-xs text-amber-600"}
              data-testid={`job-source-probe-${source.key}`}
            >
              {probe.ok
                ? t("toolsSettings.connectors.sources.probeOk", {
                    items: probe.items ?? 0,
                    latency: probe.latency_ms ?? 0,
                  })
                : t("toolsSettings.connectors.sources.probeError", {
                    code: probe.error?.code ?? "error",
                    detail: probe.error?.detail ?? "",
                  })}
            </p>
          ) : null}
        </div>
        <div
          className="shrink-0"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <SwitchRow
            label={t("toolsSettings.connectors.sources.enabledAria") + ": " + source.key}
            checked={active}
            hideLabel
            disabled={busy}
            onCheckedChange={onToggle}
            className="w-auto shrink-0 border-none bg-transparent px-0 py-0 hover:bg-transparent"
            data-testid={`job-source-toggle-${source.key}`}
          />
        </div>
      </div>
    </ItemCardShell>
  );
}

function JobSourceConnectors() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [draft, setDraft] = useState<SourceWizardDraft | null>(null);
  const [presetOpen, setPresetOpen] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set());
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
          ...(form.title ? { title: form.title } : {}),
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

  const addPresets = async (
    presets: JobSourcePreset[],
  ): Promise<{ preset: JobSourcePreset; ok: boolean; detail?: string }[]> => {
    setBusy(true);
    const outcomes: { preset: JobSourcePreset; ok: boolean; detail?: string }[] = [];
    for (const preset of presets) {
      try {
        await sourcesApi.createSource({
          key: preset.slug,
          connector_key: preset.connectorKey,
          config: { ...preset.config },
          query_mode: "static",
          query_batch_size: 2,
          title: preset.name,
        });
        outcomes.push({ preset, ok: true });
      } catch (err) {
        outcomes.push({ preset, ok: false, detail: apiDetail(err) });
      }
    }
    await refresh();
    setBusy(false);
    if (outcomes.every((outcome) => outcome.ok)) {
      setPresetOpen(false);
      setNotice(
        t("toolsSettings.connectors.presets.addedNotice", {
          count: outcomes.length,
          total: outcomes.length,
        }),
      );
    }
    return outcomes;
  };

  const kindOrder = ["posting", "market", "university", "search", "webhook_in"] as const;
  const query = sourceQuery.trim().toLowerCase();
  const visibleSources = sources.filter(
    (source) =>
      !query ||
      [source.key, source.connector_key, source.title ?? "", source.error ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(query),
  );
  const groups = useMemo(
    () =>
      kindOrder
        .map((kind) => ({
          kind,
          label: t(`toolsSettings.connectors.sources.kind.${kind}`),
          sources: visibleSources.filter((source) => (source.kind || "posting") === kind),
        }))
        .filter((group) => group.sources.length > 0),
    [visibleSources, t],
  );
  const needsSecret = (source: PostingSource) => {
    // Only REQUIRED credentials badge (plan 180): optional slots (e.g. the
    // mcp bearer token) must not paint a working source as incomplete.
    const entry = catalogByKey[source.connector_key];
    if (entry?.capabilities?.requires_credentials !== true) return false;
    return Object.entries(source.secret_hints).some(
      ([slot, hint]) => entry.secret_fields.includes(slot) && !hint.set,
    );
  };

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

  const runBulk = async (action: "pause" | "resume" | "sync") => {
    const targets = sources.filter((source) => selectedSources.has(source.id));
    setBusy(true);
    let ok = 0;
    const failures: string[] = [];
    try {
      for (const source of targets) {
        try {
          if (action === "sync") {
            await sourcesApi.syncSource(source.id);
          } else {
            await sourcesApi.updateSource(
              source.id,
              action === "pause" ? { paused: true } : { enabled: true, paused: false },
            );
          }
          ok += 1;
        } catch (err) {
          failures.push(`${source.key}: ${apiDetail(err)}`);
        }
      }
      setSelectedSources(new Set());
      await refresh();
      const label =
        action === "pause"
          ? t("toolsSettings.connectors.sources.bulkPauseDone", { count: ok })
          : action === "resume"
            ? t("toolsSettings.connectors.sources.bulkResumeDone", { count: ok })
            : t("toolsSettings.connectors.sources.bulkSyncDone", { count: ok });
      const parts = [label];
      if (failures.length) parts.push(failures.join(" · "));
      setNotice(parts.join(" — "));
    } finally {
      setBusy(false);
    }
  };

  const failing = sources.filter((s) => sourceStatus(s) === "failing").length;  const degraded = sources.filter((s) => sourceStatus(s) === "degraded").length;
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
              onClick={() => setPresetOpen(true)}
              data-testid="add-job-source"
            >
              <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.connectors.sources.add")}
            </Button>
          </div>
        </div>

        {sources.length > 0 ? (
          <div className="mt-4 space-y-3">
            <div className="max-w-xs" data-testid="job-sources-search">
              <SearchInput
                value={sourceQuery}
                onChange={setSourceQuery}
                placeholder={t("toolsSettings.connectors.sources.searchPlaceholder")}
                ariaLabel={t("toolsSettings.connectors.sources.searchPlaceholder")}
                clearLabel={t("common.clear")}
              />
            </div>
            <BulkBar
              count={selectedSources.size}
              total={visibleSources.length}
              onClear={() => setSelectedSources(new Set())}
              onSelectAll={() =>
                setSelectedSources(new Set(visibleSources.map((source) => source.id)))
              }
              testid="job-sources-bulk"
            >
              <button
                type="button"
                data-testid="bulk-pause"
                disabled={busy}
                onClick={() => void runBulk("pause")}
                className="text-xs text-[var(--as-fg)] underline-offset-2 hover:underline"
              >
                {t("toolsSettings.connectors.sources.pauseSelected")}
              </button>
              <button
                type="button"
                data-testid="bulk-resume"
                disabled={busy}
                onClick={() => void runBulk("resume")}
                className="text-xs text-[var(--as-fg)] underline-offset-2 hover:underline"
              >
                {t("toolsSettings.connectors.sources.resumeSelected")}
              </button>
              <button
                type="button"
                data-testid="bulk-sync"
                disabled={busy}
                onClick={() => void runBulk("sync")}
                className="text-xs text-[var(--as-accent)] underline-offset-2 hover:underline"
              >
                {t("toolsSettings.connectors.sources.syncSelected")}
              </button>
            </BulkBar>
          </div>
        ) : null}
        <div className="mt-4 space-y-5">
          {groups.length === 0 ? (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("toolsSettings.connectors.sources.empty")}
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.kind} className="space-y-2">
                <div className="flex items-center gap-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {group.label}
                  </p>
                  <span className="text-[11px] text-[var(--as-muted-fg)]">
                    {group.sources.length}
                  </span>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  {group.sources.map((source) => (
                    <JobSourceCard
                      key={source.id}
                      source={source}
                      connector={catalogByKey[source.connector_key]}
                      probe={probes[source.id]}
                      probing={probingId === source.id}
                      busy={busy}
                      needsSecret={needsSecret(source)}
                      selected={selectedSources.has(source.id)}
                      onSelect={(next) =>
                        setSelectedSources((current) => {
                          const nextSet = new Set(current);
                          if (next) {
                            nextSet.add(source.id);
                          } else {
                            nextSet.delete(source.id);
                          }
                          return nextSet;
                        })
                      }
                      onToggle={(next) => {
                        setBusy(true);
                        try {
                          void sourcesApi
                            .updateSource(
                              source.id,
                              next ? { enabled: true, paused: false } : { paused: true }
                            )
                            .then(refresh)
                            .catch((err) => setNotice(apiDetail(err)));
                        } finally {
                          setBusy(false);
                        }
                      }}
                      onTest={() => void probe(source)}
                      onSync={() => void sync(source)}
                      onDocs={() => setDocsKey(source.connector_key)}
                      onPlan={() => setPlanTarget(source.id)}
                      onManage={() =>
                        navigate(`/sources/${source.id}`, {
                          state: { from: `${location.pathname}${location.search}` },
                        })
                      }
                      onEdit={() =>
                        setDraft({
                          id: source.id,
                          key: source.key,
                          connector_key: source.connector_key,
                          config: { ...source.config },
                          query_mode: source.query_mode,
                          query_batch_size: source.query_batch_size,
                        })
                      }
                      onRemove={() => setRemoveTarget(source)}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
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
      <JobSourcePresetDialog
        open={presetOpen}
        onOpenChange={setPresetOpen}
        existingKeys={sources.map((row) => row.key)}
        busy={busy}
        onAddPresets={addPresets}
        onCustom={() => {
          setPresetOpen(false);
          setDraft({
            id: null,
            key: "",
            connector_key: "",
            config: {},
            query_mode: "radar",
            query_batch_size: 2,
          });
        }}
      />
    </div>
  );
}
