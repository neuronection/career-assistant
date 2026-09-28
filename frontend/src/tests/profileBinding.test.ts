import { describe, expect, it, vi, beforeEach } from "vitest";
import type { InternalAxiosRequestConfig } from "axios";

/** §15 client binding: every domain call carries `X-Profile-Id`, the
 * remembered id survives reloads, and the first domain call bootstraps
 * the active profile (stored → Default) before it goes out. */

type Seen = { url: string; header: string | undefined };

function installAdapter(mod: typeof import("@/api/client"), seen: Seen[]) {
  mod.api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const url = String(config.url ?? "");
    seen.push({ url, header: config.headers.get("X-Profile-Id") as string | undefined });
    const data =
      url === "/profiles"
        ? [
            { id: "p-default", name: "Default", color: null, is_default: true },
            { id: "p-second", name: "Second", color: null, is_default: false },
          ]
        : { ok: true };
    return { data, status: 200, statusText: "OK", headers: {}, config };
  };
}

async function freshClient() {
  vi.resetModules();
  return import("@/api/client");
}

describe("profile binding on the API client", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("attaches X-Profile-Id from setActiveProfile", async () => {
    const mod = await freshClient();
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    mod.setActiveProfile("p-second");
    await mod.api.get("/matching/rankings");
    expect(seen).toEqual([{ url: "/matching/rankings", header: "p-second" }]);
  });

  it("never overwrites a header set on the request", async () => {
    const mod = await freshClient();
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    mod.setActiveProfile("p-second");
    await mod.api.get("/profile", { headers: { "X-Profile-Id": "p-default" } });
    expect(seen[0].header).toBe("p-default");
  });

  it("restores the remembered profile from localStorage (ca-profile-id)", async () => {
    localStorage.setItem("ca-profile-id", "p-second");
    const mod = await freshClient();
    expect(mod.getActiveProfile()).toBe("p-second");
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    await mod.api.get("/profile");
    expect(seen).toEqual([{ url: "/profile", header: "p-second" }]);
  });

  it("persists and forgets the last-used profile", async () => {
    const mod = await freshClient();
    mod.persistActiveProfile("p-second");
    expect(localStorage.getItem("ca-profile-id")).toBe("p-second");
    mod.persistActiveProfile(null);
    expect(localStorage.getItem("ca-profile-id")).toBeNull();
  });

  it("primes the active profile (Default fallback) before the first domain call", async () => {
    const mod = await freshClient();
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    await mod.api.get("/me/bootstrap");
    expect(seen.map((entry) => entry.url)).toEqual(["/profiles", "/me/bootstrap"]);
    expect(seen[1].header).toBe("p-default");
    expect(mod.getActiveProfile()).toBe("p-default");
  });

  it("deduplicates the prime across concurrent first calls", async () => {
    const mod = await freshClient();
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    await Promise.all([mod.api.get("/profile"), mod.api.get("/chat/sessions")]);
    expect(seen.filter((entry) => entry.url === "/profiles")).toHaveLength(1);
    expect(seen.filter((entry) => entry.url !== "/profiles").map((e) => e.header)).toEqual([
      "p-default",
      "p-default",
    ]);
  });

  it("does not prime during auth flows — login stays header-less", async () => {
    const mod = await freshClient();
    const seen: Seen[] = [];
    installAdapter(mod, seen);
    await mod.api.post("/auth/login", { email: "a@b.c", password: "x" });
    expect(seen).toEqual([{ url: "/auth/login", header: undefined }]);
  });

  it("falls through honestly when the profiles fetch fails", async () => {
    const mod = await freshClient();
    mod.api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      if (String(config.url) === "/profiles") {
        return { data: { detail: "boom" }, status: 500, statusText: "ERR", headers: {}, config };
      }
      return {
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config: {
          ...config,
          headers: config.headers,
          // domain call goes out without a header instead of hanging
        },
      };
    };
    const response = await mod.api.get("/profile");
    expect(response.status).toBe(200);
    expect(mod.getActiveProfile()).toBeNull();
  });
});
