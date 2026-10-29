import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { BellOff, BellRing, CalendarDays, Clock, Mail, Megaphone, Radar, Rss, SlidersHorizontal, Webhook, Workflow } from "lucide-react";
import { Badge, Input } from "@neuronection/assistant-ui";
import { SwitchRow } from "@/components/ui/switch-row";
import {
  broadcastAnnouncement,
  fetchEmailChannelConfig,
  fetchEmailTransport,
  fetchFeedTokens,
  fetchNotificationDeliveries,
  fetchPreferencesMatrix,
  fetchRules,
  fetchSearches,
  fetchVapidPublicKey,
  fetchWebhookChannelConfig,
  mintFeedToken,
  resendEmailVerification,
  resetKindPreference,
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
  updateRule,
  updateWebhookChannelConfig,
  verifyEmailAddress,
} from "@/api/engagement";
import { FollowupRulesCard } from "@/features/postings/components/applications/FollowupRulesCard";
import { Button, Spinner } from "@/components/ui";
import {
  ChipTogglesRow,
  SelectField,
  StepperRow,
  ToggleRow,
} from "@/features/cv/components/cv/formPrimitives";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { KindMatrix } from "@/components/settings/KindMatrix";
import {
  useOptimisticToggle,
  useSettingsDraft,
} from "@/components/settings/useSettingsDraft";
import { apiDetail } from "@/api/client";
import { hasChannel } from "@/lib/desktop";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type {
  AlertRule,
  EmailChannelConfig,
  EmailTransportConfig,
  FeedToken,
  FeedTokenMinted,
  NotificationDeliveryRow,
  NotificationKindPref,
  NotificationRuleKind,
  PreferencesMatrix,
  SearchRecord,
  WebhookChannelConfig,
} from "@/types/wire";

const DEVICE_ID = "web";

