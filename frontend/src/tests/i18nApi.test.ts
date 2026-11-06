import { beforeEach, describe, expect, test, vi } from "vitest";

import { api } from "@/api/client";
import {
  approveOverlay,
  draftOverlays,
  fetchInstanceLocale,
  fetchLocale,
  fetchOverlayQueue,
  rejectOverlay,
  setInstanceLocale,
  setMyLocale,
  updateOverlay,
} from "@/api/i18n";

const calls: { method: string; url: string; body?: unknown }[] = [];

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn(async (url: string) => {
      calls.push({ method: "get", url });
      return { data: { locale: "de", supported: ["en", "de", "el"] } };
    }),
    put: vi.fn(async (url: string, body: unknown) => {
      calls.push({ method: "put", url, body });
      return { data: { locale: "de", supported: ["en", "de", "el"] } };
    }),
    post: vi.fn(async (url: string, body?: unknown) => {
      calls.push({ method: "post", url, body });
      return { data: { id: "x", status: "approved", locale: "de", drafted: {} } };
    }),
    patch: vi.fn(async (url: string, body: unknown) => {
      calls.push({ method: "patch", url, body });
      return { data: { id: "x", value: "v" } };
    }),
  },
}));

beforeEach(() => {
  calls.length = 0;
  vi.clearAllMocks();
});

describe("i18n api client", () => {
  test("locale calls hit the personal and admin endpoints", async () => {
    expect((await fetchLocale()).locale).toBe("de");
    expect((await setMyLocale("de")).locale).toBe("de");
    expect((await fetchInstanceLocale()).locale).toBe("de");
    expect((await setInstanceLocale("el")).locale).toBe("de");
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      "get /me/locale",
      "put /me/locale",
      "get /admin/i18n/locale",
      "put /admin/i18n/locale",
    ]);
  });

  test("overlay calls hit the review endpoints", async () => {
    await fetchOverlayQueue();
    await fetchOverlayQueue("de");
    await draftOverlays("de");
    await updateOverlay("x", "value");
    await approveOverlay("x");
    await rejectOverlay("x");
    // The review board's single bounded page: locale/status filters
    // omitted (empty = all) and the endpoint's max page size.
    expect(api.get).toHaveBeenCalledWith("/admin/i18n/overlays", {
      params: { locale: "de", status: "", limit: 500 },
    });
    expect(api.get).toHaveBeenCalledWith("/admin/i18n/overlays", {
      params: { locale: "", status: "", limit: 500 },
    });
    expect(api.post).toHaveBeenCalledWith("/admin/i18n/overlays/draft", {
      locale: "de",
      entity_kinds: ["job", "skill", "family"],
      limit: 20,
    });
    expect(api.patch).toHaveBeenCalledWith("/admin/i18n/overlays/x", { value: "value" });
    expect(api.post).toHaveBeenCalledWith("/admin/i18n/overlays/x/approve");
    expect(api.post).toHaveBeenCalledWith("/admin/i18n/overlays/x/reject");
  });
});
