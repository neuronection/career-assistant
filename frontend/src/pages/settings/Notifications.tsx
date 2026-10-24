import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { BellOff, BellRing, CalendarDays, Mail, Rss, Webhook } from "lucide-react";
import { Input } from "@neuronection/assistant-ui";
import {
  fetchEmailChannelConfig,
  fetchEmailTransport,
  fetchFeedTokens,
  fetchPreferencesMatrix,
  fetchSearches,
  fetchVapidPublicKey,
  fetchWebhookChannelConfig,
  mintFeedToken,
  resendEmailVerification,
  revokeFeedToken,
  rotateFeedToken,
  setKindPreference,
  subscribePush,
  testEmailChannel,
  testWebhookChannel,
  unsubscribePush,
  updateEmailChannelConfig,
  updateEmailTransport,
  updateNotificationPreferences,
  updateWebhookChannelConfig,
  verifyEmailAddress,
} from "@/api/engagement";
import { FollowupRulesCard } from "@/features/postings/components/applications/FollowupRulesCard";
import { Button, Spinner } from "@/components/ui";
import { SelectField, ToggleRow } from "@/features/cv/components/cv/formPrimitives";
import { apiDetail } from "@/api/client";
import { hasChannel } from "@/lib/desktop";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { EmailChannelConfig, EmailTransportConfig, FeedToken, FeedTokenMinted, SearchRecord, WebhookChannelConfig } from "@/types/wire";
import type { PreferencesMatrix } from "@/types/wire";

const DEVICE_ID = "web";

const WEBHOOK_TEMPLATES = [
  { value: "generic", labelKey: "notifications.webhook.generic" },
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Microsoft Teams" },
  { value: "telegram", label: "Telegram" },
  { value: "ntfy", label: "ntfy" },
];

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function currentSubscription(): Promise<PushSubscription | null> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  const registration = await navigator.serviceWorker.getRegistration("/sw.js");
  return registration ? registration.pushManager.getSubscription() : null;
}

function feedUrl(path: string, token: string): string {
  const base = typeof window === "undefined" ? "" : window.location.origin;
  return `${base}/api/v1/me/${path}?token=${encodeURIComponent(token)}`;
}

function webcalUrl(token: string): string {
  return feedUrl("calendar.ics", token).replace(/^https?:/, "webcal:");
}

function errorText(error: unknown, fallback: string): string {
  return apiDetail(error) || fallback;
}

/** notification preferences: channels, email/webhook delivery, calendar and
 * RSS subscriptions and the per-kind routing matrix. Desktop-only controls
 * render only when the mode declares the channel. */
