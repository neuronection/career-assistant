import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  FileArchive,
  GitBranch,
  Globe2,
  Layers,
  Library,
  ListChecks,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Badge,
  Button,
  ConfirmationModal,
  EmptyState,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  PanelModal,
  SearchInput,
  SegmentedTabs,
  Spinner,
} from "@/components/ui";
import { SwitchRow } from "@/components/ui/switch-row";
import { apiDetail } from "@/api/client";
import * as providersApi from "@/api/providers";
import type {
  AdminProvider,
  AdminProviderDetail,
  ProviderCreate,
  ProviderPlan,
  ProviderSyncRun,
  ProviderVersion,
} from "@/api/providers";

type BadgeVariant = "default" | "secondary" | "outline" | "warning" | "success" | "danger";

type Notice = { tone: "info" | "success" | "danger"; text: string } | null;

const KIND_ICON = {
  git: GitBranch,
  registry: Globe2,
  file: FileArchive,
  repository: Layers,
} as const;

const KIND_LABEL_KEY = {
  git: "toolsSettings.providers.kindGit",
  registry: "toolsSettings.providers.kindRegistry",
  file: "toolsSettings.providers.kindFile",
  repository: "toolsSettings.providers.kindRepository",
} as const;

const TRUST_LABEL_KEY = {
  official: "toolsSettings.providers.trustOfficial",
  operator: "toolsSettings.providers.trustOperator",
  community: "toolsSettings.providers.trustCommunity",
  local: "toolsSettings.providers.trustLocal",
} as const;

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  revoked: "outline",
  applied: "success",
  conflicted: "danger",
  failed: "danger",
  partial: "warning",
  ok: "success",
  noop: "secondary",
};

function when(value: string | null | undefined): string | null {
  if (!value) return null;
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortDigest(digest: string): string {
  return digest.replace(/^sha256:/, "").slice(0, 12);
}

function totalItemCount(counts: Record<string, number> | undefined): number {
  return Object.values(counts ?? {}).reduce((total, value) => total + (value ?? 0), 0);
}

function providerAccent(provider: AdminProvider): string {
  if (provider.last_error) return "var(--as-danger)";
  if ((provider.pending_count ?? 0) > 0) return "var(--as-warning)";
  if (provider.enabled && provider.current_version) return "var(--as-success)";
  return "var(--as-muted-fg)";
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "secondary"}>
      {t(`toolsSettings.providers.status.${status}`, { defaultValue: status })}
    </Badge>
  );
}

/** Plan 218: the provider hub — publishers, versions, the applied catalog.
 * Cards are the primary navigation; the detail panel is a segmented
 * workspace (Overview / Versions / Items / Endpoints / Runs). Every action
 * is explicit: sync and plan never write; apply needs an approved version. */
