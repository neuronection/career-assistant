import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MonitorDown } from "lucide-react";

import { fetchNotificationPreferences } from "@/api/engagement";
import {
  activateDesktop,
  desktopApi,
  fetchShellSettings,
  isDesktop,
  registerNotifyHandler,
  setCloseToTray,
  withinQuietHours,
  type DesktopToast,
} from "@/lib/desktop";
import { useToastStore } from "@/stores/toastStore";

interface NotificationCtor {
  new (title: string, options?: { body?: string }): {
    onclick: (() => void) | null;
    close(): void;
  };
  requestPermission(): Promise<unknown>;
}

function notificationCtor(): NotificationCtor | null {
  if (typeof window === "undefined") return null;
  if ("Notification" in window) {
    return (window as unknown as { Notification: NotificationCtor }).Notification;
  }
  return null;
}

/**
 * SPA side of the desktop bridge (plan 36's desktop scenario):
 * - announces the page as ready (flushes queued boot catch-up toasts),
 * - renders pushed events as OS-native notifications via the Web
 *   Notification API, falling back to in-app toasts,
 * - enforces quiet hours client-side too (the dispatcher already did
 *   server-side),
 * - suppresses in-app previews while the OS path works (single surface);
 *   the inbox always keeps the event either way,
 * - hosts the first-run close-to-tray opt-in prompt.
 */
export function DesktopNotifications() {
  const navigate = useNavigate();
  const pushToast = useToastStore((s) => s.push);
  const [promptOpen, setPromptOpen] = useState(false);

  useEffect(() => {
    if (!isDesktop()) return;

    let prefs: { desktop_channel_enabled: boolean; quiet_hours: { start: string; end: string } | null } | null =
      null;
    let nativeReady = false;

    const loadPrefs = async () => {
      try {
        prefs = await fetchNotificationPreferences();
      } catch {
        prefs = { desktop_channel_enabled: true, quiet_hours: null };
      }
    };
    void loadPrefs();
    const prefsTimer = setInterval(loadPrefs, 60_000);

    const notify = (toast: DesktopToast) => {
      if (prefs && !prefs.desktop_channel_enabled) return; // channel off
      if (prefs && withinQuietHours(prefs.quiet_hours)) return; // client-side guard

      const ctor = notificationCtor();
      if (ctor && Notification.permission === "granted") {
        const native = new ctor(toast.title, { body: toast.body });
        native.onclick = () => {
          native.close();
          void activateDesktop(toast.link);
          if (toast.link) navigate(toast.link);
        };
        return; // single surface: no in-app preview alongside
      }
      if (ctor && !nativeReady && Notification.permission === "default") {
        void Notification.requestPermission().then((result) => {
          nativeReady = result === "granted";
          if (nativeReady) notify(toast);
        });
        return;
      }
      // OS toast unavailable (permission denied / no provider) → fallback
      pushToast({
        title: toast.title,
        body: toast.body,
        severity: toast.severity,
        link: toast.link,
      });
    };

    const unregister = registerNotifyHandler(notify);
    desktopApi()?.ready();

    void fetchShellSettings().then((settings) => {
      if (settings && settings.close_to_tray === null) setPromptOpen(true);
    });

    return () => {
      unregister();
      clearInterval(prefsTimer);
    };
  }, [navigate, pushToast]);

  if (!promptOpen || !isDesktop()) return null;

  const answer = (keepRunning: boolean) => {
    setPromptOpen(false);
    void setCloseToTray(keepRunning);
  };

  return (
    <div
      className="fixed bottom-4 left-4 z-50 w-96 bg-white border border-slate-200 rounded-lg shadow-lg p-4"
      data-testid="close-to-tray-prompt"
    >
      <div className="flex items-start gap-3">
        <MonitorDown className="w-5 h-5 text-primary-600 shrink-0 mt-0.5" />
        <div className="text-sm">
          <p className="font-medium text-slate-900">
            Keep working in the background?
          </p>
          <p className="text-slate-500 mt-1">
            When you close the window, Career Assistant can stay in the tray
            so scheduled searches, syncs and alerts continue.
          </p>
          <div className="flex gap-2 mt-3">
            <button
              type="button"
              data-testid="close-to-tray-yes"
              className="px-3 py-1.5 rounded-md bg-primary-600 text-white text-xs font-medium hover:bg-primary-700"
              onClick={() => answer(true)}
            >
              Run in background
            </button>
            <button
              type="button"
              data-testid="close-to-tray-no"
              className="px-3 py-1.5 rounded-md border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50"
              onClick={() => answer(false)}
            >
              No, quit on close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
