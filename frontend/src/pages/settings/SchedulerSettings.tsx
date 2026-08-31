import { useEffect, useState } from "react";
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
    label: "Off",
    trigger: null,
  },
  {
    label: "Every 6 hours",
    trigger: { type: "interval", params: { every_minutes: 360 } },
  },
  {
    label: "Every 12 hours",
    trigger: { type: "interval", params: { every_minutes: 720 } },
  },
  {
    label: "Daily at 08:00 UTC",
    trigger: { type: "daily_at", params: { time: "08:00", timezone: "UTC" } },
  },
  {
    label: "Weekly (Mon 08:00 UTC)",
    trigger: {
      type: "weekly",
      params: { weekday: 0, time: "08:00", timezone: "UTC" },
    },
  },
];

function describeTrigger(trigger: ScheduleItem["trigger"]): string {
  if (!trigger) return "—";
  const params = trigger.params ?? {};
  if (trigger.type === "interval") return `every ${params.every_minutes} min`;
  if (trigger.type === "daily_at") return `daily at ${params.time} (${params.timezone})`;
  if (trigger.type === "weekly") return `weekly on day ${params.weekday} at ${params.time}`;
  if (trigger.type === "cron") return `cron: ${params.expr}`;
  if (trigger.type === "boot_stale") return `when stale > ${params.older_than_minutes} min`;
  return trigger.type;
}

function statusBadge(status?: string | null): string {
  if (!status) return "—";
  return status.replace(/_/g, " ");
}

export function SchedulerSettings() {
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
          <Clock className="w-4 h-4 text-primary-600" /> Scheduled searches
        </h2>
        <p className="text-xs text-slate-400 mb-3">
          The app runs your saved postings searches on a schedule — new
          matches ping you and land in the Live tab.
        </p>
        {savedSearches.length === 0 ? (
          <p className="text-sm text-slate-400">
            No saved searches yet — save one from the Live tab first.
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
                      {search.query || "filters only"}
                    </p>
                    <p className="text-xs text-slate-400">
                      {schedule
                        ? `${describeTrigger(schedule.trigger)} · ${statusBadge(schedule.last_status)}`
                        : "not scheduled"}
                      {schedule && schedule.consecutive_failures
                        ? ` · ${schedule.consecutive_failures} failures`
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
                      <option key={preset.label} value={index}>
                        {preset.label}
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
        <h2 className="font-semibold text-slate-900 mb-3">My schedule rhythm</h2>
        <ul className="space-y-2">
          {mine
            .filter((s) => s.kind !== "user_saved_search")
            .map((schedule) => (
              <li
                key={schedule.id}
                className="bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between text-sm"
              >
                <span className="font-medium text-slate-800">
                  {schedule.kind === "user_checkin" ? "Quarterly check-in" : schedule.kind.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-slate-400">
                  {schedule.next_run_at
                    ? `next ${new Date(schedule.next_run_at).toLocaleDateString()}`
                    : "—"}
                </span>
              </li>
            ))}
        </ul>
      </section>

      {user?.is_admin && (
        <section>
          <h2 className="font-semibold text-slate-900 mb-3">System schedules</h2>
          <ul className="space-y-2">
            {system.map((schedule) => (
              <li
                key={schedule.id}
                className="bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between gap-3"
                data-testid="system-schedule"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800">
                    {schedule.kind.replace(/_/g, " ")}{" "}
                    {!schedule.enabled && (
                      <span className="text-xs text-amber-600">(paused)</span>
                    )}
                  </p>
                  <p className="text-xs text-slate-400 truncate">
                    {describeTrigger(schedule.trigger)} ·{" "}
                    {schedule.next_run_at
                      ? `next ${new Date(schedule.next_run_at).toLocaleString()}`
                      : "—"}{" "}
                    · last: {statusBadge(schedule.last_status)}
                    {schedule.consecutive_failures
                      ? ` · ${schedule.consecutive_failures} failures`
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
                    title="Run on the next tick"
                  >
                    <Zap className="w-3 h-3" /> run now
                  </button>
                  <button
                    onClick={() =>
                      void setSystemScheduleEnabled(schedule.id, !schedule.enabled).then(load)
                    }
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 flex items-center gap-1"
                  >
                    {schedule.enabled ? (
                      <>
                        <Pause className="w-3 h-3" /> pause
                      </>
                    ) : (
                      <>
                        <Play className="w-3 h-3" /> resume
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
