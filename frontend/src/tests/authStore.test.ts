import { describe, expect, it, vi, beforeEach } from "vitest";
import { AxiosError } from "axios";
import { useAuthStore } from "@/stores/authStore";
import * as authApi from "@/api/auth";
import * as apiClient from "@/api/client";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  };
});

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return {
    ...actual,
    api: { post: vi.fn().mockResolvedValue({ status: 200 }), get: vi.fn() },
    tryRefreshSession: vi.fn(),
    hasShellToken: vi.fn(() => false),
  };
});

const mocked = vi.mocked(authApi);
const mockedClient = vi.mocked(apiClient);

const USER = {
  id: "1",
  email: "a@b.c",
  full_name: "A",
  is_active: true,
  is_admin: true,
};

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, loading: false, status: "checking", error: null });
    vi.clearAllMocks();
    mockedClient.hasShellToken.mockReturnValue(false);
    mockedClient.tryRefreshSession.mockResolvedValue(false);
  });

  it("loadUser stores the user", async () => {
    mocked.fetchMe.mockResolvedValue(USER);
    const ok = await useAuthStore.getState().loadUser();
    expect(ok).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe("a@b.c");
    expect(useAuthStore.getState().loading).toBe(false);
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(useAuthStore.getState().error).toBeNull();
  });

  it("loadUser records an error on failure", async () => {
    mocked.fetchMe.mockRejectedValue(new Error("boom"));
    const ok = await useAuthStore.getState().loadUser();
    expect(ok).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().error).toBe("not-authenticated");
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("boot accepts a live session cookie", async () => {
    mocked.fetchMe.mockResolvedValue(USER);
    expect(await useAuthStore.getState().boot()).toBe(true);
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(mockedClient.tryRefreshSession).not.toHaveBeenCalled();
  });

  it("boot rotates an expired session via the refresh cookie", async () => {
    mocked.fetchMe
      .mockRejectedValueOnce(new Error("expired"))
      .mockResolvedValueOnce(USER);
    mockedClient.tryRefreshSession.mockResolvedValue(true);
    expect(await useAuthStore.getState().boot()).toBe(true);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("boot lands anonymous without any session", async () => {
    mocked.fetchMe.mockRejectedValue(new Error("nope"));
    expect(await useAuthStore.getState().boot()).toBe(false);
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("boot exchanges the desktop shell secret (DIM)", async () => {
    mockedClient.hasShellToken.mockReturnValue(true);
    mocked.fetchMe
      .mockRejectedValueOnce(new Error("anon"))
      .mockResolvedValueOnce(USER);
    expect(await useAuthStore.getState().boot()).toBe(true);
    expect(mocked.fetchMe).toHaveBeenCalledTimes(2);
    expect(apiClient.api.post).toHaveBeenCalledWith("/auth/desktop/exchange");
  });

  it("boot exchanges without a shell token (shell-less dev, ADR-0023)", async () => {
    mockedClient.hasShellToken.mockReturnValue(false);
    mocked.fetchMe
      .mockRejectedValueOnce(new Error("anon"))
      .mockResolvedValueOnce(USER);
    expect(await useAuthStore.getState().boot()).toBe(true);
    expect(apiClient.api.post).toHaveBeenCalledWith("/auth/desktop/exchange");
  });

  it("login and register set the user; logout clears it", async () => {
    mocked.login.mockResolvedValue(USER);
    expect(await useAuthStore.getState().login("a@b.c", "pw")).toBe(true);
    expect(useAuthStore.getState().status).toBe("authenticated");

    mocked.logout.mockResolvedValue(undefined);
    await useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("register reports ok / disabled / failed outcomes", async () => {
    mocked.register.mockResolvedValue(USER);
    expect(await useAuthStore.getState().register("a@b.c", "pw", "A")).toBe("ok");
    expect(useAuthStore.getState().status).toBe("authenticated");

    useAuthStore.setState({ user: null, loading: false, status: "anonymous", error: null });
    const forbidden = new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
      status: 403,
      statusText: "Forbidden",
      data: { detail: "Registration is disabled" },
      headers: {},
      config: {},
    } as never);
    mocked.register.mockRejectedValue(forbidden);
    expect(await useAuthStore.getState().register("a@b.c", "pw")).toBe("disabled");

    useAuthStore.setState({ user: null, loading: false, status: "anonymous", error: null });
    mocked.register.mockRejectedValue(new Error("boom"));
    expect(await useAuthStore.getState().register("a@b.c", "pw")).toBe("failed");
    expect(useAuthStore.getState().status).toBe("anonymous");
  });

  it("dropToLogin lands anonymous without an API call", async () => {
    useAuthStore.setState({
      user: { ...USER },
      loading: false,
      status: "authenticated",
      error: null,
    });
    useAuthStore.getState().dropToLogin();
    expect(useAuthStore.getState().status).toBe("anonymous");
    expect(useAuthStore.getState().user).toBeNull();
    expect(mocked.logout).not.toHaveBeenCalled();
  });

  it("reset clears user state", () => {
    useAuthStore.setState({ user: { ...USER } });
    useAuthStore.getState().reset();
    expect(useAuthStore.getState().user).toBeNull();
  });
});