const WEBHOOK_TEMPLATES: { value: string; labelKey?: string; label: string }[] = [
  { value: "generic", labelKey: "notifications.webhook.generic", label: "" },
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

const RAIL_SECTIONS = [
  { id: "s-channels", labelKey: "notifications.channelsTitle" },
  { id: "s-window", labelKey: "notifications.quietHours" },
  { id: "s-kinds", labelKey: "notifications.kindsTitle" },
  { id: "s-rules", labelKey: "notifications.rulesTitle" },
  { id: "s-feeds", labelKey: "notifications.feedsTitle" },
  { id: "s-followup", labelKey: "notifications.followupTitle" },
  { id: "s-admin", labelKey: "notifications.adminTitle" },
];

/** Notification settings (plan 148 phase 1): channel cards with live
 * delivery health, debounced delivery window, the kind-routing matrix,
 * alert rules, feed tokens, follow-up cadence and the admin zone
 * (SMTP transport + broadcast). Hybrid saves: switches commit instantly
 * with rollback, forms keep explicit Save buttons, every card shows its
 * save state. */
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
  const [email, setEmail] = useState<EmailChannelConfig | null>(null);
  const [webhook, setWebhook] = useState<WebhookChannelConfig | null>(null);
  const [tokens, setTokens] = useState<FeedToken[]>([]);
  const [savedSearches, setSavedSearches] = useState<SearchRecord[]>([]);
  const [rssSearch, setRssSearch] = useState("");
  const [minted, setMinted] = useState<FeedTokenMinted | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadMatrix = useCallback(() => {
    void fetchPreferencesMatrix()
      .then(setMatrix)
      .catch(() => setMatrix(null));
  }, []);

  const reload = useCallback(() => {
    loadMatrix();
    void fetchEmailChannelConfig()
      .then(setEmail)
      .catch(() => setEmail(null));
    void fetchWebhookChannelConfig()
      .then(setWebhook)
      .catch(() => setWebhook(null));
    void fetchFeedTokens()
      .then(setTokens)
      .catch(() => setTokens([]));
    void fetchSearches({ saved: true })
      .then(setSavedSearches)
      .catch(() => setSavedSearches([]));
  }, [loadMatrix]);

  useEffect(() => {
    reload();
    void currentSubscription().then((sub) => setPushEnabled(sub !== null));
  }, [reload]);

  useEffect(() => {
    const token = searchParams.get("verify");
    if (!token) return;
    const next = new URLSearchParams(searchParams);
    next.delete("verify");
    setSearchParams(next, { replace: true });
    void verifyEmailAddress(token)
      .then((result) => {
        setNotice(result.verified ? t("notifications.emailVerifiedNotice") : null);
        reload();
      })
      .catch(() => setNotice(null));
  }, [searchParams, setSearchParams, t, reload]);

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

  const kindCommits = useMemo(
    () => ({
      onSetChannels: async (kind: NotificationKindPref, channels: string[]) => {
        await setKindPreference(kind.key, { channels });
        loadMatrix();
      },
      onSetEnabled: async (kind: NotificationKindPref, enabled: boolean) => {
        await setKindPreference(kind.key, { enabled });
        loadMatrix();
      },
      onReset: async (kind: NotificationKindPref) => {
        await resetKindPreference(kind.key);
        loadMatrix();
      },
    }),
    [loadMatrix]
  );

  const needsAttention = email ? !email.verified : false;
  const activeChannels =
    (email?.enabled ? 1 : 0) +
    (webhook?.enabled ? 1 : 0) +
    (pushEnabled ? 1 : 0) +
    (matrix?.desktop_channel_enabled && desktopChannel ? 1 : 0);

  return (
    <SettingsPage
      icon={BellRing}
      title={t("settingsNav.notifications.label")}
      description={t("settingsNav.notifications.description")}
      statusChips={
        <>
          <Badge variant="success" data-testid="notifications-active-channels">
            {t("notifications.activeChannels", { count: activeChannels })}
          </Badge>
          {needsAttention ? (
            <Badge variant="warning" data-testid="notifications-needs-attention">
              {t("notifications.needsAttention")}
            </Badge>
          ) : null}
        </>
      }
      sections={RAIL_SECTIONS.map(({ id, labelKey }) => ({ id, label: t(labelKey) }))}
    >
      {notice ? (
        <p
          className="mb-3 rounded-lg bg-[var(--as-muted)] px-3 py-2 text-xs text-[var(--as-fg)]"
          data-testid="verify-notice"
        >
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="mb-3 text-xs text-[var(--as-danger)]" role="alert">
          {error}
        </p>
      ) : null}

      <section id="s-channels" className="scroll-mt-4">
        <div className="ca-settings-duo">
          <EmailChannelCard
            email={email}
            onChange={setEmail}
            onSaved={reload}
          />
          <WebhookChannelCard
            webhook={webhook}
            onChange={setWebhook}
            onSaved={reload}
          />
          {browserChannel ? (
            <SettingsSectionCard
              name="browser-push"
              title={t("notifications.browserNotifications")}
              description={t("notifications.browserBody")}
              icon={BellRing}
              badges={
                pushEnabled ? (
                  <Badge variant="success">{t("notifications.verified")}</Badge>
                ) : (
                  <Badge variant="outline">{t("notifications.disable")}</Badge>
                )
              }
            >
              <div className="flex justify-end" data-testid="browser-push">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void (pushEnabled ? disablePush() : enablePush())}
                  data-testid="browser-push-toggle"
                >
                  {pushEnabled ? (
                    <>
                      <BellOff className="h-3.5 w-3.5" /> {t("notifications.disable")}
                    </>
                  ) : (
                    <>
                      <BellRing className="h-3.5 w-3.5" /> {t("notifications.enable")}
                    </>
                  )}
                </Button>
              </div>
            </SettingsSectionCard>
          ) : null}
          {desktopChannel && matrix ? (
            <SettingsSectionCard
              name="desktop"
              title={t("notifications.desktopToasts")}
              icon={BellRing}
              badges={
                matrix.desktop_channel_enabled ? (
                  <Badge variant="success">{t("notifications.verified")}</Badge>
                ) : (
                  <Badge variant="outline">{t("notifications.disable")}</Badge>
                )
              }
            >
              <ToggleRow
                label={t("notifications.desktopToasts")}
                checked={matrix.desktop_channel_enabled}
                onChange={(checked) => {
                  void updateNotificationPreferences({
                    desktop_channel_enabled: checked,
                    quiet_hours: matrix.quiet_hours,
                  })
                    .then(loadMatrix)
                    .catch(() => undefined);
                }}
              />
            </SettingsSectionCard>
          ) : null}
        </div>
      </section>

      {matrix ? (
        <section id="s-window" className="mt-4 scroll-mt-4">
          <DeliveryWindowCard matrix={matrix} onChange={loadMatrix} />
        </section>
      ) : null}

      <section id="s-kinds" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="kinds"
          title={t("notifications.kindsTitle")}
          description={t("notifications.kindsBody")}
          icon={Workflow}
        >
          {matrix ? (
            <KindMatrix
              channels={matrix.channels}
              kinds={matrix.kinds}
              {...kindCommits}
            />
          ) : (
            <Spinner />
          )}
        </SettingsSectionCard>
      </section>

      <section id="s-rules" className="mt-4 scroll-mt-4">
        <AlertRulesCard />
      </section>

      <section id="s-feeds" className="mt-4 scroll-mt-4">
        <FeedsCard
          tokens={tokens}
          savedSearches={savedSearches}
          rssSearch={rssSearch}
          onRssSearch={setRssSearch}
          minted={minted}
          onMinted={setMinted}
          onTokens={setTokens}
          onError={setNotice}
        />
      </section>

      <section id="s-followup" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="followup"
          title={t("notifications.followupTitle")}
          description={t("notifications.followupBody")}
          icon={CalendarDays}
        >
          <FollowupRulesCard showChannels />
        </SettingsSectionCard>
      </section>

      {isAdmin ? (
        <section id="s-admin" className="mt-4 scroll-mt-4">
          <div className="ca-settings-duo">
            <SmtpCard />
            <BroadcastCard />
          </div>
          <div className="mt-4">
            <DeliveryHealthCard />
          </div>
        </section>
      ) : null}
    </SettingsPage>
  );
}

