import { describe, expect, it, vi, beforeEach } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import * as authApi from "@/api/auth";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...actual,
    login: vi.fn(),
    register: vi.fn(),
    fetchMe: vi.fn(),
    logout: actual.logout,
  };
});

const mocked = vi.mocked(authApi);

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null, user: null, loading: false });
    vi.clearAllMocks();
  });

  it("login stores user", async () => {
    mocked.login.mockResolvedValue("token-123");
    mocked.fetchMe.mockResolvedValue({ id: "1", email: "a@b.c", full_name: "A", is_active: true, is_admin: true });
    await useAuthStore.getState().login("a@b.c", "password123");
    expect(useAuthStore.getState().user?.email).toBe("a@b.c");
    expect(useAuthStore.getState().loading).toBe(false);
  });

  it("register stores user", async () => {
    mocked.register.mockResolvedValue("token-456");
    mocked.fetchMe.mockResolvedValue({ id: "2", email: "x@y.z", full_name: "", is_active: true, is_admin: false });
    await useAuthStore.getState().register("x@y.z", "password123");
    expect(useAuthStore.getState().user?.email).toBe("x@y.z");
  });

  it("loadUser clears token on 401", async () => {
    localStorage.setItem("career_token", "bad");
    useAuthStore.setState({ token: "bad" });
    mocked.fetchMe.mockRejectedValue(new Error("401"));
    await useAuthStore.getState().loadUser();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("logout clears state", () => {
    useAuthStore.setState({ token: "t", user: { id: "1", email: "e", full_name: "", is_active: true, is_admin: false } });
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });
});
