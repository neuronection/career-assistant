import { useCallback, useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ConnectionTestStatus } from "@neuronection/assistant-ui";

import { Badge, ConnectionTestRow } from "@/components/ui";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { fetchStorageStatus, type StorageStatus } from "@/api/storage";
import { isDesktop } from "@/lib/desktop";

function checkedLabel(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** Read-only deployment storage facts (plan 55 P4b2).
 *
 * Object storage is instance configuration, not a user setting: there is no
 * credential field, no provider tile and no backend switcher. The card shows
 * what the process resolved plus a live, cached health row; changing the
 * backend is a verified migration, not a save. */
export function StorageStatusCard() {
  const { t } = useTranslation();
  const desktop = isDesktop();
  const [data, setData] = useState<StorageStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (refresh: boolean) => {
      if (refresh) setTesting(true);
      setError(null);
      try {
        setData(await fetchStorageStatus(refresh));
      } catch (cause) {
        setError(
          cause instanceof Error && cause.message
            ? cause.message
            : t("storageStatus.error"),
        );
      } finally {
        setLoading(false);
        setTesting(false);
      }
    },
    [t],
  );

  useEffect(() => {
    if (desktop) return;
    void load(false);
  }, [desktop, load]);

  if (desktop) return null;

  const connectionStatus: ConnectionTestStatus =
    loading || testing
      ? "testing"
      : error
        ? "fail"
        : data
          ? data.status === "ok"
            ? "ok"
            : "fail"
          : "idle";
  const target = data?.bucket ?? data?.container;
  const location =
    data === null
      ? null
      : data.backend === "local"
        ? t("storageStatus.localVolume")
        : [data.region, data.endpoint_host].filter(Boolean).join(" · ") ||
          t("storageStatus.providerDefault");
  const failureLabel =
    data?.status === "degraded"
      ? t("storageStatus.degraded")
      : t("storageStatus.unavailable");
  const checked = checkedLabel(data?.checked_at ?? null);

  return (
    <SettingsSectionCard
      name="storage"
      icon={HardDrive}
      adminOnly
      title={t("storageStatus.title")}
      description={t("storageStatus.description")}
      badges={
        data ? (
          <Badge variant="outline" className="font-mono">
            {data.backend}
          </Badge>
        ) : undefined
      }
      footer={
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t("storageStatus.readOnly")}
        </p>
      }
    >
      <div className="space-y-3">
        {loading ? (
          <p className="text-xs text-[var(--as-muted-fg)]" role="status">
            {t("storageStatus.loading")}
          </p>
        ) : null}
        {error ? (
          <p className="text-xs text-[var(--as-danger)]" role="alert">
            {error}
          </p>
        ) : null}
        {data ? (
          <>
            <dl className="divide-y divide-[var(--as-border)] rounded-md border border-[var(--as-border)] text-xs">
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.backend")}
                </dt>
                <dd className="font-mono">{data.backend}</dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.target")}
                </dt>
                <dd className="truncate font-mono">
                  {target ??
                    (data.backend === "local"
                      ? t("storageStatus.localVolume")
                      : t("storageStatus.none"))}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.prefix")}
                </dt>
                <dd className="truncate font-mono">
                  {data.prefix || t("storageStatus.none")}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.location")}
                </dt>
                <dd className="truncate text-right font-mono">{location}</dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.sse")}
                </dt>
                <dd className="font-mono">
                  {data.sse === "n/a"
                    ? t("storageStatus.notApplicable")
                    : data.sse}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.maxObject")}
                </dt>
                <dd className="font-mono">
                  {t("storageStatus.megabytes", {
                    value: data.max_object_mb,
                  })}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 px-3 py-2">
                <dt className="text-[var(--as-muted-fg)]">
                  {t("storageStatus.presignTtl")}
                </dt>
                <dd className="font-mono">
                  {t("storageStatus.seconds", {
                    value: data.presign_ttl_seconds,
                  })}
                </dd>
              </div>
            </dl>
            <ConnectionTestRow
              variant="inline"
              label={t("storageStatus.health")}
              status={connectionStatus}
              testLabel={t("storageStatus.test")}
              okLabel={t("storageStatus.healthy")}
              failLabel={failureLabel}
              idleLabel={t("storageStatus.notChecked")}
              errorMessage={data.detail}
              meta={
                checked
                  ? t("storageStatus.checkedAt", { time: checked })
                  : null
              }
              onTest={() => void load(true)}
              disabled={loading || testing}
            />
          </>
        ) : null}
      </div>
    </SettingsSectionCard>
  );
}
