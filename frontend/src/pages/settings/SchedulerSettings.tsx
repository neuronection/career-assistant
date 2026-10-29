import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { CalendarClock, Play, Zap } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { Badge, Button } from "@/components/ui";
import { SwitchRow } from "@/components/ui/switch-row";
import { SelectField } from "@/features/cv/components/cv/formPrimitives";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import {
  fetchMySchedules,
  fetchSavedSearches,
  fetchSystemSchedules,
  runMyScheduleNow,
  runScheduleNow,
  setMyScheduleEnabled,
  setSavedSearchSchedule,
  setSystemScheduleEnabled,
} from "@/api/scheduler";
import type { ScheduleItem } from "@/types/wire";

const SCHEDULE_PRESETS = [
  {
    labelKey: "scheduler.preset.off",
    trigger: null,
  },
  {
    labelKey: "scheduler.preset.every6h",
    trigger: { type: "interval", params: { every_minutes: 360 } },
  },
  {
    labelKey: "scheduler.preset.every12h",
    trigger: { type: "interval", params: { every_minutes: 720 } },
  },
  {
    labelKey: "scheduler.preset.daily8",
    trigger: { type: "daily_at", params: { time: "08:00", timezone: "UTC" } },
  },
  {
    labelKey: "scheduler.preset.weeklyMon8",
    trigger: {
      type: "weekly",
      params: { weekday: 0, time: "08:00", timezone: "UTC" },
    },
  },
];

function describeTrigger(trigger: ScheduleItem["trigger"]): string {
  const t = i18next.t;
  if (!trigger) return "—";
  const params = trigger.params ?? {};
  if (trigger.type === "interval")
    return t("scheduler.trigger.interval", { minutes: params.every_minutes });
  if (trigger.type === "daily_at")
    return t("scheduler.trigger.dailyAt", { time: params.time, timezone: params.timezone });
  if (trigger.type === "weekly")
    return t("scheduler.trigger.weekly", { weekday: params.weekday, time: params.time });
  if (trigger.type === "cron")
    return t("scheduler.trigger.cron", { expr: params.expr });
  if (trigger.type === "boot_stale")
    return t("scheduler.trigger.bootStale", { minutes: params.older_than_minutes });
  return trigger.type;
}

function statusBadge(status?: string | null): string {
  if (!status) return "—";
  return status.replace(/_/g, " ");
}

function kindLabel(kind: string): string {
  return i18next.t(`scheduler.kind.${kind}`, {
    defaultValue: kind.replace(/_/g, " "),
  });
}

function scheduleStatusVariant(status?: string | null) {
  if (status === "ok" || status === "succeeded") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status && status !== "—") return "warning" as const;
  return "outline" as const;
}

/** Settings → Automations (plan 148 phase 5): saved-search rhythms with
 * the preset picker, the user schedule rows with last-run/outcome/next
 * plus pause and run-now (B2 user-schedule endpoints), and the system
 * schedule table for admins. */
