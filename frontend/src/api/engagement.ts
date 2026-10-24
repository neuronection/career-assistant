import { api } from "@/api/client";
import type { AlertRule, AlertRuleParams, ChannelTestResult, EmailChannelConfig, EmailTransportConfig, FeedResponse, FeedToken, FeedTokenMinted, NotificationPreferences, NotificationsResponse, PushSubscriptionRecord, SearchRecord, SearchScope, WebhookChannelConfig } from "@/types/wire";
import type { NotificationItem, PreferencesMatrix } from "@/types/wire";
import type { NotificationRuleKind } from "@/types/wire";

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
  kind: NotificationRuleKind;
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

export async function fetchEmailChannelConfig(): Promise<EmailChannelConfig> {
  const { data } = await api.get<EmailChannelConfig>(
    "/notifications/channels/email"
  );
  return data;
}

export async function updateEmailChannelConfig(body: {
  enabled: boolean;
  address?: string | null;
  digest_mode: boolean;
}): Promise<EmailChannelConfig> {
  const { data } = await api.put<EmailChannelConfig>(
    "/notifications/channels/email",
    body
  );
  return data;
}

export async function resendEmailVerification(): Promise<{
  sent: boolean;
  pending_address: string;
}> {
  const { data } = await api.post<{ sent: boolean; pending_address: string }>(
    "/notifications/channels/email/verification"
  );
  return data;
}

export async function verifyEmailAddress(
  token: string
): Promise<{ verified: boolean }> {
  const { data } = await api.post<{ verified: boolean }>(
    "/notifications/channels/email/verify",
    { token }
  );
  return data;
}

export async function testEmailChannel(): Promise<ChannelTestResult> {
  const { data } = await api.post<ChannelTestResult>(
    "/notifications/channels/email/test"
  );
  return data;
}

export async function fetchWebhookChannelConfig(): Promise<WebhookChannelConfig> {
  const { data } = await api.get<WebhookChannelConfig>(
    "/notifications/channels/webhook"
  );
  return data;
}

export async function updateWebhookChannelConfig(body: {
  enabled: boolean;
  url?: string | null;
  template?: string | null;
  secret?: string | null;
}): Promise<WebhookChannelConfig> {
  const { data } = await api.put<WebhookChannelConfig>(
    "/notifications/channels/webhook",
    body
  );
  return data;
}

export async function testWebhookChannel(): Promise<ChannelTestResult> {
  const { data } = await api.post<ChannelTestResult>(
    "/notifications/channels/webhook/test"
  );
  return data;
}

export async function fetchFeedTokens(): Promise<FeedToken[]> {
  const { data } = await api.get<FeedToken[]>("/me/feed-tokens");
  return data;
}

export async function mintFeedToken(body: {
  kind: "ics" | "rss";
  scope?: Record<string, string>;
}): Promise<FeedTokenMinted> {
  const { data } = await api.post<FeedTokenMinted>("/me/feed-tokens", body);
  return data;
}

export async function rotateFeedToken(id: string): Promise<FeedTokenMinted> {
  const { data } = await api.post<FeedTokenMinted>(
    `/me/feed-tokens/${id}/rotate`
  );
  return data;
}

export async function revokeFeedToken(id: string): Promise<void> {
  await api.delete(`/me/feed-tokens/${id}`);
}

export async function fetchEmailTransport(): Promise<EmailTransportConfig> {
  const { data } = await api.get<EmailTransportConfig>(
    "/admin/notifications/email"
  );
  return data;
}

export async function updateEmailTransport(body: {
  host?: string;
  port?: number;
  username?: string;
  from_address?: string;
  from_name?: string;
  starttls?: boolean;
  use_ssl?: boolean;
  password?: string;
}): Promise<EmailTransportConfig> {
  const { data } = await api.put<EmailTransportConfig>(
    "/admin/notifications/email",
    body
  );
  return data;
}
