import { act } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionGate } from "@/components/SessionGate";
import { UNAUTHENTICATED_EVENT } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import * as authApi from "@/api/auth";
import * as apiClient from "@/api/client";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return { ...actual, fetchMe: vi.fn(), login: vi.fn(), register: vi.fn(), logout: vi.fn() };
});

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    api: { post: vi.fn().mockResolvedValue({ status: 200 }), get: vi.fn() },
    tryRefreshSession: vi.fn().mockResolvedValue(false),
    hasShellToken: vi.fn(() => false),
  };
});

const USER = {
  id: "1",
  email: "a@b.c",
  full_name: "A",
  is_active: true,
  is_admin: false,
};

describe("SessionGate (shared AuthGate wiring)", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, loading: false, status: "checking", error: null });
    vi.clearAllMocks();
    vi.mocked(apiClient.hasShellToken).mockReturnValue(false);
    vi.mocked(apiClient.tryRefreshSession).mockResolvedValue(false);
  });

  it("renders children once the session boots", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(USER);
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <SessionGate>
          <div>secret content</div>
        </SessionGate>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("secret content")).toBeInTheDocument()
    );
  });

  it("shows the login screen when the boot lands anonymous", async () => {
    vi.mocked(authApi.fetchMe).mockRejectedValue(new Error("nope"));
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <SessionGate>
          <div>secret content</div>
        </SessionGate>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.queryByText("secret content")).not.toBeInTheDocument()
    );
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it("dropToLogin flips the gate back to the login surface without a boot round-trip", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(USER);
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <SessionGate>
          <div>secret content</div>
        </SessionGate>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText("secret content")).toBeInTheDocument());
    const callsAfterBoot = vi.mocked(authApi.fetchMe).mock.calls.length;

    act(() => {
      useAuthStore.getState().dropToLogin();
    });

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    // §12 self-service drop: no re-check hit the API
    expect(vi.mocked(authApi.fetchMe).mock.calls.length).toBe(callsAfterBoot);
  });

  it("re-runs the boot flow when a mid-session 401 dispatches the unauthenticated event", async () => {
    vi.mocked(authApi.fetchMe).mockResolvedValue(USER);
    render(
      <MemoryRouter initialEntries={["/private"]}>
        <SessionGate>
          <div>secret content</div>
        </SessionGate>
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByText("secret content")).toBeInTheDocument());

    vi.mocked(authApi.fetchMe).mockRejectedValue(new Error("session dead"));
    act(() => {
      window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    });

    await waitFor(() =>
      expect(screen.queryByText("secret content")).not.toBeInTheDocument()
    );
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(vi.mocked(authApi.fetchMe).mock.calls.length).toBeGreaterThan(1);
  });
});
