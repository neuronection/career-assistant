import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import { DesktopNotifications } from "@/components/DesktopNotifications";
import { ToastHost } from "@/components/ToastHost";
import {
  activateDesktop,
  registerNotifyHandler,
  withinQuietHours,
  type DesktopToast,
} from "@/lib/desktop";
import { useToastStore } from "@/stores/toastStore";

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchNotificationPreferences: vi.fn(),
    updateNotificationPreferences: vi.fn(),
  };
});

import { fetchNotificationPreferences } from "@/api/engagement";
const mockPrefs = vi.mocked(fetchNotificationPreferences);

type ShellApi = {
  ready: ReturnType<typeof vi.fn>;
  activate: ReturnType<typeof vi.fn>;
  desktop_settings: ReturnType<typeof vi.fn>;
  set_close_to_tray: ReturnType<typeof vi.fn>;
  set_autostart: ReturnType<typeof vi.fn>;
};

function installShellApi(): ShellApi {
  const api: ShellApi = {
    ready: vi.fn().mockReturnValue(true),
    activate: vi.fn().mockReturnValue(true),
    desktop_settings: vi
      .fn()
      .mockReturnValue({ close_to_tray: true, autostart: false }),
    set_close_to_tray: vi.fn().mockReturnValue(true),
    set_autostart: vi.fn().mockReturnValue(true),
  };
  (window as unknown as { pywebview?: { api: ShellApi } }).pywebview = { api };
  return api;
}

function pushToast(toast: Partial<DesktopToast>): void {
  window.__caDesktopBridge?.onNotify({
    title: "Strong fit",
    body: "QA Engineer at 8/10",
    kind: "fit_threshold",
    severity: "info",
    link: "/jobs/qa-engineer",
    ...toast,
  });
}

beforeEach(() => {
  useToastStore.setState({ toasts: [], push: useToastStore.getState().push });
  mockPrefs.mockResolvedValue({ desktop_channel_enabled: true, quiet_hours: null });
});

afterEach(() => {
  delete (window as unknown as { pywebview?: unknown }).pywebview;
  delete window.__caDesktopBridge;
  vi.restoreAllMocks();
});

