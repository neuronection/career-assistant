import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Check, X } from "lucide-react";
import {
  dismissNotifications,
  fetchNotificationPreferences,
  fetchNotifications,
  fetchRules,
  markNotificationsRead,
  notificationLink,
  updateNotificationPreferences,
  updateRule,
} from "@/api/engagement";
import { hasChannel } from "@/lib/desktop";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useNotificationStream } from "@/hooks/useNotificationStream";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import type {
  AlertRule,
  NotificationItem,
  NotificationPreferences,
} from "@/types";

export function NotificationBell() {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const bootstrap = useBootstrapStore((s) => s.bootstrap);
  const desktopChannel = hasChannel(bootstrap?.notification_channels, "desktop");
  const { unreadCount: unread, refresh } = useNotificationStream();

  const load = () => {
    void fetchNotifications({ limit: 20 })
      .then((r) => {
        setItems(r.items);
        void refresh();
      })
      .catch(() => {
        setItems([]);
      });
  };

  useEffect(() => {
    load();
    void fetchRules().then((r) => setRules(r.items)).catch(() => setRules([]));
    if (desktopChannel) {
      void fetchNotificationPreferences()
        .then(setPrefs)
        .catch(() => setPrefs(null));
    }
  }, [desktopChannel]);

  useEffect(() => {
    if (open) load();
  }, [open]);

  const openItem = (item: NotificationItem) => {
    const wasUnread = item.status === "unread";
    void markNotificationsRead([item.id]).then(() => {
      if (wasUnread) void refresh();
      setItems((prev) =>
        prev.map((x) =>
          x.id === item.id ? { ...x, status: "read", read_at: new Date().toISOString() } : x
        )
      );
      const link = notificationLink(item);
      if (link) {
        setOpen(false);
        navigate(link);
      }
    });
  };

  const dismissItem = (item: NotificationItem) => {
    void dismissNotifications([item.id]).then(() => {
      setItems((prev) => prev.filter((x) => x.id !== item.id));
      void refresh();
    });
  };

  const markAll = () => {
    void markNotificationsRead([]).then(() => {
      setItems((prev) =>
        prev.map((x) =>
          x.status === "unread"
            ? { ...x, status: "read", read_at: new Date().toISOString() }
            : x
        )
      );
      void refresh();
    });
  };

  const saveRule = (rule: AlertRule, patch: Partial<AlertRule>) => {
    const next = { ...rule, ...patch };
    void updateRule({
      kind: next.kind,
      params: next.params,
      enabled: next.enabled,
    })
      .then((r) => setRules(r.items))
      .catch(() => undefined);
  };

  const fitRule = rules.find((r) => r.kind === "fit_threshold");

  const savePrefs = (patch: Partial<NotificationPreferences>) => {
    const merged = {
      desktop_channel_enabled: prefs?.desktop_channel_enabled ?? true,
      quiet_hours: prefs?.quiet_hours ?? null,
      ...patch,
    };
    const hours = merged.quiet_hours;
    const next: NotificationPreferences = {
      ...merged,
      quiet_hours:
        hours && hours.start && hours.end ? { start: hours.start, end: hours.end } : null,
    };
    setPrefs(next);
    void updateNotificationPreferences(next)
      .then(setPrefs)
      .catch(() => undefined);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Notifications"
          data-testid="notification-bell"
          className="relative p-2 rounded-lg text-slate-600 hover:bg-slate-100"
        >
          <Bell className="w-4 h-4" />
          {unread > 0 && (
            <span
              data-testid="notification-badge"
              className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 rounded-full bg-rose-500 text-white text-[10px] flex items-center justify-center"
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <span className="font-medium text-sm text-slate-900">Notifications</span>
          <button
            onClick={markAll}
            className="text-xs text-primary-700 hover:underline flex items-center gap-1"
            data-testid="mark-all-read"
          >
            <Check className="w-3 h-3" /> Mark all read
          </button>
        </div>
        <div className="max-h-72 overflow-y-auto" data-testid="notification-list">
          {items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-400 text-center">
              Nothing yet — fit alerts land here.
            </p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`flex items-start gap-1 border-b border-slate-50 ${
                  item.status === "read" || item.status === "dismissed"
                    ? "opacity-60"
                    : ""
                }`}
              >
                <button
                  onClick={() => openItem(item)}
                  className="flex-1 w-full text-left px-4 py-3 hover:bg-slate-50"
                  data-testid="notification-item"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-900">{item.title}</span>
                    {item.status === "unread" && (
                      <span className="w-2 h-2 rounded-full bg-primary-500 shrink-0" />
                    )}
                  </div>
                  {item.body && (
                    <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{item.body}</p>
                  )}
                </button>
                <button
                  type="button"
                  aria-label="Dismiss notification"
                  data-testid="notification-dismiss"
                  onClick={() => dismissItem(item)}
                  className="p-2 mr-1 mt-2 rounded text-slate-300 hover:text-slate-500 hover:bg-slate-100"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
        {desktopChannel && prefs && (
          <div
            className="px-4 py-3 border-t border-slate-100 bg-slate-50"
            data-testid="desktop-prefs"
          >
            <label className="flex items-center justify-between text-xs text-slate-600">
              <span>Desktop toasts</span>
              <input
                type="checkbox"
                checked={prefs.desktop_channel_enabled}
                onChange={(e) =>
                  savePrefs({ desktop_channel_enabled: e.target.checked })
                }
                data-testid="desktop-channel-enabled"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-slate-600 mt-2">
              <span>Quiet from</span>
              <input
                type="time"
                value={prefs.quiet_hours?.start ?? ""}
                onChange={(e) =>
                  savePrefs({
                    quiet_hours: {
                      start: e.target.value,
                      end: prefs.quiet_hours?.end ?? "23:59",
                    },
                  })
                }
                className="ml-2 text-xs border border-slate-200 rounded px-1"
                data-testid="quiet-hours-start"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-slate-600 mt-2">
              <span>Quiet until</span>
              <input
                type="time"
                value={prefs.quiet_hours?.end ?? ""}
                onChange={(e) =>
                  savePrefs({
                    quiet_hours: {
                      start: prefs.quiet_hours?.start ?? "22:00",
                      end: e.target.value,
                    },
                  })
                }
                className="ml-2 text-xs border border-slate-200 rounded px-1"
                data-testid="quiet-hours-end"
              />
            </label>
          </div>
        )}
        {fitRule && (
          <div className="px-4 py-3 border-t border-slate-100 bg-slate-50 rounded-b-lg">
            <label className="flex items-center justify-between text-xs text-slate-600">
              <span>Fit alerts</span>
              <input
                type="checkbox"
                checked={fitRule.enabled}
                onChange={(e) => saveRule(fitRule, { enabled: e.target.checked })}
                data-testid="fit-rule-enabled"
              />
            </label>
            <label className="flex items-center justify-between text-xs text-slate-600 mt-2">
              <span>Notify from fit {Number(fitRule.params.min_fit).toFixed(0)}/10</span>
              <input
                type="range"
                min={0}
                max={10}
                step={0.5}
                value={fitRule.params.min_fit}
                onChange={(e) =>
                  saveRule(fitRule, {
                    params: { ...fitRule.params, min_fit: Number(e.target.value) },
                  })
                }
                className="w-32 accent-primary-600"
                data-testid="fit-rule-threshold"
              />
            </label>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
