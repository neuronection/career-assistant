import { describe, expect, it, vi, beforeEach } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import * as authApi from "@/api/auth";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
  };
});

const mocked = vi.mocked(authApi);

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, loading: false, error: null });
    vi.clearAllMocks();
  });

  it("loadUser stores the default user", async () => {
    mocked.fetchMe.mockResolvedValue({ id: "1", email: "a@b.c", full_name: "A", is_active: true, is_admin: true });
    await useAuthStore.getState().loadUser();
    expect(useAuthStore.getState().user?.email).toBe("a@b.c");
    expect(useAuthStore.getState().loading).toBe(false);
    expect(useAuthStore.getState().error).toBeNull();
  });

  it("loadUser records an error on failure", async () => {
    mocked.fetchMe.mockRejectedValue(new Error("boom"));
    await useAuthStore.getState().loadUser();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().error).toBe("not-authenticated");
  });

  it("reset clears user state", () => {
    useAuthStore.setState({ user: { id: "1", email: "e", full_name: "", is_active: true, is_admin: false } });
    useAuthStore.getState().reset();
    expect(useAuthStore.getState().user).toBeNull();
  });
});