/** Per-card one-line notice (the old page routed every channel result
 * through one detached line — plan 148 moves results INTO their card). */
function CardNotice({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p
      className="mt-2 rounded-lg bg-[var(--as-muted)] px-2.5 py-1.5 text-xs text-[var(--as-fg)]"
      data-testid="channel-notice"
    >
      {text}
    </p>
  );
}

function EmailChannelCard({
  email,
  onChange,
  onSaved,
}: {
  email: EmailChannelConfig | null;
  onChange: (config: EmailChannelConfig) => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const { toggle, valueOf } = useOptimisticToggle();
  const [notice, setNotice] = useState<string | null>(null);
  const draft = useSettingsDraft({
    initial: {
      address: email?.address ?? "",
      digest_mode: email?.digest_mode ?? false,
    },
    buildPayload: (value) =>
      value.address ? { address: value.address, digest_mode: value.digest_mode } : null,
    onSave: async (payload) => {
      const config = await updateEmailChannelConfig({
        enabled: email?.enabled ?? true,
        ...payload,
      });
      onChange(config);
      onSaved();
      setNotice(
        config.verified
          ? t("notifications.emailSaved")
          : t("notifications.emailVerificationSent", {
              address: config.pending_address || config.address,
            })
      );
    },
  });

  if (!email) {
    return (
      <SettingsSectionCard
        name="email"
        title={t("notifications.emailTitle")}
        description={t("notifications.emailBody")}
        icon={Mail}
      >
        <Spinner />
      </SettingsSectionCard>
    );
  }
  const enabled = valueOf("email", email.enabled);
  return (
    <SettingsSectionCard
      name="email"
      title={t("notifications.emailTitle")}
      description={t("notifications.emailBody")}
      icon={Mail}
      badges={
        email.verified ? (
          <Badge variant="success" data-testid="email-verified">
            {t("notifications.verified")}
          </Badge>
        ) : (
          <Badge variant="warning" data-testid="email-verified">
            {t("notifications.notVerified")}
          </Badge>
        )
      }
      saveState={draft.state}
      saveError={draft.error}
      onRetrySave={() => void draft.save()}
      footer={
        <>
          <Button size="sm" onClick={() => void draft.save()} data-testid="email-save">
            {t("common.save")}
          </Button>
          {!email.verified ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void resendEmailVerification()
                  .then((result) =>
                    setNotice(
                      result.sent
                        ? t("notifications.emailVerificationSent", {
                            address: result.pending_address,
                          })
                        : t("notifications.emailVerificationUnavailable")
                    )
                  )
                  .catch((exc) =>
                    setNotice(
                      errorText(exc, t("notifications.emailVerificationUnavailable"))
                    )
                  );
              }}
              data-testid="email-resend"
            >
              {t("notifications.resendVerification")}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void testEmailChannel()
                .then((result) =>
                  setNotice(
                    result.status === "delivered"
                      ? t("notifications.channelTestOk")
                      : t("notifications.channelTestFailed", {
                          error: result.error ?? result.status,
                        })
                  )
                )
                .catch((exc) =>
                  setNotice(
                    errorText(exc, t("notifications.channelTestFailed", { error: "" }))
                  )
                );
            }}
            disabled={!email.verified}
            data-testid="email-test"
          >
            {t("notifications.sendTest")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <SwitchRow
          label={t("notifications.emailEnabled")}
          checked={enabled}
          onCheckedChange={(next) => {
            void toggle("email", next, async () => {
              const config = await updateEmailChannelConfig({
                enabled: next,
                address: email.address,
                digest_mode: email.digest_mode,
              });
              onChange(config);
            });
          }}
        />
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.emailAddress")}
          <Input
            value={draft.draft.address}
            data-testid="email-address"
            placeholder={t("notifications.emailAddressPlaceholder")}
            onChange={(event) =>
              draft.setDraft((prev) => ({ ...prev, address: event.target.value }))
            }
            className="mt-1 w-full"
          />
        </label>
        <ToggleRow
          label={t("notifications.emailDigestMode")}
          checked={draft.draft.digest_mode}
          onChange={(digest_mode) => draft.setDraft((prev) => ({ ...prev, digest_mode }))}
        />
        <CardNotice text={notice} />
      </div>
    </SettingsSectionCard>
  );
}

