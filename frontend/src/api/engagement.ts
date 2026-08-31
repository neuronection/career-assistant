import { api } from "./client";
import type {
  AlertRule,
  AlertRuleKind,
  AlertRuleParams,
  FeedResponse,
  NotificationItem,
  NotificationPreferences,
  NotificationsResponse,
  SearchRecord,
  SearchScope,
} from "@/types";

export async function recordSearch(body: {
  scope: SearchScope;
  query: string;
  filters: Record<string, unknown>;
  result_count: number;
}): Promise<SearchRecord> {
  const { data } = await api.post<SearchRecord>("/me/searches", body);
  return data;
}

export async function fetchSearches(params: {
  scope?: SearchScope;
  saved?: boolean;
} = {}): Promise<SearchRecord[]> {
  const { data } = await api.get<SearchRecord[]>("/me/searches", { params });
  return data;
}

export async function deleteSearch(id: string): Promise<void> {
  await api.delete(`/me/searches/${id}`);
}

export async function saveSearch(id: string): Promise<SearchRecord> {
  const { data } = await api.post<SearchRecord>(`/me/searches/${id}/save`);
  return data;
}

export async function fetchFeed(
  params: { view?: string; sort?: string; page?: number; page_size?: number } = {}
): Promise<FeedResponse> {
  const { data } = await api.get<FeedResponse>("/feed", { params });
  return data;
}

export async function fetchUnseenCount(): Promise<{ unseen: number }> {
  const { data } = await api.get<{ unseen: number }>("/feed/unseen-count");
  return data;
}

export async function markSeen(jobIds: string[]): Promise<{ marked: number }> {
  const { data } = await api.post<{ marked: number }>("/feed/seen", {
    job_ids: jobIds,
  });
  return data;
}

export async function saveJob(jobId: string, saved: boolean): Promise<void> {
  await api.post("/feed/save", { job_id: jobId, saved });
}

export async function hideJob(jobId: string, hidden: boolean): Promise<void> {
  await api.post("/feed/hide", { job_id: jobId, hidden });
}

export async function fetchNotifications(
  params: { unread?: boolean; kind?: string; limit?: number } = {}
): Promise<NotificationsResponse> {
  const { data } = await api.get<NotificationsResponse>("/notifications", { params });
  return data;
}

export async function markNotificationsRead(
  ids: string[] = []
): Promise<{ marked: number }> {
  const { data } = await api.post<{ marked: number }>("/notifications/read", {
    ids,
  });
  return data;
}

export async function fetchRules(): Promise<{ items: AlertRule[] }> {
  const { data } = await api.get<{ items: AlertRule[] }>("/notifications/rules");
  return data;
}

export async function updateRule(body: {
  kind: AlertRuleKind;
  params: Partial<AlertRuleParams>;
  enabled: boolean;
}): Promise<{ items: AlertRule[] }> {
  const { data } = await api.put<{ items: AlertRule[] }>("/notifications/rules", body);
  return data;
}

export function notificationLink(item: NotificationItem): string | null {
  const link = item.payload?.link;
  return typeof link === "string" && link.startsWith("/") ? link : null;
}

export async function fetchNotificationPreferences(): Promise<NotificationPreferences> {
  const { data } = await api.get<NotificationPreferences>(
    "/notifications/preferences"
  );
  return data;
}

export async function updateNotificationPreferences(
  body: NotificationPreferences
): Promise<NotificationPreferences> {
  const { data } = await api.put<NotificationPreferences>(
    "/notifications/preferences",
    body
  );
  return data;
}
