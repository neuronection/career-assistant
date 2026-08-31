import type { NotificationChannel } from "@/types";

/**
 * Desktop shell bridge (Phase 30): the pywebview `js_api` object and the
 * backend→SPA push contract. Web mode never has `window.pywebview`, so
 * every helper degrades to a no-op there.
 */

export interface DesktopToast {
  title: string;
  body: string;
  kind: string;
  severity: string;
  link: string;
}

export interface DesktopShellSettings {
  close_to_tray: boolean | null;
  autostart: boolean;
}

interface DesktopBridgeApi {
  ready(): boolean;
  activate(link?: string): boolean;
  desktop_settings(): DesktopShellSettings;
  set_close_to_tray(value: boolean): boolean;
  set_autostart(value: boolean): boolean;
}

interface PywebviewHost {
  api?: DesktopBridgeApi;
}

declare global {
  interface Window {
    pywebview?: PywebviewHost;
    __caDesktopBridge?: { onNotify: (toast: DesktopToast) => void };
  }
}

export function isDesktop(): boolean {
  return typeof window !== "undefined" && !!window.pywebview?.api;
}

export function desktopApi(): DesktopBridgeApi | null {
  return window.pywebview?.api ?? null;
}

/** Register the backend push handler; returns the unregister function. */
export function registerNotifyHandler(
  handler: (toast: DesktopToast) => void
): () => void {
  window.__caDesktopBridge = { onNotify: handler };
  return () => {
    delete window.__caDesktopBridge;
  };
}

/**
 * Toast click-through contract: the shell shows/unhides + focuses the
 * window; the caller then navigates to `link` via the router.
 */
export async function activateDesktop(link: string): Promise<void> {
  const api = desktopApi();
  if (!api) return;
  try {
    await api.activate(link);
  } catch {
    // focus is best-effort; navigation still happens
  }
}

export async function fetchShellSettings(): Promise<DesktopShellSettings | null> {
  const api = desktopApi();
  if (!api) return null;
  try {
    return await api.desktop_settings();
  } catch {
    return null;
  }
}

export async function setCloseToTray(value: boolean): Promise<void> {
  const api = desktopApi();
  if (!api) return;
  try {
    await api.set_close_to_tray(value);
  } catch {
    // shell may already be shutting down
  }
}

/** Channel capability declared by the bootstrap payload (plan 25 pattern). */
export function hasChannel(
  channels: NotificationChannel[] | undefined,
  channel: NotificationChannel
): boolean {
  return Array.isArray(channels) && channels.includes(channel);
}

/** Quiet-hours window check (mirrors the server-side dispatch guard). */
export function withinQuietHours(
  quiet: { start: string; end: string } | null | undefined,
  now: Date = new Date()
): boolean {
  if (!quiet) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  const parse = (value: string): number | null => {
    const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value ?? "");
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  };
  const start = parse(quiet.start);
  const end = parse(quiet.end);
  if (start === null || end === null) return false;
  if (start <= end) return minutes >= start && minutes <= end;
  return minutes >= start || minutes <= end;
}