describe("desktop bridge contract", () => {
  it("announces ready and navigates on toast click-through", async () => {
    const api = installShellApi();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <DesktopNotifications />
                <ToastHost />
              </>
            }
          />
          <Route path="*" element={<div>landed</div>} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => expect(api.ready).toHaveBeenCalled());

    pushToast({});
    // Native Notification API does not exist in jsdom → in-app fallback
    const toast = await screen.findByTestId("toast-host");
    expect(toast).toBeInTheDocument();

    fireEvent.click(screen.getByTestId(/^toast-\d+$/));
    await waitFor(() => expect(api.activate).toHaveBeenCalledWith("/jobs/qa-engineer"));
    expect(await screen.findByText("landed")).toBeInTheDocument();
  });

  it("falls back to in-app toasts when the OS path is unavailable", async () => {
    installShellApi();
    render(
      <MemoryRouter>
        <DesktopNotifications />
        <ToastHost />
      </MemoryRouter>
    );
    pushToast({});
    expect(await screen.findByTestId("toast-host")).toBeInTheDocument();
  });

  it("suppresses toasts when the desktop channel is disabled", async () => {
    installShellApi();
    mockPrefs.mockResolvedValue({
      desktop_channel_enabled: false,
      quiet_hours: null,
    });
    render(
      <MemoryRouter>
        <DesktopNotifications />
        <ToastHost />
      </MemoryRouter>
    );
    await waitFor(() => expect(mockPrefs).toHaveBeenCalled());
    pushToast({});
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("toast-host")).not.toBeInTheDocument();
  });

  it("suppresses toasts during quiet hours (client-side guard)", async () => {
    installShellApi();
    mockPrefs.mockResolvedValue({
      desktop_channel_enabled: true,
      quiet_hours: { start: "00:00", end: "23:59" },
    });
    render(
      <MemoryRouter>
        <DesktopNotifications />
        <ToastHost />
      </MemoryRouter>
    );
    await waitFor(() => expect(mockPrefs).toHaveBeenCalled());
    pushToast({});
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("toast-host")).not.toBeInTheDocument();
  });

  it("renders native notifications when the API is granted", async () => {
    installShellApi();
    const instances: Array<{
      onclick: (() => void) | null;
      close: ReturnType<typeof vi.fn>;
    }> = [];
    const nativeCtor = function (this: unknown, _title: string) {
      const instance = { onclick: null as (() => void) | null, close: vi.fn() };
      instances.push(instance);
      return instance;
    } as unknown as { permission: string };
    nativeCtor.permission = "granted";
    (window as unknown as { Notification: unknown }).Notification = nativeCtor;

    render(
      <MemoryRouter>
        <DesktopNotifications />
        <ToastHost />
      </MemoryRouter>
    );
    pushToast({ title: "Native ping" });
    await waitFor(() => {
      expect(instances).toHaveLength(1);
      expect(instances[0].onclick).not.toBeNull();
    });
    // single surface: no in-app preview alongside the native toast
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("toast-host")).not.toBeInTheDocument();
  });

  it("hosts the first-run close-to-tray prompt and stores the answer", async () => {
    const api = installShellApi();
    api.desktop_settings.mockReturnValue({ close_to_tray: null, autostart: false });
    render(
      <MemoryRouter>
        <DesktopNotifications />
      </MemoryRouter>
    );
    const prompt = await screen.findByTestId("close-to-tray-prompt");
    expect(prompt).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("close-to-tray-yes"));
    await waitFor(() => expect(api.set_close_to_tray).toHaveBeenCalledWith(true));
    expect(screen.queryByTestId("close-to-tray-prompt")).not.toBeInTheDocument();
  });

  it("shows no prompt when the user already chose", async () => {
    installShellApi();
    render(
      <MemoryRouter>
        <DesktopNotifications />
      </MemoryRouter>
    );
    await waitFor(() => expect(mockPrefs).toHaveBeenCalled());
    expect(screen.queryByTestId("close-to-tray-prompt")).not.toBeInTheDocument();
  });
});

describe("ToastHost", () => {
  it("renders pushed toasts and dismisses without marking anything", async () => {
    const { push } = useToastStore.getState();
    render(
      <MemoryRouter>
        <ToastHost />
      </MemoryRouter>
    );
    push({ title: "T1", body: "B1", severity: "warning", link: "/jobs/x" });
    expect(await screen.findByText("T1")).toBeInTheDocument();
    expect(screen.getByTestId("toast-host")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByTestId("toast-host")).not.toBeInTheDocument();
  });
});

describe("quiet-hours math + handler registry", () => {
  it("mirrors the server-side window logic", () => {
    const morning = new Date(2026, 7, 31, 6, 30);
    const noon = new Date(2026, 7, 31, 12, 0);
    expect(withinQuietHours({ start: "22:00", end: "07:00" }, morning)).toBe(true);
    expect(withinQuietHours({ start: "22:00", end: "07:00" }, noon)).toBe(false);
    expect(withinQuietHours({ start: "12:00", end: "13:00" }, noon)).toBe(true);
    expect(withinQuietHours(null, noon)).toBe(false);
    expect(withinQuietHours({ start: "bad", end: "07:00" }, noon)).toBe(false);
  });

  it("unregisters the push handler", () => {
    const unregister = registerNotifyHandler(() => undefined);
    expect(window.__caDesktopBridge).toBeDefined();
    unregister();
    expect(window.__caDesktopBridge).toBeUndefined();
  });

  it("activateDesktop degrades without a shell", async () => {
    await expect(activateDesktop("/jobs/x")).resolves.toBeUndefined();
  });
});
