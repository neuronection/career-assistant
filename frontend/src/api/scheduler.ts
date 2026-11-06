import { api } from "@/api/client";
import type { ScheduleItem } from "@/types/wire";

export async function fetchMySchedules(): Promise<ScheduleItem[]> {
  const { data } = await api.get<ScheduleItem[]>("/me/schedules");
  return data;
}

export async function setMyScheduleEnabled(
  scheduleId: string,
  enabled: boolean
): Promise<ScheduleItem> {
  const { data } = await api.put<ScheduleItem>(`/me/schedules/${scheduleId}`, {
    enabled,
  });
  return data;
}

export async function runMyScheduleNow(
  scheduleId: string
): Promise<{ id: string; next_run_at: string | null }> {
  const { data } = await api.post<{ id: string; next_run_at: string | null }>(
    `/me/schedules/${scheduleId}/run-now`
  );
  return data;
}

export async function setSavedSearchSchedule(
  searchId: string,
  trigger: { type: string; params: Record<string, unknown> } | null
): Promise<ScheduleItem> {
  const { data } = await api.put<ScheduleItem>(
    `/me/searches/${searchId}/schedule`,
    { trigger }
  );
  return data;
}

export async function fetchSystemSchedules(): Promise<ScheduleItem[]> {
  const { data } = await api.get<ScheduleItem[]>("/admin/scheduler/schedules");
  return data;
}

export async function setSystemScheduleEnabled(
  scheduleId: string,
  enabled: boolean
): Promise<void> {
  await api.put(`/admin/scheduler/schedules/${scheduleId}`, { enabled });
}

export async function runScheduleNow(scheduleId: string): Promise<void> {
  await api.post(`/admin/scheduler/schedules/${scheduleId}/run-now`);
}

export async function fetchSavedSearches(): Promise<
  { id: string; query: string; scope: string; saved: boolean }[]
> {
  const { data } = await api.get("/me/searches?saved=true");
  return data;
}
