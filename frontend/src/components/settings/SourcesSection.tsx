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
import { SelectField } from "@/features/cv/components/cv/formPrimitives";
import { countryDisplayName, findCountry } from "@neuronection/assistant-ui/countries";
import {
  JOB_SOURCE_PRESETS,
  WORLDWIDE_KEY,
  type JobSourcePreset,
} from "@/config/jobSourcePresets";
import {
  compareDocuments,
  fetchCatalogDocument,
  mergeCatalogs,
  validateCatalog,
  type CatalogFetchOutcome,
  type CatalogProvenance,
  type SourcesCatalog,
} from "@/config/sourcesCatalogs";
import * as sourcesApi from "@/api/sources";
import * as catalogsApi from "@/api/sourcesCatalogs";
import type { ConnectorCatalogEntry, PostingSource, SourceProbe } from "@/api/sources";
import { apiDetail } from "@/api/client";

const TIER_LABEL_KEY: Record<CatalogProvenance["tier"], string> = {
  bundled: "toolsSettings.connectors.presets.tierBundled",
  operator: "toolsSettings.connectors.presets.tierOperator",
  community: "toolsSettings.connectors.presets.tierCommunity",
  user: "toolsSettings.connectors.presets.tierUser",
};

function newCatalogId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `catalog-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

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

/** Country lens bucket: preset-added sources carry the preset's country
 * (ISO code or WORLDWIDE_KEY); everything else is the custom bucket. */
function sourceCountryKey(source: PostingSource): string {
  const preset = JOB_SOURCE_PRESETS.find((entry) => entry.slug === source.key);
  return preset ? (preset.country ?? WORLDWIDE_KEY) : "custom";
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

/** Plan 187: the catalog management block — add an operator/community URL,
 * upload a user JSON file, per-catalog refresh (browser-side conditional
 * GET) and remove. Refresh NEVER creates sources: it only updates the
 * gallery data through the admin API. */
function CatalogsBlock({
  catalogs,
  report,
  busy,
  onImportUrl,
  onImportFile,
  onRefresh,
  onRemove,
}: {
  catalogs: SourcesCatalog[];
  report: string[];
  busy: boolean;
  onImportUrl: (url: string, tier: "operator" | "community") => void;
  onImportFile: (file: File) => void;
  onRefresh: (catalog: SourcesCatalog) => void;
  onRemove: (catalog: SourcesCatalog) => void;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [tier, setTier] = useState<"operator" | "community">("community");
  return (
    <div
      className="rounded-lg border border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-muted)_35%,transparent)] p-3"
      data-testid="catalog-block"
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1 basis-40">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("toolsSettings.connectors.catalogs.title")}
          </p>
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
            {t("toolsSettings.connectors.catalogs.hint")}
          </p>
        </div>
        <label className="block min-w-0 flex-1 basis-56 text-xs text-[var(--as-muted-fg)]">
          <span className="sr-only">{t("toolsSettings.connectors.catalogs.urlPlaceholder")}</span>
          <input
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
            placeholder={t("toolsSettings.connectors.catalogs.urlPlaceholder")}
            value={url}
            disabled={busy}
            onChange={(event) => setUrl(event.target.value)}
            data-testid="catalog-url-input"
          />
        </label>
        <div className="w-40">
          <SelectField
            label={t("toolsSettings.connectors.catalogs.tier")}
            value={tier}
            onChange={(next) => setTier(next as "operator" | "community")}
            options={[
              { value: "community", label: t("toolsSettings.connectors.catalogs.tierCommunity") },
              { value: "operator", label: t("toolsSettings.connectors.catalogs.tierOperator") },
            ]}
            testId="catalog-tier-select"
          />
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onImportUrl(url.trim(), tier)}
          data-testid="catalog-add-url"
        >
          <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.connectors.catalogs.addUrl")}
        </Button>
        <label
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] transition-colors hover:border-[var(--as-accent)]"
          data-testid="catalog-upload-label"
        >
          {t("toolsSettings.connectors.catalogs.upload")}
          <input
            type="file"
            accept="application/json,.json"
            className="hidden"
            disabled={busy}
            data-testid="catalog-file-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onImportFile(file);
              event.target.value = "";
            }}
          />
        </label>
      </div>

      {report.length > 0 ? (
        <div className="mt-2 space-y-1" data-testid="catalog-report">
          {report.map((line, index) => (
            <p
              key={`${index}-${line}`}
              className="rounded-md bg-[var(--as-muted)] px-2 py-1 text-xs text-[var(--as-fg)]"
              data-testid={`catalog-report-line-${index}`}
            >
              {line}
            </p>
          ))}
        </div>
      ) : null}

      {catalogs.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="catalog-empty">
          {t("toolsSettings.connectors.catalogs.empty")}
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5" data-testid="catalog-list">
          {catalogs.map((catalog) => (
            <li
              key={catalog.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2.5 py-1.5"
              data-testid={`catalog-row-${catalog.id}`}
            >
              <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--as-fg)]">
                {catalog.name}
              </span>
              <span
                className="rounded-full bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
                data-testid={`catalog-tier-${catalog.id}`}
              >
                {t(TIER_LABEL_KEY[catalog.tier])}
              </span>
              <span className="text-[11px] text-[var(--as-muted-fg)]" data-testid={`catalog-stamp-${catalog.id}`}>
                {t("toolsSettings.connectors.catalogs.revision", {
                  revision: catalog.revision,
                  date: shortTime(catalog.fetchedAt) ?? "",
                })}
              </span>
              {catalog.url ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onRefresh(catalog)}
                  data-testid={`catalog-refresh-${catalog.id}`}
                >
                  <RefreshCw className="h-3 w-3" /> {t("toolsSettings.connectors.catalogs.refresh")}
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => onRemove(catalog)}
                data-testid={`catalog-remove-${catalog.id}`}
              >
                {t("toolsSettings.connectors.catalogs.remove")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
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
  provenance,
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
  provenance?: Map<string, CatalogProvenance>;
}) {
  const { t, i18n } = useTranslation();
  const language = (i18n as { language?: string } | undefined)?.language ?? "en";
  const paused = Boolean(source.paused_at);
  const active = source.enabled && !paused;
  const tone = STATUS_TONE[sourceStatus(source)] ?? STATUS_TONE.ok;
  const isPosting = (source.kind || "posting") === "posting";
  const lastSuccess = shortTime(source.last_run_at);
  const Icon = source.kind === "market" ? Globe : Radar;
  const preset = JOB_SOURCE_PRESETS.find((entry) => entry.slug === source.key);
  const importedTier = provenance?.get(source.key);

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
            {(() => {
              const lens = sourceCountryKey(source);
              if (lens === "custom") return null;
              const flag = lens === WORLDWIDE_KEY ? "🌍" : findCountry(lens)?.flag;
              return flag ? (
                <span
                  className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[var(--as-muted-fg)]"
                  title={lens === WORLDWIDE_KEY ? undefined : countryDisplayName(lens, language)}
                  data-testid={`source-country-${source.key}`}
                >
                  {flag}
                </span>
              ) : null;
            })()}
            {importedTier ? (
              <span
                className="rounded-full bg-[color-mix(in_srgb,var(--as-accent)_14%,transparent)] px-2 py-0.5 font-medium text-[var(--as-fg)]"
                data-testid={`source-provenance-${source.key}`}
              >
                {t(TIER_LABEL_KEY[importedTier.tier])}
              </span>
            ) : null}
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
  const { t, i18n } = useTranslation();
  const language = (i18n as { language?: string } | undefined)?.language ?? "en";
  const navigate = useNavigate();
  const location = useLocation();
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [catalogs, setCatalogs] = useState<SourcesCatalog[]>([]);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogReport, setCatalogReport] = useState<string[]>([]);
  const [removeCatalogTarget, setRemoveCatalogTarget] = useState<SourcesCatalog | null>(null);
  const [draft, setDraft] = useState<SourceWizardDraft | null>(null);
  const [presetOpen, setPresetOpen] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [countries, setCountries] = useState<Set<string> | null>(null);
  const [problemsOnly, setProblemsOnly] = useState(false);
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
    catalogsApi.fetchCatalogs().then(setCatalogs).catch(() => setCatalogs([]));
  }, [refresh]);

  const reloadCatalogs = async () => {
    try {
      setCatalogs(await catalogsApi.fetchCatalogs());
    } catch (err) {
      setCatalogReport([apiDetail(err)]);
    }
  };

  const fetchFailureLine = (outcome: CatalogFetchOutcome): string | null => {
    switch (outcome.kind) {
      case "not-modified":
        return t("toolsSettings.connectors.catalogs.reportAlreadyLatest");
      case "fetch-failed":
        return t("toolsSettings.connectors.catalogs.reportFetchFailed");
      case "mixed-content":
        return t("toolsSettings.connectors.catalogs.reportMixedContent");
      case "http-error":
        return t("toolsSettings.connectors.catalogs.reportHttpError", {
          status: outcome.status,
        });
      case "non-json":
        return t("toolsSettings.connectors.catalogs.reportNonJson");
      default:
        return null;
    }
  };

  const importFromUrl = async (url: string, tier: "operator" | "community") => {
    setCatalogReport([]);
    if (!url) {
      setCatalogReport([t("toolsSettings.connectors.catalogs.needUrl")]);
      return;
    }
    setCatalogBusy(true);
    try {
      const existing = catalogs.find((entry) => entry.url === url);
      const outcome = await fetchCatalogDocument(
        url,
        existing ? { etag: existing.etag, lastModified: existing.lastModified } : {},
      );
      const failure = fetchFailureLine(outcome);
      if (failure || outcome.kind !== "fetched") {
        setCatalogReport([failure ?? ""]);
        return;
      }
      const parsed = validateCatalog(outcome.raw);
      if (!parsed.ok) {
        setCatalogReport([
          t("toolsSettings.connectors.catalogs.reportInvalid", { detail: parsed.error }),
        ]);
        return;
      }
      const change = existing ? compareDocuments(existing, parsed.document) : null;
      if (existing && change?.kind === "same") {
        setCatalogReport([
          t("toolsSettings.connectors.catalogs.reportUpToDate", { revision: existing.revision }),
        ]);
        return;
      }
      await catalogsApi.putCatalog(existing?.id ?? newCatalogId(), {
        ...parsed.document,
        tier,
        url,
        fetchedAt: new Date().toISOString(),
        etag: outcome.etag,
        lastModified: outcome.lastModified,
      });
      await reloadCatalogs();
      setCatalogReport([
        change === null
          ? t("toolsSettings.connectors.catalogs.reportImported", {
              name: parsed.document.name,
              count: parsed.document.presets.length,
              providers: parsed.document.providers.length,
            })
          : change.kind === "revision-bump"
            ? t("toolsSettings.connectors.catalogs.reportRevisionBump", {
                revision: change.to,
              })
            : change.kind === "updated"
              ? t("toolsSettings.connectors.catalogs.reportUpdated", {
                  from: change.from,
                  to: change.to,
                  count: change.changedPresets,
                })
              : t("toolsSettings.connectors.catalogs.reportImported", {
                  count: parsed.document.presets.length,
                }),
      ]);
    } catch (err) {
      setCatalogReport([apiDetail(err)]);
    } finally {
      setCatalogBusy(false);
    }
  };

  const importFromFile = (file: File) => {
    setCatalogReport([]);
    setCatalogBusy(true);
    const reader = new FileReader();
    reader.onload = () => {
      void (async () => {
        try {
          let raw: unknown;
          try {
            raw = JSON.parse(String(reader.result ?? ""));
          } catch {
            setCatalogReport([t("toolsSettings.connectors.catalogs.reportNonJson")]);
            return;
          }
          const parsed = validateCatalog(raw);
          if (!parsed.ok) {
            setCatalogReport([
              t("toolsSettings.connectors.catalogs.reportInvalid", { detail: parsed.error }),
            ]);
            return;
          }
          await catalogsApi.putCatalog(newCatalogId(), {
            ...parsed.document,
            tier: "user",
            url: null,
            fetchedAt: new Date().toISOString(),
            etag: null,
            lastModified: null,
          });
          await reloadCatalogs();
          setCatalogReport([
            t("toolsSettings.connectors.catalogs.reportImported", {
              name: parsed.document.name,
              count: parsed.document.presets.length,
              providers: parsed.document.providers.length,
            }),
          ]);
        } catch (err) {
          setCatalogReport([apiDetail(err)]);
        } finally {
          setCatalogBusy(false);
        }
      })();
    };
    reader.onerror = () => {
      setCatalogBusy(false);
      setCatalogReport([t("toolsSettings.connectors.catalogs.reportFetchFailed")]);
    };
    reader.readAsText(file);
  };

  const refreshCatalog = async (target: SourcesCatalog) => {
    if (!target.url) return;
    setCatalogReport([]);
    setCatalogBusy(true);
    try {
      const outcome = await fetchCatalogDocument(target.url, {
        etag: target.etag,
        lastModified: target.lastModified,
      });
      const failure = fetchFailureLine(outcome);
      if (failure || outcome.kind !== "fetched") {
        setCatalogReport([failure ?? ""]);
        return;
      }
      const parsed = validateCatalog(outcome.raw);
      if (!parsed.ok) {
        setCatalogReport([
          t("toolsSettings.connectors.catalogs.reportInvalid", { detail: parsed.error }),
        ]);
        return;
      }
      const change = compareDocuments(target, parsed.document);
      if (change.kind === "same") {
        setCatalogReport([
          t("toolsSettings.connectors.catalogs.reportUpToDate", { revision: target.revision }),
        ]);
        return;
      }
      await catalogsApi.putCatalog(target.id, {
        ...parsed.document,
        tier: target.tier,
        url: target.url,
        fetchedAt: new Date().toISOString(),
        etag: outcome.etag ?? target.etag,
        lastModified: outcome.lastModified ?? target.lastModified,
      });
      await reloadCatalogs();
      setCatalogReport([
        change.kind === "revision-bump"
          ? t("toolsSettings.connectors.catalogs.reportRevisionBump", { revision: change.to })
          : t("toolsSettings.connectors.catalogs.reportUpdated", {
              from: change.from,
              to: change.to,
              count: change.changedPresets,
            }),
      ]);
    } catch (err) {
      setCatalogReport([apiDetail(err)]);
    } finally {
      setCatalogBusy(false);
    }
  };

  const removeCatalog = async (target: SourcesCatalog) => {
    setCatalogBusy(true);
    try {
      await catalogsApi.deleteCatalog(target.id);
      setRemoveCatalogTarget(null);
      await reloadCatalogs();
    } catch (err) {
      setCatalogReport([apiDetail(err)]);
    } finally {
      setCatalogBusy(false);
    }
  };

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
  const countryLens = (source: PostingSource) => sourceCountryKey(source);
  const hasProblem = (source: PostingSource) => {
    if (sourceStatus(source) !== "ok") return true;
    if (source.paused_at) return true;
    const entry = catalogByKey[source.connector_key];
    if (entry?.capabilities?.requires_credentials !== true) return false;
    return Object.entries(source.secret_hints).some(
      ([slot, hint]) => entry.secret_fields.includes(slot) && !hint.set,
    );
  };
  const visibleSources = sources.filter(
    (source) =>
      !(countries && countries.size > 0 && !countries.has(countryLens(source))) &&
      !(problemsOnly && !hasProblem(source)) &&
      (!query ||
        [source.key, source.connector_key, source.title ?? "", source.error ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(query)),
  );
  const problemCount = useMemo(() => sources.filter(hasProblem).length, [sources, catalogByKey]);
  const countryLenses = useMemo(() => {
    const counts = new Map<string, number>();
    for (const source of sources) {
      const key = sourceCountryKey(source);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([key, count]) => ({ key, count }))
      .sort((a, b) => {
        if (a.key === "custom") return 1;
        if (b.key === "custom") return -1;
        if (a.key === WORLDWIDE_KEY) return 1;
        if (b.key === WORLDWIDE_KEY) return -1;
        return countryDisplayName(a.key, language).localeCompare(countryDisplayName(b.key, language));
      });
  }, [sources, language]);
  const lensLabel = (key: string) =>
    key === "custom"
      ? t("toolsSettings.connectors.sources.countryCustom")
      : key === WORLDWIDE_KEY
        ? t("toolsSettings.connectors.sources.worldwide")
        : countryDisplayName(key, language);
  const lensFlag = (key: string) => {
    if (key === "custom") return "⚙️";
    if (key === WORLDWIDE_KEY) return "🌍";
    return findCountry(key)?.flag ?? "";
  };
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
  const gallery = useMemo(() => mergeCatalogs(JOB_SOURCE_PRESETS, catalogs), [catalogs]);
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

        <div className="mt-3">
          <CatalogsBlock
            catalogs={catalogs}
            report={catalogReport}
            busy={catalogBusy}
            onImportUrl={(url, tier) => void importFromUrl(url, tier)}
            onImportFile={importFromFile}
            onRefresh={(target) => void refreshCatalog(target)}
            onRemove={setRemoveCatalogTarget}
          />
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
            <div
              className="flex flex-wrap items-center gap-1.5"
              role="group"
              aria-label={t("toolsSettings.connectors.sources.countryFilterAria")}
              data-testid="job-sources-country-filter"
            >
              <button
                type="button"
                aria-pressed={!countries || countries.size === 0}
                onClick={() => setCountries(null)}
                data-testid="job-sources-country-all"
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                  !countries || countries.size === 0
                    ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))] font-medium text-[var(--as-accent)]"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)] hover:border-[var(--as-accent)]"
                }`}
              >
                {t("toolsSettings.connectors.sources.countryAll")}
              </button>
              {countryLenses.map((lens) => {
                const active = countries?.has(lens.key) ?? false;
                return (
                  <button
                    key={lens.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setCountries((current) => {
                        const base = current ?? new Set<string>();
                        const next = new Set(base);
                        if (next.has(lens.key)) {
                          next.delete(lens.key);
                        } else {
                          next.add(lens.key);
                        }
                        return next.size > 0 ? next : null;
                      });
                    }}
                    data-testid={`job-sources-country-${lens.key}`}
                    className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                      active
                        ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))] font-medium text-[var(--as-accent)]"
                        : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-fg)] hover:border-[var(--as-accent)]"
                    }`}
                  >
                    {lensFlag(lens.key)} {lensLabel(lens.key)}
                    <span
                      className={active ? "ml-1 opacity-80" : "ml-1 text-[var(--as-muted-fg)]"}
                    >
                      {lens.count}
                    </span>
                  </button>
                );
              })}
              <button
                type="button"
                aria-pressed={problemsOnly}
                onClick={() => setProblemsOnly((value) => !value)}
                data-testid="job-sources-problems"
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                  problemsOnly
                    ? "border-[var(--as-danger)] bg-[color-mix(in_srgb,var(--as-danger)_8%,var(--as-surface))] font-medium text-[var(--as-danger)]"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)] hover:border-[var(--as-danger)]"
                }`}
              >
                ⚠ {t("toolsSettings.connectors.sources.problemsOnly")}
                {problemCount > 0 ? (
                  <span className="ml-1 opacity-80">{problemCount}</span>
                ) : null}
              </button>
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
                      provenance={gallery.provenance}
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

        <ConfirmationModal
          open={removeCatalogTarget !== null}
          onOpenChange={(open) => {
            if (!open) setRemoveCatalogTarget(null);
          }}
          title={t("toolsSettings.connectors.catalogs.removeTitle", {
            name: removeCatalogTarget?.name ?? "",
          })}
          description={t("toolsSettings.connectors.catalogs.removeBody")}
          confirmLabel={t("toolsSettings.connectors.catalogs.removeConfirm")}
          destructive
          busy={catalogBusy}
          onConfirm={() => {
            if (removeCatalogTarget) void removeCatalog(removeCatalogTarget);
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
        presets={gallery.presets}
        provenance={gallery.provenance}
        providers={gallery.providers}
        onAddPresets={addPresets}
        onCustom={(prefill) => {
          setPresetOpen(false);
          setDraft({
            id: null,
            key: "",
            connector_key: prefill?.connectorKey ?? "",
            config: prefill?.config ?? {},
            query_mode: "radar",
            query_batch_size: 2,
          });
        }}
      />
    </div>
  );
}