export function SchedulerSettings() {
  const { t } = useTranslation();
  const { user } = useAuthStore();
  const [mine, setMine] = useState<ScheduleItem[]>([]);
  const [savedSearches, setSavedSearches] = useState<
    { id: string; query: string; scope: string; saved: boolean }[]
  >([]);
  const [system, setSystem] = useState<ScheduleItem[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    void fetchMySchedules().then(setMine).catch(() => setMine([]));
    void fetchSavedSearches().then(setSavedSearches).catch(() => setSavedSearches([]));
    if (user?.is_admin) {
      void fetchSystemSchedules().then(setSystem).catch(() => setSystem([]));
    }
  }, [user?.is_admin]);

  useEffect(() => {
    load();
  }, [load]);

  const runUser = async (schedule: ScheduleItem, action: () => Promise<unknown>) => {
    setBusyId(schedule.id);
    setError("");
    try {
      await action();
      load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusyId(null);
    }
  };

  const savedScheduleFor = (searchId: string): ScheduleItem | undefined =>
    mine.find(
      (s) => s.kind === "user_saved_search" && s.payload?.search_id === searchId
    );

  const presetFor = (schedule?: ScheduleItem): number => {
    if (!schedule) return 0;
    return SCHEDULE_PRESETS.findIndex(
      (p) =>
        p.trigger &&
        schedule.trigger.type === p.trigger.type &&
        schedule.trigger.params?.every_minutes === p.trigger.params.every_minutes &&
        schedule.trigger.params?.time === p.trigger.params.time
    );
  };

  const rhythm = mine.filter((s) => s.kind !== "user_saved_search");

  return (
    <SettingsPage
      icon={CalendarClock}
      title={t("settingsNav.automations.label")}
      description={t("settingsNav.automations.description")}
      sections={[
        { id: "s-searches", label: t("scheduler.searchesTitle") },
        { id: "s-rhythm", label: t("scheduler.rhythmTitle") },
        ...(user?.is_admin
          ? [{ id: "s-system", label: t("scheduler.systemTitle") }]
          : []),
      ]}
    >
      {error ? (
        <p className="mb-3 text-xs text-[var(--as-danger)]" role="alert">
          {error}
        </p>
      ) : null}

      <section id="s-searches" className="scroll-mt-4">
        <SettingsSectionCard
          name="searches"
          title={t("scheduler.searchesTitle")}
          description={t("scheduler.searchesBody")}
        >
          {savedSearches.length === 0 ? (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("scheduler.noSavedSearches")}
            </p>
          ) : (
            <ul className="divide-y divide-[var(--as-border)]">
              {savedSearches.map((search) => {
                const schedule = savedScheduleFor(search.id);
                const current = presetFor(schedule);
                return (
                  <li
                    key={search.id}
                    className="flex flex-wrap items-center justify-between gap-3 py-2.5"
                    data-testid="saved-search-schedule"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-[var(--as-fg)]">
                        {search.query || t("scheduler.filtersOnly")}
                      </p>
                      <p className="text-xs text-[var(--as-muted-fg)]">
                        {schedule
                          ? `${describeTrigger(schedule.trigger)} · ${statusBadge(schedule.last_status)}`
                          : t("scheduler.notScheduled")}
                        {schedule && schedule.consecutive_failures
                          ? ` · ${t("scheduler.failures", { count: schedule.consecutive_failures })}`
                          : ""}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <SelectField
                        label={t("scheduler.searchesTitle")}
                        value={String(current >= 0 ? current : 0)}
                        onChange={(value) => {
                          const preset = SCHEDULE_PRESETS[Number(value)];
                          void setSavedSearchSchedule(search.id, preset.trigger)
                            .then(load)
                            .catch((err) => setError(String(err)));
                        }}
                        options={SCHEDULE_PRESETS.map((preset, index) => ({
                          value: String(index),
                          label: t(preset.labelKey),
                        }))}
                        testId={`saved-search-preset-${search.id}`}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </SettingsSectionCard>
      </section>

      <section id="s-rhythm" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="rhythm"
          title={t("scheduler.rhythmTitle")}
          description={t("scheduler.rhythmBody")}
        >
          {rhythm.length === 0 ? (
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("scheduler.noSavedSearches")}
            </p>
          ) : (
            <ul className="divide-y divide-[var(--as-border)]">
              {rhythm.map((schedule) => (
                <li
                  key={schedule.id}
                  className="flex flex-wrap items-center gap-3 py-2.5"
                  data-testid={`rhythm-${schedule.kind}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--as-fg)]">
                      {kindLabel(schedule.kind)}
                      <Badge variant={scheduleStatusVariant(schedule.last_status)}>
                        {statusBadge(schedule.last_status)}
                      </Badge>
                      {!schedule.enabled ? (
                        <Badge variant="outline">{t("scheduler.paused")}</Badge>
                      ) : null}
                    </p>
                    <p className="text-xs text-[var(--as-muted-fg)]">
                      {t("scheduler.last")}{" "}
                      {schedule.last_run_at
                        ? new Date(schedule.last_run_at).toLocaleString()
                        : "—"}
                      {" · "}
                      {schedule.next_run_at
                        ? t("scheduler.nextDate", {
                            date: new Date(schedule.next_run_at).toLocaleString(),
                          })
                        : "—"}
                      {schedule.consecutive_failures
                        ? ` · ${t("scheduler.failures", { count: schedule.consecutive_failures })}`
                        : ""}
                    </p>
                    {schedule.error ? (
                      <p className="truncate text-xs text-[var(--as-danger)]">
                        {schedule.error}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {schedule.task ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === schedule.id}
                        onClick={() =>
                          void runUser(schedule, () => runMyScheduleNow(schedule.id))
                        }
                        data-testid={`rhythm-run-${schedule.kind}`}
                      >
                        <Zap className="h-3.5 w-3.5" /> {t("scheduler.runNow")}
                      </Button>
                    ) : null}
                    <SwitchRow
                      label={t("scheduler.pauseToggle", { kind: kindLabel(schedule.kind) })}
                      checked={schedule.enabled}
                      disabled={busyId === schedule.id}
                      hideLabel
                      onCheckedChange={(enabled) =>
                        void runUser(schedule, () =>
                          setMyScheduleEnabled(schedule.id, enabled)
                        )
                      }
                      className="w-auto border-none bg-transparent px-1 py-0 hover:bg-transparent"
                      data-testid={`rhythm-enabled-${schedule.kind}`}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </SettingsSectionCard>
      </section>

      {user?.is_admin ? (
        <section id="s-system" className="mt-4 scroll-mt-4">
          <SettingsSectionCard
            name="system"
            title={t("scheduler.systemTitle")}
            description={t("scheduler.systemBody")}
            adminOnly
          >
            <ul className="divide-y divide-[var(--as-border)]">
              {system.map((schedule) => (
                <li
                  key={schedule.id}
                  className="flex flex-wrap items-center gap-3 py-2.5"
                  data-testid="system-schedule"
                >
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--as-fg)]">
                      {kindLabel(schedule.kind)}
                      <Badge variant={scheduleStatusVariant(schedule.last_status)}>
                        {statusBadge(schedule.last_status)}
                      </Badge>
                      {!schedule.enabled ? (
                        <Badge variant="outline">{t("scheduler.paused")}</Badge>
                      ) : null}
                    </p>
                    <p className="truncate text-xs text-[var(--as-muted-fg)]">
                      {describeTrigger(schedule.trigger)} ·{" "}
                      {schedule.next_run_at
                        ? `${t("scheduler.next")} ${new Date(schedule.next_run_at).toLocaleString()}`
                        : "—"}
                      {schedule.consecutive_failures
                        ? ` · ${t("scheduler.failures", { count: schedule.consecutive_failures })}`
                        : ""}
                    </p>
                    {schedule.error ? (
                      <p className="truncate text-xs text-[var(--as-danger)]">
                        {schedule.error}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void runScheduleNow(schedule.id).then(load)}
                      title={t("scheduler.runNextTick")}
                    >
                      <Zap className="h-3.5 w-3.5" /> {t("scheduler.runNow")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void setSystemScheduleEnabled(schedule.id, !schedule.enabled).then(
                          load
                        )
                      }
                    >
                      {schedule.enabled ? (
                        t("scheduler.pause")
                      ) : (
                        <>
                          <Play className="h-3.5 w-3.5" />
                          {t("scheduler.resume")}
                        </>
                      )}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </SettingsSectionCard>
        </section>
      ) : null}
    </SettingsPage>
  );
}