export function ProviderHub() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<AdminProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      setProviders(await providersApi.listAdminProviders());
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return providers;
    return providers.filter(
      (provider) =>
        provider.name.toLowerCase().includes(needle) ||
        provider.kind.toLowerCase().includes(needle) ||
        provider.trust_tier.toLowerCase().includes(needle),
    );
  }, [providers, query]);

  const pending = providers.reduce((total, provider) => total + provider.pending_count, 0);
  const items = providers.reduce(
    (total, provider) => total + totalItemCount(provider.item_counts),
    0,
  );

  return (
    <div className="space-y-3" data-testid="provider-hub">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("toolsSettings.providers.title")}
            </h3>
            <Badge variant="secondary" data-testid="provider-hub-count">
              {t("toolsSettings.providers.count", { count: providers.length })}
            </Badge>
            {pending > 0 ? (
              <Badge variant="warning" data-testid="provider-hub-pending">
                {t("toolsSettings.providers.updates", { count: pending })}
              </Badge>
            ) : null}
            {items > 0 ? (
              <Badge variant="outline">
                {t("toolsSettings.providers.items", { count: items })}
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 max-w-2xl text-xs text-[var(--as-muted-fg)]">
            {t("toolsSettings.providers.hint")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void load()}
            disabled={loading}
            data-testid="provider-hub-refresh"
          >
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            {t("toolsSettings.providers.refresh")}
          </Button>
          <Button size="sm" onClick={() => setAddOpen(true)} data-testid="provider-add">
            <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.providers.add")}
          </Button>
        </div>
      </div>

      {notice ? (
        <div
          className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
            notice.tone === "danger"
              ? "border-[color-mix(in_srgb,var(--as-danger)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-danger)_10%,var(--as-surface))] text-[var(--as-danger)]"
              : notice.tone === "success"
                ? "border-[color-mix(in_srgb,var(--as-success)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-success)_10%,var(--as-surface))] text-[var(--as-success)]"
                : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)]"
          }`}
          data-testid="provider-hub-notice"
        >
          {notice.tone === "danger" ? (
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          ) : (
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          )}
          <span className="min-w-0 flex-1">{notice.text}</span>
          <button
            type="button"
            className="shrink-0 text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            onClick={() => setNotice(null)}
            aria-label={t("common.dismiss")}
          >
            ×
          </button>
        </div>
      ) : null}

      {error ? (
        <div
          className="flex items-center justify-between gap-3 rounded-lg border border-[color-mix(in_srgb,var(--as-danger)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-danger)_8%,var(--as-surface))] px-3 py-2 text-xs text-[var(--as-danger)]"
          data-testid="provider-hub-error"
        >
          <span className="min-w-0 flex-1">{error}</span>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t("common.retry")}
          </Button>
        </div>
      ) : null}

      {providers.length > 4 ? (
        <div className="max-w-sm">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder={t("toolsSettings.providers.search")}
            ariaLabel={t("toolsSettings.providers.search")}
            clearLabel={t("common.clear")}
          />
        </div>
      ) : null}

      {loading && providers.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-10 text-xs text-[var(--as-muted-fg)]">
          <Spinner /> {t("toolsSettings.providers.loading")}
        </div>
      ) : visible.length === 0 ? (
        <EmptyState
          icon={Database}
          title={t("toolsSettings.providers.emptyTitle")}
          description={t("toolsSettings.providers.emptyBody")}
          action={
            <Button size="sm" onClick={() => setAddOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.providers.add")}
            </Button>
          }
        />
      ) : (
        <div
          className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3"
          data-testid="provider-hub-grid"
        >
          {visible.map((provider) => {
            const KindIcon = KIND_ICON[provider.kind as keyof typeof KIND_ICON] ?? Database;
            const version =
              provider.current_version?.pack_version ??
              provider.latest_version?.pack_version ??
              "—";
            const checked = when(provider.last_check_at);
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => setSelectedId(provider.id)}
                className="group flex h-full min-h-[136px] flex-col rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3.5 text-left transition hover:border-[var(--as-accent)] hover:bg-[var(--as-surface-raised)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
                data-testid={`provider-card-${provider.id}`}
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className="rounded-lg bg-[color-mix(in_srgb,var(--as-accent)_10%,var(--as-surface))] p-1.5 text-[var(--as-accent)]"
                    aria-hidden
                  >
                    <KindIcon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ background: providerAccent(provider) }}
                        aria-hidden
                      />
                      <p className="truncate text-sm font-semibold text-[var(--as-fg)]">
                        {provider.name}
                      </p>
                    </div>
                    <p className="mt-0.5 truncate text-[11px] text-[var(--as-muted-fg)]">
                      {t(KIND_LABEL_KEY[provider.kind as keyof typeof KIND_LABEL_KEY] ?? "toolsSettings.providers.kindFile")}
                      {" · "}
                      {t(TRUST_LABEL_KEY[provider.trust_tier as keyof typeof TRUST_LABEL_KEY] ?? "toolsSettings.providers.trustCommunity")}
                      {" · "}
                      {t("toolsSettings.providers.priority", { priority: provider.priority })}
                    </p>
                  </div>
                  {(provider.pending_count ?? 0) > 0 ? (
                    <Badge variant="warning" className="shrink-0">
                      {provider.pending_count ?? 0}
                    </Badge>
                  ) : null}
                </div>

                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  <Badge variant="secondary">
                    <Layers className="mr-1 h-3 w-3" /> {version}
                  </Badge>
                  <Badge variant="outline">
                    {t("toolsSettings.providers.itemCount", {
                      count: totalItemCount(provider.item_counts),
                    })}
                  </Badge>
                  <Badge variant={provider.enabled ? "success" : "secondary"}>
                    {provider.enabled
                      ? t("toolsSettings.providers.enabled")
                      : t("toolsSettings.providers.disabled")}
                  </Badge>
                </div>

                <div className="mt-auto flex items-center justify-between gap-2 pt-3 text-[11px] text-[var(--as-muted-fg)]">
                  <span className="truncate">
                    {checked
                      ? t("toolsSettings.providers.checked", { date: checked })
                      : t("toolsSettings.providers.neverChecked")}
                  </span>
                  <span className="flex shrink-0 items-center gap-0.5 font-medium text-[var(--as-accent)]">
                    {t("toolsSettings.providers.manage")}
                    <ArrowUpRight className="h-3 w-3" />
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {selectedId ? (
        <ProviderDetail
          providerId={selectedId}
          onClose={() => setSelectedId(null)}
          onChanged={() => void load()}
          onNotice={setNotice}
        />
      ) : null}
      <AddProviderDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={(message) => {
          setNotice({ tone: "success", text: message });
          void load();
        }}
        onError={(message) => setNotice({ tone: "danger", text: message })}
      />
    </div>
  );
}

function ProviderDetail({
  providerId,
  onClose,
  onChanged,
  onNotice,
}: {
  providerId: string;
  onClose: () => void;
  onChanged: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<AdminProviderDetail | null>(null);
  const [versions, setVersions] = useState<ProviderVersion[]>([]);
  const [runs, setRuns] = useState<ProviderSyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [plan, setPlan] = useState<ProviderPlan | null>(null);
  const [planFor, setPlanFor] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [probe, setProbe] = useState<Record<string, string>>({});
  const [deleteOpen, setDeleteOpen] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [nextDetail, nextVersions, nextRuns] = await Promise.all([
        providersApi.fetchAdminProvider(providerId),
        providersApi.listProviderVersions(providerId),
        providersApi.listProviderRuns(providerId, 30),
      ]);
      setDetail(nextDetail);
      setVersions(nextVersions);
      setRuns(nextRuns);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshAll = useCallback(async () => {
    await load();
    onChanged();
  }, [load, onChanged]);

  const run = async (key: string, action: () => Promise<unknown>, success: string) => {
    setBusy(key);
    setActionError("");
    try {
      await action();
      onNotice({ tone: "success", text: success });
      await refreshAll();
    } catch (err) {
      setActionError(apiDetail(err));
    } finally {
      setBusy(null);
    }
  };

  const tabs = useMemo(
    () => [
      { value: "overview", label: t("toolsSettings.providers.tabOverview"), icon: Activity },
      { value: "versions", label: t("toolsSettings.providers.tabVersions"), icon: ListChecks },
      { value: "items", label: t("toolsSettings.providers.tabItems"), icon: Database },
      { value: "catalog", label: t("toolsSettings.providers.tabCatalog"), icon: Library },
      { value: "endpoints", label: t("toolsSettings.providers.tabEndpoints"), icon: Globe2 },
      { value: "runs", label: t("toolsSettings.providers.tabRuns"), icon: Clock3 },
    ],
    [t],
  );

  const title = detail?.name ?? t("toolsSettings.providers.detailFallback");
  const KindIcon = detail
    ? KIND_ICON[detail.kind as keyof typeof KIND_ICON] ?? Database
    : Database;

  return (
    <>
      <PanelModal
        open
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
        size="xl"
        title={title}
        description={
          detail
            ? `${t(KIND_LABEL_KEY[detail.kind as keyof typeof KIND_LABEL_KEY] ?? "toolsSettings.providers.kindFile")} · ${t(TRUST_LABEL_KEY[detail.trust_tier as keyof typeof TRUST_LABEL_KEY] ?? "toolsSettings.providers.trustCommunity")}`
            : undefined
        }
        headerIcon={<KindIcon className="h-4 w-4" />}
        headerActions={
          detail ? (
            <Button
              size="sm"
              variant="secondary"
              loading={busy === "sync"}
              onClick={() =>
                void run(
                  "sync",
                  () => providersApi.syncProvider(providerId),
                  t("toolsSettings.providers.syncDone"),
                )
              }
              data-testid="provider-sync"
            >
              <RefreshCw className="h-3.5 w-3.5" /> {t("toolsSettings.providers.syncNow")}
            </Button>
          ) : undefined
        }
        bodyClassName="min-h-0 overflow-y-auto p-5 sm:p-6"
      >
        <div data-testid="provider-detail">
          {loading && !detail ? (
            <div className="flex items-center justify-center gap-2 py-16 text-xs text-[var(--as-muted-fg)]">
              <Spinner /> {t("toolsSettings.providers.loading")}
            </div>
          ) : error ? (
            <div className="space-y-3">
              <p className="text-sm text-[var(--as-danger)]">{error}</p>
              <Button size="sm" variant="secondary" onClick={() => void load()}>
                {t("common.retry")}
              </Button>
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <SegmentedTabs
                items={tabs}
                value={tab}
                onValueChange={setTab}
                ariaLabel={t("toolsSettings.providers.detailTabs")}
                wrap
              />

              {actionError ? (
                <p
                  className="rounded-lg border border-[color-mix(in_srgb,var(--as-danger)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-danger)_8%,var(--as-surface))] px-3 py-2 text-xs text-[var(--as-danger)]"
                  data-testid="provider-action-error"
                >
                  {actionError}
                </p>
              ) : null}

              {tab === "overview" ? (
                <OverviewTab
                  detail={detail}
                  busy={busy}
                  onDelete={() => setDeleteOpen(true)}
                />
              ) : null}
              {tab === "versions" ? (
                <VersionsTab
                  detail={detail}
                  versions={versions}
                  busy={busy}
                  plan={plan}
                  planFor={planFor}
                  onPlan={async (versionId) => {
                    setBusy(`plan-${versionId}`);
                    setActionError("");
                    try {
                      const next = await providersApi.planProviderVersion(
                        providerId,
                        versionId,
                      );
                      setPlan(next);
                      setPlanFor(versionId);
                    } catch (err) {
                      setActionError(apiDetail(err));
                    } finally {
                      setBusy(null);
                    }
                  }}
                  onApprove={(versionId) =>
                    void run(
                      `approve-${versionId}`,
                      () => providersApi.approveProviderVersion(providerId, versionId),
                      t("toolsSettings.providers.approved"),
                    )
                  }
                  onApply={(versionId) =>
                    void run(
                      `apply-${versionId}`,
                      () => providersApi.applyProviderVersion(providerId, versionId),
                      t("toolsSettings.providers.applied"),
                    )
                  }
                  onRevoke={(versionId) =>
                    void run(
                      `revoke-${versionId}`,
                      () => providersApi.revokeProviderVersion(providerId, versionId),
                      t("toolsSettings.providers.revoked"),
                    )
                  }
                  onReject={(versionId) => {
                    setRejectFor(versionId);
                    setRejectReason("");
                  }}
                />
              ) : null}
              {tab === "items" ? (
                <ItemsTab
                  detail={detail}
                  busy={busy}
                  onToggle={(seedKey, enabled) =>
                    void run(
                      `item-${seedKey}`,
                      () => providersApi.setProviderItemEnabled(providerId, seedKey, enabled),
                      t("toolsSettings.providers.itemUpdated"),
                    )
                  }
                  onRetire={(seedKey) =>
                    void run(
                      `retire-${seedKey}`,
                      () => providersApi.retireProviderItem(providerId, seedKey),
                      t("toolsSettings.providers.itemRetired"),
                    )
                  }
                />
              ) : null}
              {tab === "catalog" ? <CatalogTab detail={detail} /> : null}
              {tab === "endpoints" ? (
                <EndpointsTab
                  detail={detail}
                  busy={busy}
                  probe={probe}
                  onProbe={async (seedKey) => {
                    setBusy(`probe-${seedKey}`);
                    setProbe((current) => ({ ...current, [seedKey]: "" }));
                    try {
                      const result = await providersApi.probeProviderEndpoint(
                        providerId,
                        seedKey,
                      );
                      setProbe((current) => ({
                        ...current,
                        [seedKey]: t("toolsSettings.providers.probeResult", {
                          status: result.status,
                          ms: result.elapsed_ms,
                        }),
                      }));
                    } catch (err) {
                      setProbe((current) => ({
                        ...current,
                        [seedKey]: apiDetail(err),
                      }));
                    } finally {
                      setBusy(null);
                    }
                  }}
                />
              ) : null}
              {tab === "runs" ? <RunsTab runs={runs} /> : null}
            </div>
          ) : null}
        </div>
      </PanelModal>

      <Modal open={rejectFor !== null} onOpenChange={(open) => !open && setRejectFor(null)}>
        <ModalContent size="sm" aria-describedby={undefined}>
          <ModalHeader>
            <ModalTitle>{t("toolsSettings.providers.rejectTitle")}</ModalTitle>
          </ModalHeader>
          <div className="space-y-2">
            <label className="text-xs font-medium text-[var(--as-muted-fg)]" htmlFor="provider-reject-reason">
              {t("toolsSettings.providers.rejectReason")}
            </label>
            <textarea
              id="provider-reject-reason"
              className="min-h-20 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
            />
          </div>
          <ModalFooter>
            <Button variant="secondary" onClick={() => setRejectFor(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={!rejectReason.trim() || busy !== null}
              onClick={() => {
                const versionId = rejectFor;
                if (!versionId) return;
                setRejectFor(null);
                void run(
                  `reject-${versionId}`,
                  () =>
                    providersApi.rejectProviderVersion(
                      providerId,
                      versionId,
                      rejectReason.trim(),
                    ),
                  t("toolsSettings.providers.rejected"),
                );
              }}
            >
              {t("toolsSettings.providers.reject")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <ConfirmationModal
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("toolsSettings.providers.deleteTitle", { name: title })}
        description={t("toolsSettings.providers.deleteBody")}
        confirmLabel={t("toolsSettings.providers.deleteConfirm")}
        destructive
        busy={busy === "delete"}
        onConfirm={() => {
          setDeleteOpen(false);
          void run(
            "delete",
            () => providersApi.deleteProvider(providerId),
            t("toolsSettings.providers.deleted"),
          ).then(onClose);
        }}
      />
    </>
  );
}

function OverviewTab({
  detail,
  busy,
  onDelete,
}: {
  detail: AdminProviderDetail;
  busy: string | null;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const rows = [
    [t("toolsSettings.providers.fieldKind"), t(KIND_LABEL_KEY[detail.kind as keyof typeof KIND_LABEL_KEY] ?? "toolsSettings.providers.kindFile")],
    [t("toolsSettings.providers.fieldTrust"), t(TRUST_LABEL_KEY[detail.trust_tier as keyof typeof TRUST_LABEL_KEY] ?? "toolsSettings.providers.trustCommunity")],
    [t("toolsSettings.providers.fieldPriority"), String(detail.priority)],
    [
      t("toolsSettings.providers.fieldRefresh"),
      detail.refresh_minutes > 0
        ? t("toolsSettings.providers.everyMinutes", { count: detail.refresh_minutes })
        : t("toolsSettings.providers.manualRefresh"),
    ],
    [t("toolsSettings.providers.fieldUri"), detail.uri || "—"],
    [t("toolsSettings.providers.fieldRef"), detail.ref || "—"],
    [t("toolsSettings.providers.fieldSubpath"), detail.subpath || "—"],
    [
      t("toolsSettings.providers.fieldChecked"),
      when(detail.last_check_at) ?? t("toolsSettings.providers.neverChecked"),
    ],
  ];
  return (
    <div className="space-y-4" data-testid="provider-overview">
      {detail.last_error ? (
        <div className="flex items-start gap-2 rounded-lg border border-[color-mix(in_srgb,var(--as-warning)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-warning)_10%,var(--as-surface))] px-3 py-2 text-xs text-[var(--as-fg)]">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--as-warning)]" />
          <span className="min-w-0 flex-1 break-words">{detail.last_error}</span>
        </div>
      ) : null}
      <div className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
        <div className="flex flex-wrap items-center gap-2">
          {detail.current_version ? (
            <>
              <StatusBadge status={detail.current_version.status} />
              <Badge variant="secondary">
                {t("toolsSettings.providers.appliedVersion", {
                  version: detail.current_version.pack_version,
                })}
              </Badge>
              <code className="text-[11px] text-[var(--as-muted-fg)]">
                {shortDigest(detail.current_version.digest)}
              </code>
            </>
          ) : (
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("toolsSettings.providers.notApplied")}
            </span>
          )}
          {detail.latest_version &&
          detail.latest_version.id !== detail.current_version?.id ? (
            <Badge variant="outline">
              {t("toolsSettings.providers.latestVersion", {
                version: detail.latest_version.pack_version,
              })}
            </Badge>
          ) : null}
          {(detail.pending_count ?? 0) > 0 ? (
            <Badge variant="warning">
              {t("toolsSettings.providers.pendingVersions", {
                count: detail.pending_count ?? 0,
              })}
            </Badge>
          ) : null}
        </div>
        <dl className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          {rows.map(([label, value]) => (
            <div key={label} className="flex min-w-0 items-baseline gap-2">
              <dt className="w-28 shrink-0 text-[var(--as-muted-fg)]">{label}</dt>
              <dd className="min-w-0 break-words text-[var(--as-fg)]">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-[var(--as-fg)]">
            {t("toolsSettings.providers.dangerTitle")}
          </p>
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("toolsSettings.providers.dangerBody")}
          </p>
        </div>
        <Button
          size="sm"
          variant="destructive"
          disabled={busy !== null}
          onClick={onDelete}
          data-testid="provider-delete"
        >
          <Trash2 className="h-3.5 w-3.5" /> {t("toolsSettings.providers.delete")}
        </Button>
      </div>
      <p className="text-[11px] text-[var(--as-muted-fg)]">
        {t("toolsSettings.providers.policyNote", {
          count: totalItemCount(detail.item_counts),
        })}
      </p>
    </div>
  );
}

function VersionsTab({
  detail,
  versions,
  busy,
  plan,
  planFor,
  onPlan,
  onApprove,
  onApply,
  onRevoke,
  onReject,
}: {
  detail: AdminProviderDetail;
  versions: ProviderVersion[];
  busy: string | null;
  plan: ProviderPlan | null;
  planFor: string | null;
  onPlan: (versionId: string) => Promise<void>;
  onApprove: (versionId: string) => void;
  onApply: (versionId: string) => void;
  onRevoke: (versionId: string) => void;
  onReject: (versionId: string) => void;
}) {
  const { t } = useTranslation();
  if (versions.length === 0) {
    return (
      <EmptyState
        icon={Layers}
        title={t("toolsSettings.providers.noVersions")}
        description={t("toolsSettings.providers.noVersionsBody")}
      />
    );
  }
  return (
    <div className="space-y-2.5" data-testid="provider-versions">
      {versions.map((version) => {
        const applied = detail.current_version?.id === version.id;
        return (
          <div
            key={version.id}
            className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3.5"
            data-testid={`provider-version-${version.id}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="text-sm font-semibold text-[var(--as-fg)]">
                    {t("toolsSettings.providers.version", {
                      version: version.pack_version,
                    })}
                  </p>
                  <StatusBadge status={version.status} />
                  {applied ? (
                    <Badge variant="success">
                      {t("toolsSettings.providers.current")}
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-0.5 text-[11px] text-[var(--as-muted-fg)]">
                  {when(version.created_at) ?? "—"} ·{" "}
                  <code>{shortDigest(version.digest)}</code>
                  {version.commit_sha ? ` · ${version.commit_sha.slice(0, 8)}` : ""}
                </p>
                {version.reason ? (
                  <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
                    {version.reason}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === `plan-${version.id}`}
                  onClick={() => void onPlan(version.id)}
                  data-testid={`provider-plan-${version.id}`}
                >
                  {t("toolsSettings.providers.plan")}
                </Button>
                {version.status === "pending" ? (
                  <>
                    <Button
                      size="sm"
                      loading={busy === `approve-${version.id}`}
                      onClick={() => onApprove(version.id)}
                      data-testid={`provider-approve-${version.id}`}
                    >
                      <ShieldCheck className="h-3.5 w-3.5" />{" "}
                      {t("toolsSettings.providers.approve")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => onReject(version.id)}
                      data-testid={`provider-reject-${version.id}`}
                    >
                      {t("toolsSettings.providers.reject")}
                    </Button>
                  </>
                ) : null}
                {version.status === "approved" ? (
                  <>
                    <Button
                      size="sm"
                      loading={busy === `apply-${version.id}`}
                      disabled={applied}
                      onClick={() => onApply(version.id)}
                      data-testid={`provider-apply-${version.id}`}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />{" "}
                      {t("toolsSettings.providers.apply")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={busy === `revoke-${version.id}`}
                      onClick={() => onRevoke(version.id)}
                      data-testid={`provider-revoke-${version.id}`}
                    >
                      {t("toolsSettings.providers.revoke")}
                    </Button>
                  </>
                ) : null}
              </div>
            </div>
            {plan && planFor === version.id ? <PlanPreview plan={plan} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function PlanPreview({ plan }: { plan: ProviderPlan }) {
  const { t } = useTranslation();
  const actionVariant: Record<string, BadgeVariant> = {
    create: "success",
    update: "warning",
    retire: "danger",
    conflict: "danger",
    noop: "secondary",
    skip: "outline",
    override: "warning",
    delete: "danger",
  };
  return (
    <div
      className="mt-3 rounded-lg border border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-muted)_45%,transparent)] p-3"
      data-testid="provider-plan-preview"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
          {t("toolsSettings.providers.planPreview")}
        </p>
        <StatusBadge status={plan.status} />
        {Object.entries(plan.counts ?? {})
          .filter(([, count]) => count > 0)
          .map(([action, count]) => (
            <Badge key={action} variant={actionVariant[action] ?? "secondary"}>
              {t(`toolsSettings.providers.action.${action}`, {
                defaultValue: action,
              })}{" "}
              {count}
            </Badge>
          ))}
      </div>
      {(plan.conflicts ?? []).length > 0 ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-[var(--as-danger)]">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("toolsSettings.providers.planConflictHint", {
            count: (plan.conflicts ?? []).length,
          })}
        </p>
      ) : null}
      {(plan.warnings ?? []).length > 0 ? (
        <div className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="provider-plan-warnings">
          <p className="font-medium">
            {t("toolsSettings.providers.planWarnings", {
              count: (plan.warnings ?? []).length,
            })}
          </p>
          <ul className="mt-1 space-y-0.5">
            {(plan.warnings ?? []).slice(0, 8).map((warning, index) => (
              <li key={`${String(warning.code)}-${index}`}>
                {String(warning.code ?? "")}
                {warning.detail ? `: ${String(warning.detail)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-[11px]">
        {(plan.items ?? []).slice(0, 40).map((item) => (
          <li
            key={`${item.action}-${item.seed_key}`}
            className="flex items-center gap-2"
          >
            <Badge variant={actionVariant[item.action] ?? "secondary"}>
              {t(`toolsSettings.providers.action.${item.action}`, {
                defaultValue: item.action,
              })}
            </Badge>
            <code className="min-w-0 flex-1 truncate text-[var(--as-fg)]">
              {item.seed_key}
            </code>
            <span className="shrink-0 text-[var(--as-muted-fg)]">{item.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ItemsTab({
  detail,
  busy,
  onToggle,
  onRetire,
}: {
  detail: AdminProviderDetail;
  busy: string | null;
  onToggle: (seedKey: string, enabled: boolean) => void;
  onRetire: (seedKey: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3" data-testid="provider-items">
      <div>
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("toolsSettings.providers.presets")}
          </h4>
          <Badge variant="secondary">{(detail.presets ?? []).length}</Badge>
        </div>
        {(detail.presets ?? []).length === 0 ? (
          <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
            {t("toolsSettings.providers.noPresets")}
          </p>
        ) : (
          <div className="mt-2 space-y-1.5">
            {(detail.presets ?? []).map((preset) => (
              <div
                key={preset.seed_key}
                className={`flex flex-wrap items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 ${
                  preset.state === "retired" ? "opacity-60" : ""
                }`}
                data-testid={`provider-preset-${preset.seed_key}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <p className="truncate text-xs font-medium text-[var(--as-fg)]">
                      {preset.name}
                    </p>
                    <Badge variant="outline">{preset.category}</Badge>
                    {preset.country ? (
                      <Badge variant="secondary">{preset.country}</Badge>
                    ) : null}
                    {preset.state === "retired" ? (
                      <Badge variant="danger">
                        {t("toolsSettings.providers.retired")}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="truncate text-[11px] text-[var(--as-muted-fg)]">
                    {preset.connector_key} · <code>{preset.seed_key}</code>
                  </p>
                </div>
                <div className="shrink-0">
                  <SwitchRow
                    label={t("toolsSettings.providers.enabled")}
                    hideLabel
                    checked={preset.enabled}
                    disabled={busy !== null || preset.state === "retired"}
                    onCheckedChange={(checked) => onToggle(preset.seed_key, checked)}
                  />
                </div>
                {preset.state === "active" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy !== null}
                    onClick={() => onRetire(preset.seed_key)}
                    data-testid={`provider-retire-${preset.seed_key}`}
                  >
                    {t("toolsSettings.providers.retire")}
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const CATALOG_ENTITY_KEY: Record<string, string> = {
  job_family: "families",
  job_type: "jobs",
  job_relation: "relations",
  career_path: "paths",
  skill: "skills",
  interest_tag: "interests",
};

function CatalogTab({ detail }: { detail: AdminProviderDetail }) {
  const { t } = useTranslation();
  const groups = detail.catalog ?? [];
  const total = groups.reduce(
    (sum, group) => sum + (group.active ?? 0) + (group.retired ?? 0),
    0,
  );
  if (groups.length === 0 || total === 0) {
    return (
      <EmptyState
        icon={Library}
        title={t("toolsSettings.providers.noCatalog")}
        description={t("toolsSettings.providers.noCatalogBody")}
      />
    );
  }
  return (
    <div className="space-y-3" data-testid="provider-catalog">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
          {t("toolsSettings.providers.catalogTitle")}
        </h4>
        <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
          {t("toolsSettings.providers.catalogHint")}
        </p>
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {groups.map((group) => {
          const key = CATALOG_ENTITY_KEY[group.entity_type] ?? group.entity_type;
          return (
            <div
              key={group.entity_type}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2"
              data-testid={`provider-catalog-${group.entity_type}`}
            >
              <p className="min-w-0 truncate text-xs font-medium text-[var(--as-fg)]">
                {t(`toolsSettings.providers.catalogEntity.${key}`, {
                  defaultValue: key,
                })}
              </p>
              <div className="flex shrink-0 items-center gap-1.5">
                <Badge variant="secondary">
                  {t("toolsSettings.providers.catalogActive", {
                    count: group.active ?? 0,
                  })}
                </Badge>
                {(group.retired ?? 0) > 0 ? (
                  <Badge variant="danger">
                    {t("toolsSettings.providers.retired")} {group.retired}
                  </Badge>
                ) : null}
                {(group.user_modified ?? 0) > 0 ? (
                  <Badge variant="warning">
                    {t("toolsSettings.providers.catalogEdited", {
                      count: group.user_modified,
                    })}
                  </Badge>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EndpointsTab({
  detail,
  busy,
  probe,
  onProbe,
}: {
  detail: AdminProviderDetail;
  busy: string | null;
  probe: Record<string, string>;
  onProbe: (seedKey: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  if ((detail.endpoints ?? []).length === 0) {
    return (
      <EmptyState
        icon={Globe2}
        title={t("toolsSettings.providers.noEndpoints")}
        description={t("toolsSettings.providers.noEndpointsBody")}
      />
    );
  }
  return (
    <div className="space-y-1.5" data-testid="provider-endpoints">
      {(detail.endpoints ?? []).map((endpoint) => (
        <div
          key={endpoint.seed_key}
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
          data-testid={`provider-endpoint-${endpoint.seed_key}`}
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <p className="text-xs font-medium text-[var(--as-fg)]">
                  {endpoint.label}
                </p>
                <Badge variant="outline">{endpoint.method}</Badge>
                <Badge variant="secondary">{endpoint.auth}</Badge>
                {endpoint.worldwide ? (
                  <Badge variant="secondary">{t("toolsSettings.providers.worldwideShort")}</Badge>
                ) : (
                  (endpoint.countries ?? []).map((country) => (
                    <Badge key={country} variant="secondary">
                      {country}
                    </Badge>
                  ))
                )}
              </div>
              <p className="mt-1 break-all text-[11px] text-[var(--as-muted-fg)]">
                <code>
                  {endpoint.server}
                  {endpoint.path}
                </code>
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {endpoint.docs_url ? (
                <Button size="sm" variant="ghost" asChild>
                  <a href={endpoint.docs_url} target="_blank" rel="noreferrer">
                    {t("toolsSettings.providers.docs")}
                  </a>
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="secondary"
                loading={busy === `probe-${endpoint.seed_key}`}
                onClick={() => void onProbe(endpoint.seed_key)}
                data-testid={`provider-probe-${endpoint.seed_key}`}
              >
                <Activity className="h-3.5 w-3.5" /> {t("toolsSettings.providers.probe")}
              </Button>
            </div>
          </div>
          {probe[endpoint.seed_key] ? (
            <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
              {probe[endpoint.seed_key]}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function RunsTab({ runs }: { runs: ProviderSyncRun[] }) {
  const { t } = useTranslation();
  if (runs.length === 0) {
    return (
      <EmptyState
        icon={Clock3}
        title={t("toolsSettings.providers.noRuns")}
        description={t("toolsSettings.providers.noRunsBody")}
      />
    );
  }
  return (
    <div className="space-y-1.5" data-testid="provider-runs">
      {runs.map((run) => (
        <div
          key={run.id}
          className="flex flex-wrap items-start gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2"
        >
          <StatusBadge status={run.status} />
          <span className="text-[11px] text-[var(--as-muted-fg)]">
            {run.trigger} · {when(run.started_at) ?? "—"}
            {run.http_status ? ` · ${t("toolsSettings.providers.httpStatus", { status: run.http_status })}` : ""}
            {run.bytes ? ` · ${run.bytes} B` : ""}
          </span>
          {run.error ? (
            <span className="min-w-0 flex-1 break-words text-[11px] text-[var(--as-danger)]">
              {run.error}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function AddProviderDialog({
  open,
  onOpenChange,
  onCreated,
  onError,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (message: string) => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<"git" | "registry" | "file" | "repository">("git");
  const [name, setName] = useState("");
  const [uri, setUri] = useState("");
  const [ref, setRef] = useState("");
  const [subpath, setSubpath] = useState("");
  const [priority, setPriority] = useState("100");
  const [trust, setTrust] = useState<ProviderCreate["trust_tier"]>("community");
  const [refresh, setRefresh] = useState("360");
  const [enabled, setEnabled] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setKind("git");
    setName("");
    setUri("");
    setRef("");
    setSubpath("");
    setPriority("100");
    setTrust("community");
    setRefresh("360");
    setEnabled(false);
    setFile(null);
    setError("");
  };

  const submit = async () => {
    setError("");
    if (kind !== "repository" && !name.trim()) {
      setError(t("toolsSettings.providers.nameRequired"));
      return;
    }
    if (kind !== "file" && !uri.trim()) {
      setError(t("toolsSettings.providers.uriRequired"));
      return;
    }
    if ((kind === "git" || kind === "repository") && !ref.trim()) {
      setError(t("toolsSettings.providers.refRequired"));
      return;
    }
    if (kind === "file" && !file) {
      setError(t("toolsSettings.providers.fileRequired"));
      return;
    }
    setBusy(true);
    try {
      if (kind === "repository") {
        const result = await providersApi.importProviderRepository({
          kind: "git",
          uri: uri.trim(),
          ref: ref.trim(),
          priority: Number(priority) || 0,
          trust_tier: trust,
          refresh_minutes: Number(refresh) || 0,
          enabled,
        });
        const packs = result.packs ?? [];
        const added = packs.filter((pack) => pack.created).length;
        onCreated(
          t("toolsSettings.providers.imported", {
            added,
            total: packs.length,
            publisher: result.publisher?.name || uri.trim(),
          }),
        );
        reset();
        onOpenChange(false);
        return;
      }
      const payload: ProviderCreate = {
        kind,
        name: name.trim(),
        uri: kind === "file" ? "" : uri.trim(),
        ref: kind === "git" ? ref.trim() : "",
        subpath: subpath.trim(),
        priority: Number(priority) || 0,
        trust_tier: trust,
        refresh_minutes: Number(refresh) || 0,
        enabled,
      };
      const created = await providersApi.createProvider(payload);
      if (kind === "file" && file) {
        const report = await providersApi.uploadProviderPack(created.id, file);
        if (report.status === "failed") {
          onError(
            t("toolsSettings.providers.uploadFailed", {
              detail: report.message || report.code || "",
            }),
          );
        } else {
          onCreated(t("toolsSettings.providers.createdUploaded", { name: payload.name }));
        }
      } else {
        onCreated(t("toolsSettings.providers.created", { name: payload.name }));
      }
      reset();
      onOpenChange(false);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelModal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      size="md"
      title={t("toolsSettings.providers.addTitle")}
      description={t("toolsSettings.providers.addHint")}
      headerIcon={<Plus className="h-4 w-4" />}
      bodyClassName="min-h-0 overflow-y-auto p-5 sm:p-6"
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => {
              reset();
              onOpenChange(false);
            }}
          >
            {t("common.cancel")}
          </Button>
          <Button loading={busy} onClick={() => void submit()} data-testid="provider-create">
            {kind === "repository"
              ? t("toolsSettings.providers.importAction")
              : t("toolsSettings.providers.create")}
          </Button>
        </>
      }
    >
      <div className="space-y-4" data-testid="provider-add-dialog">
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["git", GitBranch, "gitHint"],
              ["repository", Layers, "repositoryHint"],
              ["registry", Globe2, "registryHint"],
              ["file", Upload, "fileHint"],
            ] as const
          ).map(([value, Icon, hint]) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => setKind(value)}
              className={`rounded-xl border p-3 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                kind === value
                  ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))]"
                  : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
              }`}
              data-testid={`provider-kind-${value}`}
            >
              <Icon className="h-4 w-4 text-[var(--as-accent)]" />
              <p className="mt-2 text-xs font-semibold text-[var(--as-fg)]">
                {t(KIND_LABEL_KEY[value])}
              </p>
              <p className="mt-0.5 text-[11px] text-[var(--as-muted-fg)]">
                {t(`toolsSettings.providers.${hint}`)}
              </p>
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {kind !== "repository" ? (
            <Field label={t("toolsSettings.providers.name")} className="sm:col-span-2">
              <input
                className={INPUT}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("toolsSettings.providers.namePlaceholder")}
                data-testid="provider-name"
              />
            </Field>
          ) : null}
          {kind !== "file" ? (
            <Field label={t("toolsSettings.providers.uri")} className="sm:col-span-2">
              <input
                className={INPUT}
                value={uri}
                onChange={(event) => setUri(event.target.value)}
                placeholder={
                  kind === "registry"
                    ? "https://example.com/api/v1/career/"
                    : "https://github.com/org/repo.git"
                }
                data-testid="provider-uri"
              />
            </Field>
          ) : null}
          {kind === "git" || kind === "repository" ? (
            <Field label={t("toolsSettings.providers.ref")}>
              <input
                className={INPUT}
                value={ref}
                onChange={(event) => setRef(event.target.value)}
                placeholder="v2026.11.25.2"
                data-testid="provider-ref"
              />
            </Field>
          ) : null}
          {kind !== "file" && kind !== "repository" ? (
            <Field label={t("toolsSettings.providers.subpath")}>
              <input
                className={INPUT}
                value={subpath}
                onChange={(event) => setSubpath(event.target.value)}
                placeholder={t("toolsSettings.providers.subpathPlaceholder")}
                data-testid="provider-subpath"
              />
            </Field>
          ) : null}
          <Field label={t("toolsSettings.providers.priorityLabel")}>
            <input
              type="number"
              min={0}
              max={999}
              className={INPUT}
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            />
          </Field>
          <Field label={t("toolsSettings.providers.refreshMinutes")}>
            <input
              type="number"
              min={0}
              max={10080}
              className={INPUT}
              value={refresh}
              onChange={(event) => setRefresh(event.target.value)}
            />
          </Field>
          <Field label={t("toolsSettings.providers.trust")}>
            <select
              className={INPUT}
              value={trust}
              onChange={(event) =>
                setTrust(event.target.value as ProviderCreate["trust_tier"])
              }
            >
              <option value="official">{t("toolsSettings.providers.trustOfficial")}</option>
              <option value="operator">{t("toolsSettings.providers.trustOperator")}</option>
              <option value="community">{t("toolsSettings.providers.trustCommunity")}</option>
              <option value="local">{t("toolsSettings.providers.trustLocal")}</option>
            </select>
          </Field>
          <div className="flex items-end">
            <SwitchRow
              label={t("toolsSettings.providers.enabled")}
              currentValue={t("toolsSettings.providers.enabledHint")}
              checked={enabled}
              onCheckedChange={setEnabled}
            />
          </div>
        </div>

        {kind === "file" ? (
          <div className="rounded-lg border border-dashed border-[var(--as-border)] bg-[var(--as-surface)] p-3">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-[var(--as-fg)]">
              <Upload className="h-4 w-4 text-[var(--as-accent)]" />
              <span>{file ? file.name : t("toolsSettings.providers.choosePack")}</span>
              <input
                type="file"
                accept=".zip,application/zip"
                className="sr-only"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                data-testid="provider-file"
              />
            </label>
            <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
              {t("toolsSettings.providers.fileHint")}
            </p>
          </div>
        ) : null}

        {error ? (
          <p className="text-xs text-[var(--as-danger)]" data-testid="provider-add-error">
            {error}
          </p>
        ) : null}
        <p className="text-[11px] text-[var(--as-muted-fg)]">
          {t("toolsSettings.providers.addNote")}
        </p>
      </div>
    </PanelModal>
  );
}

const INPUT =
  "w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] placeholder:text-[var(--as-muted-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]";

function Field({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={`block space-y-1 ${className ?? ""}`}>
      <span className="text-[11px] font-medium text-[var(--as-muted-fg)]">{label}</span>
      {children}
    </label>
  );
}
