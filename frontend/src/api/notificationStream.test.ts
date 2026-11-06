import { afterEach, describe, expect, it, vi } from "vitest";

const encoder = new TextEncoder();

async function loadStream() {
  vi.resetModules();
  const client = await import("@/api/client");
  client.setActiveProfile("profile-1");
  return await import("@/api/notificationStream");
}

describe("streamNotifications", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("binds the active profile on the SSE request", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode('event: unread\ndata: {"unread_count":3}\n\n'),
        );
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { streamNotifications } = await loadStream();
    const controller = new AbortController();
    const events: unknown[] = [];
    await streamNotifications((event) => {
      events.push(event);
      controller.abort();
    }, controller.signal);

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Profile-Id"]).toBe("profile-1");
    expect(events).toEqual([{ event: "unread", data: { unread_count: 3 } }]);
  });
});
