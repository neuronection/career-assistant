import { useEffect, useState } from "react";
import { BellOff, BellRing } from "lucide-react";
import {
  fetchPreferencesMatrix,
  fetchVapidPublicKey,
  setKindPreference,
  subscribePush,
  unsubscribePush,
  updateNotificationPreferences,
} from "@/api/engagement";
import { hasChannel } from "@/lib/desktop";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { PreferencesMatrix } from "@/types";

const DEVICE_ID = "web";

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

/** Plan-36 notification preferences: channels, browser push and the
 * per-kind matrix. Desktop-only controls render only when the mode
 * declares the channel (one build, capabilities declared). */
export function Notifications() {
  const bootstrap = useBootstrapStore((s) => s.bootstrap);
  const browserChannel = hasChannel(bootstrap?.notification_channels, "browser");
  const desktopChannel = hasChannel(bootstrap?.notification_channels, "desktop");
  const [matrix, setMatrix] = useState<PreferencesMatrix | null>(null);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    void fetchPreferencesMatrix()
      .then(setMatrix)
      .catch(() => setMatrix(null));
  };

  useEffect(() => {
    load();
    void currentSubscription().then((sub) => setPushEnabled(sub !== null));
  }, []);

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

  return (
    <div className="max-w-2xl space-y-6" data-testid="notifications-settings">
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <BellRing className="w-4 h-4" /> Channels
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Available in this mode: {matrix?.channels.join(", ") ?? "…"}
        </p>
        {desktopChannel && matrix && (
          <label className="mt-3 flex items-center justify-between text-sm text-slate-700">
            <span>Desktop toasts</span>
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
            <span>Quiet hours</span>
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
        {browserChannel && (
          <div className="mt-4 flex items-center justify-between" data-testid="browser-push">
            <div>
              <p className="text-sm text-slate-700">Browser notifications</p>
              <p className="text-xs text-slate-500">
                Push when the tab is closed (web push / VAPID).
              </p>
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
                  <BellOff className="w-3.5 h-3.5" /> Disable
                </>
              ) : (
                <>
                  <BellRing className="w-3.5 h-3.5" /> Enable
                </>
              )}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold text-slate-900">Notification kinds</h2>
        <p className="mt-1 text-xs text-slate-500">
          Choose what reaches your inbox. Per-kind channels follow the defaults
          unless overridden.
        </p>
        <div className="mt-3 divide-y divide-slate-100">
          {(matrix?.kinds ?? []).map((kind) => (
            <div key={kind.key} className="flex items-center justify-between py-2.5">
              <div>
                <p className="text-sm text-slate-800">{kind.label}</p>
                <p className="text-xs text-slate-400">
                  {kind.group}
                  {kind.mutable ? "" : " · always on"}
                </p>
              </div>
              {kind.mutable && (
                <input
                  type="checkbox"
                  aria-label={`Enable ${kind.label}`}
                  data-testid={`kind-${kind.key}`}
                  checked={kind.enabled}
                  onChange={(e) => toggleKind(kind.key, e.target.checked)}
                />
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