function WebhookChannelCard({
  webhook,
  onChange,
  onSaved,
}: {
  webhook: WebhookChannelConfig | null;
  onChange: (config: WebhookChannelConfig) => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const { toggle, valueOf } = useOptimisticToggle();
  const [notice, setNotice] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const draft = useSettingsDraft({
    initial: {
      url: webhook?.url ?? "",
      template: webhook?.template ?? "generic",
    },
    buildPayload: (value) => (value.url ? value : null),
    onSave: async (payload) => {
      const config = await updateWebhookChannelConfig({
        enabled: webhook?.enabled ?? true,
        url: payload.url,
        template: payload.template,
        secret: secret || null,
      });
      setSecret("");
      onChange(config);
      onSaved();
      setNotice(t("notifications.webhookSaved"));
    },
  });

  if (!webhook) {
    return (
      <SettingsSectionCard
        name="webhook"
        title={t("notifications.webhookTitle")}
        description={t("notifications.webhookBody")}
        icon={Webhook}
      >
        <Spinner />
      </SettingsSectionCard>
    );
  }
  const enabled = valueOf("webhook", webhook.enabled);
  return (
    <SettingsSectionCard
      name="webhook"
      title={t("notifications.webhookTitle")}
      description={t("notifications.webhookBody")}
      icon={Webhook}
      badges={
        webhook.verified ? (
          <Badge variant="success" data-testid="webhook-verified">
            {t("notifications.verified")}
          </Badge>
        ) : (
          <Badge variant="warning" data-testid="webhook-verified">
            {t("notifications.notVerified")}
          </Badge>
        )
      }
      saveState={draft.state}
      saveError={draft.error}
      onRetrySave={() => void draft.save()}
      footer={
        <>
          <Button size="sm" onClick={() => void draft.save()} data-testid="webhook-save">
            {t("common.save")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void testWebhookChannel()
                .then((result) =>
                  setNotice(
                    result.status === "delivered"
                      ? t("notifications.channelTestOk")
                      : t("notifications.channelTestFailed", {
                          error: result.error ?? result.status,
                        })
                  )
                )
                .catch((exc) =>
                  setNotice(
                    errorText(exc, t("notifications.channelTestFailed", { error: "" }))
                  )
                );
            }}
            data-testid="webhook-test"
          >
            {t("notifications.sendTest")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <SwitchRow
          label={t("notifications.webhookEnabled")}
          checked={enabled}
          onCheckedChange={(next) => {
            void toggle("webhook", next, async () => {
              const config = await updateWebhookChannelConfig({
                enabled: next,
                url: webhook.url,
                template: webhook.template,
                secret: null,
              });
              onChange(config);
            });
          }}
        />
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.webhookUrl")}
          <Input
            value={draft.draft.url}
            data-testid="webhook-url"
            placeholder={t("notifications.webhook.urlPlaceholder")}
            onChange={(event) =>
              draft.setDraft((prev) => ({ ...prev, url: event.target.value }))
            }
            className="mt-1 w-full"
          />
        </label>
        <SelectField
          label={t("notifications.webhookTemplate")}
          value={draft.draft.template}
          onChange={(template) => draft.setDraft((prev) => ({ ...prev, template }))}
          options={WEBHOOK_TEMPLATES.map((preset) => ({
            value: preset.value,
            label: preset.labelKey ? t(preset.labelKey) : preset.label,
          }))}
          testId="webhook-template"
        />
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.webhookSecret")}
          <Input
            type="password"
            value={secret}
            data-testid="webhook-secret"
            placeholder={webhook.secret_set ? "***" : ""}
            onChange={(event) => setSecret(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
        <CardNotice text={notice} />
      </div>
    </SettingsSectionCard>
  );
}

function DeliveryWindowCard({
  matrix,
  onChange,
}: {
  matrix: PreferencesMatrix;
  onChange: () => void;
}) {
  const { t } = useTranslation();
  const draft = useSettingsDraft({
    initial: {
      start: matrix.quiet_hours?.start ?? "22:00",
      end: matrix.quiet_hours?.end ?? "07:00",
    },
    mode: "autosave",
    delay: 800,
    buildPayload: (value) => value,
    onSave: async (payload) => {
      await updateNotificationPreferences({
        desktop_channel_enabled: matrix.desktop_channel_enabled,
        quiet_hours: payload,
      });
      onChange();
    },
  });
  return (
    <SettingsSectionCard
      name="window"
      title={t("notifications.quietHours")}
      description={t("notifications.quietSemantics")}
      icon={Clock}
      saveState={draft.state}
      saveError={draft.error}
      onRetrySave={() => void draft.save()}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-[var(--as-fg)]">{t("notifications.quietHours")}</span>
        <input
          type="time"
          data-testid="quiet-hours-start"
          value={draft.draft.start}
          onChange={(e) => draft.setDraft((prev) => ({ ...prev, start: e.target.value }))}
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1 text-sm text-[var(--as-fg)]"
        />
        <span className="text-[var(--as-muted-fg)]">–</span>
        <input
          type="time"
          data-testid="quiet-hours-end"
          value={draft.draft.end}
          onChange={(e) => draft.setDraft((prev) => ({ ...prev, end: e.target.value }))}
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1 text-sm text-[var(--as-fg)]"
        />
      </div>
    </SettingsSectionCard>
  );
}

function AlertRulesCard() {
  const { t } = useTranslation();
  const bootstrap = useBootstrapStore((s) => s.bootstrap);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const { toggle, valueOf } = useOptimisticToggle();

  useEffect(() => {
    void fetchRules()
      .then((result) => setRules(result.items))
      .catch(() => setRules([]));
  }, []);

  const save = async (
    rule: AlertRule,
    params: Partial<AlertRule["params"]>,
    enabled?: boolean
  ) => {
    const result = await updateRule({
      kind: rule.kind as NotificationRuleKind,
      params: { ...rule.params, ...params },
      enabled: enabled ?? rule.enabled,
    });
    setRules(result.items);
  };

  const familyOptions = (bootstrap?.target_families ?? []).map((key) => ({
    value: key,
    label: key,
  }));

  return (
    <SettingsSectionCard
      name="rules"
      title={t("notifications.rulesTitle")}
      description={t("notifications.rulesBody")}
      icon={SlidersHorizontal}
    >
      {rules.length === 0 ? (
        <Spinner />
      ) : (
        <div className="divide-y divide-[var(--as-border)]">
          {rules.map((rule) => {
            const enabled = valueOf(`rule:${rule.kind}`, rule.enabled);
            return (
              <div key={rule.kind} className="py-3 first:pt-0 last:pb-0" data-testid={`rule-${rule.kind}`}>
                <SwitchRow
                  label={t(`notifications.ruleTitle.${rule.kind}`)}
                  currentValue={t(`notifications.ruleHint.${rule.kind}`)}
                  checked={enabled}
                  onCheckedChange={(next) =>
                    void toggle(`rule:${rule.kind}`, next, () => save(rule, {}, next))
                  }
                />
                <div className="mt-2 space-y-2 pl-1">
                  {rule.kind === "fit_threshold" ? (
                    <StepperRow
                      label={t("notifications.ruleMinFit")}
                      value={rule.params.min_fit}
                      min={0}
                      max={10}
                      step={0.5}
                      onChange={(min_fit) => void save(rule, { min_fit })}
                    />
                  ) : null}
                  {rule.kind !== "fit_threshold" ? (
                    <StepperRow
                      label={t("notifications.ruleMaxPerDay")}
                      value={rule.params.max_per_day ?? 5}
                      min={1}
                      max={50}
                      onChange={(max_per_day) => void save(rule, { max_per_day })}
                    />
                  ) : null}
                  {rule.kind === "new_in_family" && (rule.params.family_keys ?? []).length > 0 ? (
                    <>
                      <ChipTogglesRow
                        label={t("notifications.ruleFamilies")}
                        values={rule.params.family_keys ?? []}
                        options={familyOptions}
                        onChange={(family_keys) => void save(rule, { family_keys })}
                      />
                      {(rule.params.muted_family_keys ?? []).length > 0 ? (
                        <ChipTogglesRow
                          label={t("notifications.ruleMutedFamilies")}
                          values={rule.params.muted_family_keys ?? []}
                          options={familyOptions}
                          onChange={(muted_family_keys) =>
                            void save(rule, { muted_family_keys })
                          }
                        />
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </SettingsSectionCard>
  );
}

function FeedsCard({
  tokens,
  savedSearches,
  rssSearch,
  onRssSearch,
  minted,
  onMinted,
  onTokens,
  onError,
}: {
  tokens: FeedToken[];
  savedSearches: SearchRecord[];
  rssSearch: string;
  onRssSearch: (value: string) => void;
  minted: FeedTokenMinted | null;
  onMinted: (value: FeedTokenMinted | null) => void;
  onTokens: (value: FeedToken[]) => void;
  onError: (value: string | null) => void;
}) {
  const { t } = useTranslation();

  const mintToken = (kind: "ics" | "rss") => {
    const scope: Record<string, string> =
      kind === "rss" && rssSearch ? { saved_search_id: rssSearch } : {};
    void mintFeedToken({ kind, scope })
      .then((result) => {
        onMinted(result);
        void fetchFeedTokens().then(onTokens);
      })
      .catch((exc) => onError(errorText(exc, t("notifications.feedMintFailed"))));
  };
  const rotateToken = (id: string) => {
    void rotateFeedToken(id)
      .then((result) => {
        onMinted(result);
        void fetchFeedTokens().then(onTokens);
      })
      .catch((exc) => onError(errorText(exc, t("notifications.feedRotateFailed"))));
  };
  const revokeToken = (id: string) => {
    void revokeFeedToken(id)
      .then(() => {
        onMinted(minted?.id === id ? null : minted);
        void fetchFeedTokens().then(onTokens);
      })
      .catch((exc) => onError(errorText(exc, t("notifications.feedRevokeFailed"))));
  };

  return (
    <SettingsSectionCard
      name="feeds"
      title={t("notifications.feedsTitle")}
      description={t("notifications.feedsBody")}
      icon={Rss}
      footer={
        <>
          <Button size="sm" variant="outline" onClick={() => mintToken("ics")} data-testid="mint-ics">
            <CalendarDays className="mr-1 h-3.5 w-3.5" /> {t("notifications.mintCalendar")}
          </Button>
          {savedSearches.length > 0 ? (
            <>
              <SelectField
                label={t("notifications.feedSavedSearch")}
                value={rssSearch}
                onChange={onRssSearch}
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
          ) : null}
        </>
      }
    >
      {minted ? (
        <div
          className="mb-3 rounded-lg border border-[color-mix(in_srgb,var(--as-warning)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-warning)_14%,var(--as-surface-raised))] p-3"
          data-testid="feed-token-once"
        >
          <p className="text-xs font-medium text-[var(--as-fg)]">
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
            className="mt-2 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-1.5 font-mono text-[11px] text-[var(--as-fg)]"
          />
          {minted.kind === "ics" ? (
            <a
              className="mt-2 inline-block text-xs text-[var(--as-primary)] underline"
              href={webcalUrl(minted.token)}
              data-testid="feed-webcal"
            >
              {t("notifications.webcalSubscribe")}
            </a>
          ) : null}
        </div>
      ) : null}
      <div className="divide-y divide-[var(--as-border)]">
        {tokens.length === 0 ? (
          <p className="py-2 text-xs text-[var(--as-muted-fg)]">
            {t("notifications.feedNoTokens")}
          </p>
        ) : null}
        {tokens.map((token) => (
          <div
            key={token.id}
            className="flex items-center justify-between gap-2 py-2.5"
            data-testid={`feed-token-${token.id}`}
          >
            <div className="min-w-0">
              <p className="text-sm text-[var(--as-fg)]">
                {token.kind === "ics"
                  ? t("notifications.feedCalendar")
                  : t("notifications.feedRss")}
                {token.scope.saved_search_id
                  ? ` · ${t("notifications.feedScoped")}`
                  : ""}
              </p>
              <p className="text-[11px] text-[var(--as-muted-fg)]">
                {t("notifications.feedCreated", {
                  date: new Date(token.created_at).toLocaleDateString(),
                })}
                {" · "}
                {token.revoked_at
                  ? t("notifications.feedRevoked")
                  : token.last_used_at
                    ? t("notifications.feedLastUsed", {
                        date: new Date(token.last_used_at).toLocaleString(),
                      })
                    : t("notifications.feedNeverUsed")}
              </p>
            </div>
            {token.revoked_at === null ? (
              <div className="flex shrink-0 gap-1">
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
            ) : null}
          </div>
        ))}
      </div>
    </SettingsSectionCard>
  );
}

function SmtpCard() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<EmailTransportConfig | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const draft = useSettingsDraft({
    initial: {
      host: config?.host ?? "",
      port: config ? String(config.port) : "587",
      username: config?.username ?? "",
      from_address: config?.from_address ?? "",
      from_name: config?.from_name ?? "",
      starttls: config?.starttls ?? true,
      use_ssl: config?.use_ssl ?? false,
    },
    buildPayload: (value) =>
      value.host ? { ...value, port: Number(value.port) || 587 } : null,
    onSave: async (payload) => {
      const saved = await updateEmailTransport({
        ...payload,
        ...(password ? { password } : {}),
      });
      setConfig(saved);
      setPassword("");
      setNotice(t("notifications.smtpSaved"));
    },
  });

  useEffect(() => {
    void fetchEmailTransport()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const field = (key: keyof typeof draft.draft, label: string, testid: string) => (
    <label className="block text-xs text-[var(--as-muted-fg)]">
      {label}
      <Input
        value={String(draft.draft[key] ?? "")}
        data-testid={testid}
        onChange={(event) =>
          draft.setDraft((prev) => ({ ...prev, [key]: event.target.value }))
        }
        className="mt-1 w-full"
      />
    </label>
  );

  return (
    <SettingsSectionCard
      name="smtp"
      title={t("notifications.smtpTitle")}
      description={t("notifications.smtpBody")}
      icon={Mail}
      adminOnly
      collapsible
      defaultOpen={false}
      badges={
        config ? (
          <Badge variant="success">{t("notifications.verified")}</Badge>
        ) : (
          <Badge variant="outline">{t("notifications.disable")}</Badge>
        )
      }
      saveState={draft.state}
      saveError={draft.error}
      onRetrySave={() => void draft.save()}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {field("host", t("notifications.smtpHost"), "smtp-host")}
        {field("port", t("notifications.smtpPort"), "smtp-port")}
        {field("username", t("notifications.smtpUsername"), "smtp-username")}
        {field("from_address", t("notifications.smtpFrom"), "smtp-from")}
        {field("from_name", t("notifications.smtpFromName"), "smtp-from-name")}
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.smtpPassword")}
          <Input
            type="password"
            value={password}
            data-testid="smtp-password"
            placeholder={config?.password_set ? "***" : ""}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
        <ToggleRow
          label={t("notifications.smtpStarttls")}
          checked={draft.draft.starttls}
          onChange={(starttls) => draft.setDraft((prev) => ({ ...prev, starttls }))}
        />
        <ToggleRow
          label={t("notifications.smtpUseSsl")}
          checked={draft.draft.use_ssl}
          onChange={(use_ssl) => draft.setDraft((prev) => ({ ...prev, use_ssl }))}
        />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" onClick={() => void draft.save()} data-testid="smtp-save">
          {t("common.save")}
        </Button>
        <CardNotice text={notice} />
      </div>
    </SettingsSectionCard>
  );
}

function BroadcastCard() {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <SettingsSectionCard
      name="broadcast"
      title={t("notifications.broadcastTitle")}
      description={t("notifications.broadcastBody")}
      icon={Megaphone}
      adminOnly
    >
      <div className="space-y-2">
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.broadcastTitleField")}
          <Input
            value={title}
            data-testid="broadcast-title"
            onChange={(event) => setTitle(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.broadcastBodyField")}
          <Input
            value={body}
            data-testid="broadcast-body"
            onChange={(event) => setBody(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
        <label className="block text-xs text-[var(--as-muted-fg)]">
          {t("notifications.broadcastLink")}
          <Input
            value={link}
            data-testid="broadcast-link"
            onChange={(event) => setLink(event.target.value)}
            className="mt-1 w-full"
          />
        </label>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            disabled={busy || title.trim().length === 0}
            data-testid="broadcast-send"
            onClick={() => {
              setBusy(true);
              setNotice(null);
              void broadcastAnnouncement({
                title: title.trim(),
                body: body.trim(),
                link: link.trim() || null,
              })
                .then((result) => {
                  setNotice(t("notifications.broadcastSent", { count: result.delivered }));
                  setTitle("");
                  setBody("");
                  setLink("");
                })
                .catch((exc) => setNotice(errorText(exc, t("notifications.broadcastFailed"))))
                .finally(() => setBusy(false));
            }}
          >
            {t("notifications.broadcastSend")}
          </Button>
          <CardNotice text={notice} />
        </div>
      </div>
    </SettingsSectionCard>
  );
}

function DeliveryHealthCard() {
  const { t } = useTranslation();
  const [items, setItems] = useState<NotificationDeliveryRow[] | null>(null);

  useEffect(() => {
    void fetchNotificationDeliveries({ limit: 40 })
      .then((result) => setItems(result.items))
      .catch(() => setItems([]));
  }, []);

  const latest = useMemo(() => {
    const byChannel = new Map<string, NotificationDeliveryRow>();
    for (const row of items ?? []) {
      if (!byChannel.has(row.channel)) byChannel.set(row.channel, row);
    }
    return [...byChannel.values()];
  }, [items]);
  const failures = (items ?? []).filter((row) => row.status === "failed").length;

  return (
    <SettingsSectionCard
      name="health"
      title={t("notifications.healthTitle")}
      description={t("notifications.healthBody")}
      icon={Radar}
      adminOnly
      badges={
        failures > 0 ? (
          <Badge variant="danger" data-testid="delivery-failures">
            {t("notifications.healthFailures", { count: failures })}
          </Badge>
        ) : null
      }
    >
      {items === null ? (
        <Spinner />
      ) : items.length === 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]">{t("notifications.healthEmpty")}</p>
      ) : (
        <ul className="divide-y divide-[var(--as-border)]" data-testid="delivery-health">
          {latest.map((row) => (
            <li key={row.channel} className="flex items-center justify-between gap-2 py-2" data-testid={`delivery-${row.channel}`}>
              <span className="text-sm text-[var(--as-fg)]">
                {t(`notifications.channel.${row.channel}`)}
              </span>
              <span className="flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
                {row.error ? (
                  <span className="truncate text-[var(--as-danger)]" title={row.error}>
                    {row.error}
                  </span>
                ) : null}
                {t(`notifications.deliveryStatus.${row.status}`)}
                <span aria-hidden>·</span>
                {new Date(row.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SettingsSectionCard>
  );
}