export function Notifications() {
  const { t } = useTranslation();
  const bootstrap = useBootstrapStore((s) => s.bootstrap);
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const browserChannel = hasChannel(bootstrap?.notification_channels, "browser");
  const desktopChannel = hasChannel(bootstrap?.notification_channels, "desktop");
  const [searchParams, setSearchParams] = useSearchParams();
  const [matrix, setMatrix] = useState<PreferencesMatrix | null>(null);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState<EmailChannelConfig | null>(null);
  const [emailAddress, setEmailAddress] = useState("");
  const [emailDigest, setEmailDigest] = useState(false);
  const [webhook, setWebhook] = useState<WebhookChannelConfig | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookTemplate, setWebhookTemplate] = useState("generic");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [smtp, setSmtp] = useState<EmailTransportConfig | null>(null);
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpFrom, setSmtpFrom] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [tokens, setTokens] = useState<FeedToken[]>([]);
  const [savedSearches, setSavedSearches] = useState<SearchRecord[]>([]);
  const [rssSearch, setRssSearch] = useState("");
  const [minted, setMinted] = useState<FeedTokenMinted | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [channelNotice, setChannelNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    void fetchPreferencesMatrix()
      .then(setMatrix)
      .catch(() => setMatrix(null));
    void fetchEmailChannelConfig()
      .then((config) => {
        setEmail(config);
        setEmailAddress(config.address);
        setEmailDigest(config.digest_mode);
      })
      .catch(() => setEmail(null));
    void fetchWebhookChannelConfig()
      .then((config) => {
        setWebhook(config);
        setWebhookUrl(config.url);
        setWebhookTemplate(config.template);
      })
      .catch(() => setWebhook(null));
    void fetchFeedTokens()
      .then(setTokens)
      .catch(() => setTokens([]));
    void fetchSearches({ saved: true })
      .then(setSavedSearches)
      .catch(() => setSavedSearches([]));
    if (isAdmin) {
      void fetchEmailTransport()
        .then((config) => {
          setSmtp(config);
          setSmtpHost(config.host);
          setSmtpPort(String(config.port));
          setSmtpFrom(config.from_address);
        })
        .catch(() => setSmtp(null));
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
    void currentSubscription().then((sub) => setPushEnabled(sub !== null));
  }, [load]);

  useEffect(() => {
    const token = searchParams.get("verify");
    if (!token) return;
    const next = new URLSearchParams(searchParams);
    next.delete("verify");
    setSearchParams(next, { replace: true });
    void verifyEmailAddress(token)
      .then((result) => {
        setNotice(result.verified ? t("notifications.emailVerifiedNotice") : null);
        load();
      })
      .catch(() => setNotice(null));
  }, [searchParams, setSearchParams, t, load]);

  const enablePush = async () => {
    setBusy(true);
    setError(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Permission denied");
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const key = await fetchVapidPublicKey();
      const sub = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key) as BufferSource,
      });
      const json = sub.toJSON();
      const keys = (json.keys ?? {}) as { p256dh?: string; auth?: string };
      if (!keys.p256dh || !keys.auth) throw new Error("Subscription missing keys");
      await subscribePush({
        endpoint: sub.endpoint,
        p256dh: keys.p256dh,
        auth: keys.auth,
        device_id: DEVICE_ID,
        user_agent: navigator.userAgent.slice(0, 300),
      });
      setPushEnabled(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Subscribe failed");
    } finally {
      setBusy(false);
    }
  };

  const disablePush = async () => {
    setBusy(true);
    try {
      const sub = await currentSubscription();
      if (sub) await sub.unsubscribe();
      await unsubscribePush(DEVICE_ID);
      setPushEnabled(false);
    } finally {
      setBusy(false);
    }
  };

  const toggleKind = (key: string, enabled: boolean) => {
    void setKindPreference(key, { enabled })
      .then(load)
      .catch(() => undefined);
  };

  const toggleKindChannel = (kindKey: string, channels: string[], channel: string) => {
    const next = new Set(channels);
    if (next.has(channel)) next.delete(channel);
    else next.add(channel);
    next.add("in_app");
    void setKindPreference(kindKey, { channels: [...next] })
      .then(load)
      .catch(() => undefined);
  };

  const setQuietHours = (patch: { start?: string; end?: string }) => {
    if (!matrix) return;
    const quiet = {
      start: patch.start ?? matrix.quiet_hours?.start ?? "22:00",
      end: patch.end ?? matrix.quiet_hours?.end ?? "07:00",
    };
    void updateNotificationPreferences({
      desktop_channel_enabled: matrix.desktop_channel_enabled,
      quiet_hours: quiet,
    })
      .then(load)
      .catch(() => undefined);
  };

  const saveEmail = () => {
    setBusy(true);
    setChannelNotice(null);
    void updateEmailChannelConfig({
      enabled: email?.enabled ?? true,
      address: emailAddress,
      digest_mode: emailDigest,
    })
      .then((config) => {
        setEmail(config);
        setEmailAddress(config.address);
        setChannelNotice(
          config.verified
            ? t("notifications.emailSaved")
            : t("notifications.emailVerificationSent", {
                address: config.pending_address || config.address,
              })
        );
        load();
      })
      .catch((exc) => setChannelNotice(errorText(exc, t("notifications.emailSaveFailed"))))
      .finally(() => setBusy(false));
  };

  const resendEmail = () => {
    void resendEmailVerification()
      .then((result) =>
        setChannelNotice(
          result.sent
            ? t("notifications.emailVerificationSent", { address: result.pending_address })
            : t("notifications.emailVerificationUnavailable")
        )
      )
      .catch((exc) =>
        setChannelNotice(errorText(exc, t("notifications.emailVerificationUnavailable")))
      );
  };

  const sendEmailTest = () => {
    void testEmailChannel()
      .then((result) =>
        setChannelNotice(
          result.status === "delivered"
            ? t("notifications.channelTestOk")
            : t("notifications.channelTestFailed", { error: result.error ?? result.status })
        )
      )
      .catch((exc) => setChannelNotice(errorText(exc, t("notifications.channelTestFailed", { error: "" }))));
  };

  const saveWebhook = () => {
    setBusy(true);
    setChannelNotice(null);
    void updateWebhookChannelConfig({
      enabled: webhook?.enabled ?? true,
      url: webhookUrl,
      template: webhookTemplate,
      secret: webhookSecret || null,
    })
      .then((config) => {
        setWebhook(config);
        setWebhookSecret("");
        setChannelNotice(t("notifications.webhookSaved"));
        load();
      })
      .catch((exc) => setChannelNotice(errorText(exc, t("notifications.webhookSaveFailed"))))
      .finally(() => setBusy(false));
  };

  const sendWebhookTest = () => {
    void testWebhookChannel()
      .then((result) =>
        setChannelNotice(
          result.status === "delivered"
            ? t("notifications.channelTestOk")
            : t("notifications.channelTestFailed", { error: result.error ?? result.status })
        )
      )
      .catch((exc) => setChannelNotice(errorText(exc, t("notifications.channelTestFailed", { error: "" }))));
  };

  const mintToken = (kind: "ics" | "rss") => {
    const scope: Record<string, string> =
      kind === "rss" && rssSearch ? { saved_search_id: rssSearch } : {};
    void mintFeedToken({ kind, scope })
      .then((result) => {
        setMinted(result);
        load();
      })
      .catch((exc) => setNotice(errorText(exc, t("notifications.feedMintFailed"))));
  };

  const rotateToken = (id: string) => {
    void rotateFeedToken(id)
      .then((result) => {
        setMinted(result);
        load();
      })
      .catch((exc) => setNotice(errorText(exc, t("notifications.feedRotateFailed"))));
  };

  const revokeToken = (id: string) => {
    void revokeFeedToken(id)
      .then(() => {
        setMinted((current) => (current?.id === id ? null : current));
        load();
      })
      .catch((exc) => setNotice(errorText(exc, t("notifications.feedRevokeFailed"))));
  };

  const saveSmtp = () => {
    setBusy(true);
    void updateEmailTransport({
      host: smtpHost,
      port: Number(smtpPort) || 587,
      from_address: smtpFrom,
      ...(smtpPassword ? { password: smtpPassword } : {}),
    })
      .then((config) => {
        setSmtp(config);
        setSmtpPassword("");
        setChannelNotice(t("notifications.smtpSaved"));
      })
      .catch((exc) => setChannelNotice(errorText(exc, t("notifications.smtpSaveFailed"))))
      .finally(() => setBusy(false));
  };

  return (
    <div className="max-w-2xl space-y-6" data-testid="notifications-settings">
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <BellRing className="w-4 h-4" /> {t("notifications.channelsTitle")}
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          {t("notifications.availableChannels", {
            channels: matrix?.channels.join(", ") ?? "…",
          })}
        </p>
        {desktopChannel && matrix && (
          <label className="mt-3 flex items-center justify-between text-sm text-slate-700">
            <span>{t("notifications.desktopToasts")}</span>
            <input
              type="checkbox"
              data-testid="desktop-channel-enabled"
              checked={matrix.desktop_channel_enabled}
              onChange={(e) => {
                void updateNotificationPreferences({
                  desktop_channel_enabled: e.target.checked,
                  quiet_hours: matrix.quiet_hours,
                })
                  .then(load)
                  .catch(() => undefined);
              }}
            />
          </label>
        )}
        {desktopChannel && matrix && (
          <div className="mt-3 flex items-center gap-2 text-sm text-slate-700">
            <span>{t("notifications.quietHours")}</span>
            <input
              type="time"
              data-testid="quiet-hours-start"
              value={matrix.quiet_hours?.start ?? ""}
              onChange={(e) => setQuietHours({ start: e.target.value })}
              className="border border-slate-200 rounded px-2 py-1 text-xs"
            />
            <span>–</span>
            <input
              type="time"
              data-testid="quiet-hours-end"
              value={matrix.quiet_hours?.end ?? ""}
              onChange={(e) => setQuietHours({ end: e.target.value })}
              className="border border-slate-200 rounded px-2 py-1 text-xs"
            />
          </div>
        )}
        <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
          {t("notifications.quietSemantics")}
        </p>
        {browserChannel && (
          <div className="mt-4 flex items-center justify-between" data-testid="browser-push">
            <div>
              <p className="text-sm text-slate-700">{t("notifications.browserNotifications")}</p>
              <p className="text-xs text-slate-500">{t("notifications.browserBody")}</p>
              {error && <p className="text-xs text-rose-600 mt-1">{error}</p>}
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void (pushEnabled ? disablePush() : enablePush())}
              className="ml-4 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
              data-testid="browser-push-toggle"
            >
              {pushEnabled ? (
                <>
                  <BellOff className="w-3.5 h-3.5" /> {t("notifications.disable")}
                </>
              ) : (
                <>
                  <BellRing className="w-3.5 h-3.5" /> {t("notifications.enable")}
                </>
              )}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="email-settings">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <Mail className="w-4 h-4" /> {t("notifications.emailTitle")}
        </h2>
        <p className="mt-1 text-xs text-slate-500">{t("notifications.emailBody")}</p>
        {email === null ? (
          <div className="mt-3"><Spinner /></div>
        ) : (
          <div className="mt-3 space-y-3">
            <ToggleRow
              label={t("notifications.emailEnabled")}
              checked={email.enabled}
              onChange={(enabled) => setEmail({ ...email, enabled })}
            />
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.emailAddress")}
              <Input
                value={emailAddress}
                data-testid="email-address"
                placeholder={t("notifications.emailAddressPlaceholder")}
                onChange={(event) => setEmailAddress(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <ToggleRow
              label={t("notifications.emailDigestMode")}
              checked={emailDigest}
              onChange={setEmailDigest}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={
                  email.verified
                    ? "rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700"
                    : "rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700"
                }
                data-testid="email-verified"
              >
                {email.verified
                  ? t("notifications.verified")
                  : t("notifications.notVerified")}
              </span>
              <Button size="sm" onClick={saveEmail} disabled={busy} data-testid="email-save">
                {t("common.save")}
              </Button>
              {!email.verified && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={resendEmail}
                  data-testid="email-resend"
                >
                  {t("notifications.resendVerification")}
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={sendEmailTest}
                disabled={!email.verified}
                data-testid="email-test"
              >
                {t("notifications.sendTest")}
              </Button>
            </div>
          </div>
        )}
      </section>

      {isAdmin && (
        <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="smtp-settings">
          <h2 className="text-sm font-semibold text-slate-900">{t("notifications.smtpTitle")}</h2>
          <p className="mt-1 text-xs text-slate-500">{t("notifications.smtpBody")}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.smtpHost")}
              <Input
                value={smtpHost}
                data-testid="smtp-host"
                onChange={(event) => setSmtpHost(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.smtpPort")}
              <Input
                value={smtpPort}
                inputMode="numeric"
                data-testid="smtp-port"
                onChange={(event) => setSmtpPort(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.smtpFrom")}
              <Input
                value={smtpFrom}
                data-testid="smtp-from"
                onChange={(event) => setSmtpFrom(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.smtpPassword")}
              <Input
                type="password"
                value={smtpPassword}
                data-testid="smtp-password"
                placeholder={smtp?.password_set ? "***" : ""}
                onChange={(event) => setSmtpPassword(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
          </div>
          <Button size="sm" className="mt-3" onClick={saveSmtp} disabled={busy} data-testid="smtp-save">
            {t("common.save")}
          </Button>
        </section>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="webhook-settings">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <Webhook className="w-4 h-4" /> {t("notifications.webhookTitle")}
        </h2>
        <p className="mt-1 text-xs text-slate-500">{t("notifications.webhookBody")}</p>
        {webhook === null ? (
          <div className="mt-3"><Spinner /></div>
        ) : (
          <div className="mt-3 space-y-3">
            <ToggleRow
              label={t("notifications.webhookEnabled")}
              checked={webhook.enabled}
              onChange={(enabled) => setWebhook({ ...webhook, enabled })}
            />
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.webhookUrl")}
              <Input
                value={webhookUrl}
                data-testid="webhook-url"
                placeholder={t("notifications.webhook.urlPlaceholder")}
                onChange={(event) => setWebhookUrl(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <SelectField
              label={t("notifications.webhookTemplate")}
              value={webhookTemplate}
              onChange={setWebhookTemplate}
              options={WEBHOOK_TEMPLATES.map((preset) => ({
                value: preset.value,
                label: preset.labelKey ? t(preset.labelKey) : (preset.label as string),
              }))}
              testId="webhook-template"
            />
            <label className="block text-xs text-[var(--as-muted-fg)]">
              {t("notifications.webhookSecret")}
              <Input
                type="password"
                value={webhookSecret}
                data-testid="webhook-secret"
                placeholder={webhook.secret_set ? "***" : ""}
                onChange={(event) => setWebhookSecret(event.target.value)}
                className="mt-1 w-full"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={
                  webhook.verified
                    ? "rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700"
                    : "rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700"
                }
                data-testid="webhook-verified"
              >
                {webhook.verified
                  ? t("notifications.verified")
                  : t("notifications.notVerified")}
              </span>
              <Button size="sm" onClick={saveWebhook} disabled={busy} data-testid="webhook-save">
                {t("common.save")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={sendWebhookTest}
                data-testid="webhook-test"
              >
                {t("notifications.sendTest")}
              </Button>
            </div>
          </div>
        )}
      </section>

      {channelNotice && (
        <p
          className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-[var(--as-fg)]"
          data-testid="channel-notice"
        >
          {channelNotice}
        </p>
      )}

      <section className="rounded-xl border border-slate-200 bg-white p-5" data-testid="feed-tokens">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <CalendarDays className="w-4 h-4" /> {t("notifications.feedsTitle")}
        </h2>
        <p className="mt-1 text-xs text-slate-500">{t("notifications.feedsBody")}</p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Button size="sm" onClick={() => mintToken("ics")} data-testid="mint-ics">
            <CalendarDays className="mr-1 h-3.5 w-3.5" /> {t("notifications.mintCalendar")}
          </Button>
          {savedSearches.length > 0 && (
            <>
              <SelectField
                label={t("notifications.feedSavedSearch")}
                value={rssSearch}
                onChange={setRssSearch}
                options={[
                  { value: "", label: t("notifications.feedAllPostings") },
                  ...savedSearches.map((search) => ({
                    value: search.id,
                    label: search.query || t("notifications.feedUntitledSearch"),
                  })),
                ]}
                testId="rss-search"
              />
              <Button size="sm" variant="outline" onClick={() => mintToken("rss")} data-testid="mint-rss">
                <Rss className="mr-1 h-3.5 w-3.5" /> {t("notifications.mintRss")}
              </Button>
            </>
          )}
        </div>
        {minted && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3" data-testid="feed-token-once">
            <p className="text-xs font-medium text-amber-800">
              {t("notifications.feedTokenOnce")}
            </p>
            <input
              readOnly
              value={
                minted.kind === "ics"
                  ? feedUrl("calendar.ics", minted.token)
                  : feedUrl("feeds/rss", minted.token)
              }
              data-testid="feed-token-secret"
              className="mt-2 w-full rounded border border-amber-200 bg-white p-1.5 font-mono text-[11px]"
            />
            {minted.kind === "ics" && (
              <a
                className="mt-2 inline-block text-xs text-[var(--as-accent)] underline"
                href={webcalUrl(minted.token)}
                data-testid="feed-webcal"
              >
                {t("notifications.webcalSubscribe")}
              </a>
            )}
          </div>
        )}
        <div className="mt-3 divide-y divide-slate-100">
          {tokens.length === 0 && (
            <p className="py-3 text-xs text-slate-500">{t("notifications.feedNoTokens")}</p>
          )}
          {tokens.map((token) => (
            <div
              key={token.id}
              className="flex items-center justify-between gap-2 py-2.5"
              data-testid={`feed-token-${token.id}`}
            >
              <div>
                <p className="text-sm text-slate-800">
                  {token.kind === "ics"
                    ? t("notifications.feedCalendar")
                    : t("notifications.feedRss")}
                  {token.scope.saved_search_id
                    ? ` · ${t("notifications.feedScoped")}`
                    : ""}
                </p>
                <p className="text-[11px] text-slate-400">
                  {token.revoked_at
                    ? t("notifications.feedRevoked")
                    : token.last_used_at
                      ? t("notifications.feedLastUsed", {
                          date: new Date(token.last_used_at).toLocaleString(),
                        })
                      : t("notifications.feedNeverUsed")}
                </p>
              </div>
              {token.revoked_at === null && (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => rotateToken(token.id)}
                    data-testid={`feed-token-rotate-${token.id}`}
                  >
                    {t("notifications.feedRotate")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => revokeToken(token.id)}
                    data-testid={`feed-token-revoke-${token.id}`}
                  >
                    {t("notifications.feedRevoke")}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
        {notice && (
          <p className="mt-2 text-xs text-rose-600" data-testid="feed-token-error">
            {notice}
          </p>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">{t("notifications.kindsTitle")}</h2>
        <p className="mt-1 text-xs text-slate-500">{t("notifications.kindsBody")}</p>
        <div className="mt-3 divide-y divide-slate-100">
          {(matrix?.kinds ?? []).map((kind) => (
            <div key={kind.key} className="flex items-center justify-between gap-3 py-2.5">
              <div>
                <p className="text-sm text-slate-800">{kind.label}</p>
                <p className="text-xs text-slate-400">
                  {kind.group}
                  {kind.mutable ? "" : ` · ${t("notifications.alwaysOn")}`}
                </p>
              </div>
              <div className="flex items-center gap-3">
                {(["email", "webhook"] as const).map((channel) => (
                  <label
                    key={channel}
                    className="flex items-center gap-1 text-[11px] text-slate-500"
                  >
                    <input
                      type="checkbox"
                      aria-label={t("notifications.routeChannel", {
                        channel,
                        name: kind.label,
                      })}
                      data-testid={`kind-${kind.key}-${channel}`}
                      disabled={!kind.mutable}
                      checked={kind.channels.includes(channel)}
                      onChange={() =>
                        toggleKindChannel(kind.key, kind.channels, channel)
                      }
                    />
                    {channel}
                  </label>
                ))}
                {kind.mutable && (
                  <input
                    type="checkbox"
                    aria-label={t("notifications.enableKind", { name: kind.label })}
                    data-testid={`kind-${kind.key}`}
                    checked={kind.enabled}
                    onChange={(e) => toggleKind(kind.key, e.target.checked)}
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">
          {t("notifications.followupTitle")}
        </h2>
        <p className="mt-1 text-xs text-slate-500">{t("notifications.followupBody")}</p>
        <div className="mt-3">
          <FollowupRulesCard showChannels />
        </div>
      </section>
    </div>
  );
}
