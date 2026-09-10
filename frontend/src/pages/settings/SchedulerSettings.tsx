import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Clock, Pause, Play, Zap } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import {
  fetchMySchedules,
  fetchSavedSearches,
  fetchSystemSchedules,
  runScheduleNow,
  setSavedSearchSchedule,
  setSystemScheduleEnabled,
} from "@/api/scheduler";
import type { ScheduleItem } from "@/types";

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

export function SchedulerSettings() {
  const { t } = useTranslation();
  const { user } = useAuthStore();
  const [mine, setMine] = useState<ScheduleItem[]>([]);
  const [savedSearches, setSavedSearches] = useState<
    { id: string; query: string; scope: string; saved: boolean }[]
  >([]);
  const [system, setSystem] = useState<ScheduleItem[]>([]);
  const [error, setError] = useState("");

  const load = () => {
    void fetchMySchedules().then(setMine).catch(() => setMine([]));
    void fetchSavedSearches().then(setSavedSearches).catch(() => setSavedSearches([]));
    if (user?.is_admin) {
      void fetchSystemSchedules().then(setSystem).catch(() => setSystem([]));
    }
  };

  useEffect(load, []);

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

  return (
    <div className="space-y-8 max-w-3xl" data-testid="scheduler-settings">
      <section>
        <h2 className="font-semibold text-slate-900 flex items-center gap-2">
          <Clock className="w-4 h-4 text-primary-600" /> {t("scheduler.searchesTitle")}
        </h2>
        <p className="text-xs text-slate-400 mb-3">
          {t("scheduler.searchesBody")}
        </p>
        {savedSearches.length === 0 ? (
          <p className="text-sm text-slate-400">
            {t("scheduler.noSavedSearches")}
          </p>
        ) : (
          <ul className="space-y-2">
            {savedSearches.map((search) => {
              const schedule = savedScheduleFor(search.id);
              const current = presetFor(schedule);
              return (
                <li
                  key={search.id}
                  className="bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between gap-3"
                  data-testid="saved-search-schedule"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800 truncate">
                      {search.query || t("scheduler.filtersOnly")}
                    </p>
                    <p className="text-xs text-slate-400">
                      {schedule
                        ? `${describeTrigger(schedule.trigger)} · ${statusBadge(schedule.last_status)}`
                        : t("scheduler.notScheduled")}
                      {schedule && schedule.consecutive_failures
                        ? ` · ${t("scheduler.failures", { count: schedule.consecutive_failures })}`
                        : ""}
                    </p>
                  </div>
                  <select
                    value={current >= 0 ? current : 0}
                    onChange={(e) => {
                      const preset = SCHEDULE_PRESETS[Number(e.target.value)];
                      void setSavedSearchSchedule(search.id, preset.trigger)
                        .then(load)
                        .catch((err) => setError(String(err)));
                    }}
                    className="text-sm border border-slate-200 rounded-lg px-2 py-1.5 shrink-0"
                  >
                    {SCHEDULE_PRESETS.map((preset, index) => (
                      <option key={preset.labelKey} value={index}>
                        {t(preset.labelKey)}
                      </option>
                    ))}
                  </select>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <h2 className="font-semibold text-slate-900 mb-3">{t("scheduler.rhythmTitle")}</h2>
        <ul className="space-y-2">
          {mine
            .filter((s) => s.kind !== "user_saved_search")
            .map((schedule) => (
              <li
                key={schedule.id}
                className="bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between text-sm"
              >
                <span className="font-medium text-slate-800">
                  {schedule.kind === "user_checkin"
                    ? t("scheduler.checkin")
                    : t(`scheduler.kind.${schedule.kind}`, {
                        defaultValue: schedule.kind.replace(/_/g, " "),
                      })}
                </span>
                <span className="text-xs text-slate-400">
                  {schedule.next_run_at
                    ? t("scheduler.nextDate", {
                        date: new Date(schedule.next_run_at).toLocaleDateString(),
                      })
                    : "—"}
                </span>
              </li>
            ))}
        </ul>
      </section>

      {user?.is_admin && (
        <section>
          <h2 className="font-semibold text-slate-900 mb-3">{t("scheduler.systemTitle")}</h2>
          <ul className="space-y-2">
            {system.map((schedule) => (
              <li
                key={schedule.id}
                className="bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between gap-3"
                data-testid="system-schedule"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800">
                    {t(`scheduler.kind.${schedule.kind}`, {
                      defaultValue: schedule.kind.replace(/_/g, " "),
                    })}{" "}
                    {!schedule.enabled && (
                      <span className="text-xs text-amber-600">({t("scheduler.paused")})</span>
                    )}
                  </p>
                  <p className="text-xs text-slate-400 truncate">
                    {describeTrigger(schedule.trigger)} ·{" "}
                    {schedule.next_run_at
                      ? `${t("scheduler.next")} ${new Date(schedule.next_run_at).toLocaleString()}`
                      : "—"}{" "}
                    · {t("scheduler.last")} {statusBadge(schedule.last_status)}
                    {schedule.consecutive_failures
                      ? ` · ${t("scheduler.failures", { count: schedule.consecutive_failures })}`
                      : ""}
                  </p>
                  {schedule.error && (
                    <p className="text-xs text-rose-500 truncate">{schedule.error}</p>
                  )}
                </div>
                <div className="flex gap-1.5 shrink-0">
                  <button
                    onClick={() => void runScheduleNow(schedule.id).then(load)}
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 flex items-center gap-1"
                    title={t("scheduler.runNextTick")}
                  >
                    <Zap className="w-3 h-3" /> {t("scheduler.runNow")}
                  </button>
                  <button
                    onClick={() =>
                      void setSystemScheduleEnabled(schedule.id, !schedule.enabled).then(load)
                    }
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 flex items-center gap-1"
                  >
                    {schedule.enabled ? (
                      <>
                        <Pause className="w-3 h-3" /> {t("scheduler.pause")}
                      </>
                    ) : (
                      <>
                        <Play className="w-3 h-3" /> {t("scheduler.resume")}
                      </>
                    )}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {error && <p className="text-sm text-rose-600">{error}</p>}
    </div>
  );
}
