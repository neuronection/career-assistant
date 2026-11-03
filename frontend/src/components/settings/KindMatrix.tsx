import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Lock, RotateCcw } from "lucide-react";

import { SwitchRow } from "@/components/ui/switch-row";
import { useOptimisticToggle } from "@/components/settings/useSettingsDraft";
import type { NotificationKindPref } from "@/types/wire";

const TOGGLEABLE = (channels: string[]) => channels.filter((c) => c !== "in_app");

/** The per-kind × per-channel routing matrix (plan 148): real table with
 * column headers, group rows, switches (instant optimistic saves with
 * rollback), `overridden` reset, locked always-on rows and a filter box.
 * The caller owns the API; every commit prop returns a promise the matrix
 * awaits per cell. Testids: `kind-{key}`, `kind-{key}-{channel}`,
 * `kind-{key}-reset`, `kind-matrix`, `kind-filter`. */
export function KindMatrix({
  channels,
  kinds,
  onSetChannels,
  onSetEnabled,
  onReset,
}: {
  channels: string[];
  kinds: NotificationKindPref[];
  onSetChannels: (kind: NotificationKindPref, channels: string[]) => Promise<void>;
  onSetEnabled: (kind: NotificationKindPref, enabled: boolean) => Promise<void>;
  onReset: (kind: NotificationKindPref) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState("");
  const columns = useMemo(() => TOGGLEABLE(channels), [channels]);

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const visible = needle
      ? kinds.filter(
          (kind) =>
            kind.label.toLowerCase().includes(needle) ||
            kind.group.toLowerCase().includes(needle)
        )
      : kinds;
    const ordered: { group: string; kinds: NotificationKindPref[] }[] = [];
    for (const kind of visible) {
      let bucket = ordered.find((entry) => entry.group === kind.group);
      if (!bucket) {
        bucket = { group: kind.group, kinds: [] };
        ordered.push(bucket);
      }
      bucket.kinds.push(kind);
    }
    return ordered;
  }, [kinds, filter]);

  const shown = groups.reduce((sum, entry) => sum + entry.kinds.length, 0);

  return (
    <div data-testid="kind-matrix">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <input
          className="w-full max-w-56 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2.5 py-1.5 text-sm text-[var(--as-fg)] placeholder:text-[var(--as-muted-fg)] focus:border-[var(--as-primary)] focus:outline-none sm:w-auto"
          placeholder={t("notifications.filterKinds")}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          data-testid="kind-filter"
        />
        <span className="text-xs text-[var(--as-muted-fg)]">
          {t("notifications.matrixSummary", { count: shown, groups: groups.length })}
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-[var(--as-border)]">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-[var(--as-border)] bg-[var(--as-muted)]">
              <th
                scope="col"
                className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
              >
                {t("notifications.kindColumn")}
              </th>
              {columns.map((channel) => (
                <th
                  key={channel}
                  scope="col"
                  className="w-20 px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
                >
                  {t(`notifications.channel.${channel}`)}
                </th>
              ))}
              <th
                scope="col"
                className="w-16 px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
              >
                {t("notifications.onColumn")}
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((bucket) => (
              <KindGroup
                key={bucket.group}
                group={bucket.group}
                kinds={bucket.kinds}
                columns={columns}
                onSetChannels={onSetChannels}
                onSetEnabled={onSetEnabled}
                onReset={onReset}
              />
            ))}
            {shown === 0 && (
              <tr>
                <td
                  colSpan={columns.length + 2}
                  className="px-3 py-4 text-center text-sm text-[var(--as-muted-fg)]"
                >
                  {t("notifications.noKindsMatch")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function KindGroup({
  group,
  kinds,
  columns,
  onSetChannels,
  onSetEnabled,
  onReset,
}: {
  group: string;
  kinds: NotificationKindPref[];
  columns: string[];
  onSetChannels: (kind: NotificationKindPref, channels: string[]) => Promise<void>;
  onSetEnabled: (kind: NotificationKindPref, enabled: boolean) => Promise<void>;
  onReset: (kind: NotificationKindPref) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <>
      <tr className="border-b border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-muted)_55%,var(--as-surface-raised))]">
        <td
          colSpan={columns.length + 2}
          className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wide text-[var(--as-muted-fg)]"
        >
          {t(`notifications.group.${group}`, { defaultValue: group })}
          {group === "system" ? ` · ${t("notifications.alwaysOn")}` : ""}
        </td>
      </tr>
      {kinds.map((kind) => (
        <KindRow
          key={kind.key}
          kind={kind}
          columns={columns}
          onSetChannels={onSetChannels}
          onSetEnabled={onSetEnabled}
          onReset={onReset}
        />
      ))}
    </>
  );
}

function KindRow({
  kind,
  columns,
  onSetChannels,
  onSetEnabled,
  onReset,
}: {
  kind: NotificationKindPref;
  columns: string[];
  onSetChannels: (kind: NotificationKindPref, channels: string[]) => Promise<void>;
  onSetEnabled: (kind: NotificationKindPref, enabled: boolean) => Promise<void>;
  onReset: (kind: NotificationKindPref) => Promise<void>;
}) {
  const { t } = useTranslation();
  const { toggle, valueOf } = useOptimisticToggle();
  const channelOn = (channel: string) =>
    valueOf(`${kind.key}:${channel}`, kind.channels.includes(channel));
  const setChannel = (channel: string, next: boolean) => {
    const rest = columns.filter((c) => c !== channel && channelOn(c));
    const nextChannels = ["in_app", ...rest, ...(next ? [channel] : [])];
    return toggle(`${kind.key}:${channel}`, next, () =>
      onSetChannels(kind, nextChannels)
    );
  };

  return (
    <tr
      className="border-b border-[var(--as-border)] last:border-b-0"
      data-testid={`kind-row-${kind.key}`}
      data-locked={kind.mutable ? undefined : "true"}
    >
      <td className="max-w-0 px-3 py-2">
        <span className="flex items-center gap-1.5 font-medium text-[var(--as-fg)]">
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--as-warning)]"
            data-severity={kind.severity}
            aria-hidden
          />
          <span className="truncate">{kind.label}</span>
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--as-muted-fg)]">
          {kind.mutable && kind.overridden ? (
            <>
              {t("notifications.custom")}
              <button
                type="button"
                className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[11px] font-medium text-[var(--as-primary)] underline decoration-transparent transition-colors hover:decoration-current focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-focus-ring)]"
                onClick={() => void onReset(kind)}
                data-testid={`kind-${kind.key}-reset`}
                aria-label={t("notifications.resetToDefault", { name: kind.label })}
              >
                <RotateCcw className="h-2.5 w-2.5" aria-hidden />
                {t("notifications.resetShort")}
              </button>
            </>
          ) : null}
          {kind.manage_url ? (
            <Link
              to={kind.manage_url}
              className="rounded px-1 py-0.5 text-[11px] font-medium text-[var(--as-primary)] underline decoration-transparent transition-colors hover:decoration-current focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-focus-ring)]"
              data-testid={`kind-${kind.key}-manage`}
            >
              {t("notifications.manage")} →
            </Link>
          ) : null}
        </span>
      </td>
      {columns.map((channel) => {
        const locked = !kind.mutable;
        return (
          <td key={channel} className="px-2 py-2 text-center">
            <span className="inline-flex justify-center">
              <SwitchRow
                label={t("notifications.routeChannel", { channel, name: kind.label })}
                checked={channelOn(channel)}
                disabled={locked}
                hideLabel
                onCheckedChange={(next) => void setChannel(channel, next)}
                className="w-auto border-none bg-transparent px-1 py-0 hover:bg-transparent data-[state=unchecked]:opacity-60"
                data-testid={`kind-${kind.key}-${channel}`}
              />
            </span>
          </td>
        );
      })}
      <td className="px-2 py-2 text-center">
        {kind.mutable ? (
          <span className="inline-flex justify-center">
            <SwitchRow
              label={t("notifications.enableKind", { name: kind.label })}
              checked={valueOf(`${kind.key}:on`, kind.enabled)}
              hideLabel
              onCheckedChange={(next) => void toggle(`${kind.key}:on`, next, () => onSetEnabled(kind, next))}
              className="w-auto border-none bg-transparent px-1 py-0 hover:bg-transparent data-[state=unchecked]:opacity-60"
              data-testid={`kind-${kind.key}`}
            />
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1 text-[var(--as-muted-fg)]"
            title={t("notifications.alwaysOn")}
          >
            <Lock className="h-3 w-3" aria-hidden />
            <span className="sr-only">{t("notifications.alwaysOn")}</span>
          </span>
        )}
      </td>
    </tr>
  );
}
