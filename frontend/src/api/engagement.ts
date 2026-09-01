import { api } from "./client";
import type {
  AlertRule,
  AlertRuleKind,
  AlertRuleParams,
  FeedResponse,
  NotificationItem,
  NotificationPreferences,
  NotificationsResponse,
  PreferencesMatrix,
  PushSubscriptionRecord,
  SearchRecord,
  SearchScope,
  ThreadsResponse,
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

export async function dismissNotifications(
  ids: string[] = []
): Promise<{ marked: number }> {
  const { data } = await api.post<{ marked: number }>("/notifications/dismiss", {
    ids,
  });
  return data;
}

export async function fetchUnreadCount(): Promise<{ unread_count: number }> {
  const { data } = await api.get<{ unread_count: number }>(
    "/notifications/unread-count"
  );
  return data;
}

export async function fetchThreads(
  params: { group?: string; limit?: number } = {}
): Promise<ThreadsResponse> {
  const { data } = await api.get<ThreadsResponse>("/notifications/threads", {
    params,
  });
  return data;
}

export async function fetchPreferencesMatrix(): Promise<PreferencesMatrix> {
  const { data } = await api.get<PreferencesMatrix>("/notifications/preferences");
  return data;
}

export async function setKindPreference(
  kindKey: string,
  body: { enabled?: boolean | null; channels?: string[] | null }
): Promise<{ key: string; enabled: boolean; channels: string[] }> {
  const { data } = await api.put(
    `/notifications/preferences/${kindKey}`,
    body
  );
  return data;
}

export async function fetchVapidPublicKey(): Promise<string> {
  const { data } = await api.get<{ public_key: string }>(
    "/notifications/vapid-key"
  );
  return data.public_key;
}

export async function subscribePush(body: {
  endpoint: string;
  p256dh: string;
  auth: string;
  device_id?: string;
  user_agent?: string;
}): Promise<PushSubscriptionRecord> {
  const { data } = await api.post<PushSubscriptionRecord>(
    "/notifications/subscriptions",
    body
  );
  return data;
}

export async function unsubscribePush(deviceId: string): Promise<void> {
  await api.delete(`/notifications/subscriptions/${deviceId}`);
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
