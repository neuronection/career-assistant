import { TOKEN_KEY } from "./client";

export type NotificationStreamEvent =
  | { event: "notification"; data: Record<string, unknown> }
  | { event: "unread"; data: { unread_count: number } };

interface SseBlock {
  event: string;
  data: string;
  id: string | null;
}

function parseBlocks(buffer: string): SseBlock[] {
  return buffer
    .split("\n\n")
    .filter((block) => block.trim().length > 0)
    .map((block) => {
      let event = "message";
      let data = "";
      let id: string | null = null;
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
        else if (line.startsWith("id: ")) id = line.slice(4);
      }
      return { event, data, id };
    });
}

function parseStreamEvent(block: SseBlock): NotificationStreamEvent | null {
  if (block.event === "unread") {
    return { event: "unread", data: { unread_count: Number(block.data ? JSON.parse(block.data).unread_count : 0) } };
  }
  if (block.event === "notification") {
    return {
      event: "notification",
      data: block.data ? JSON.parse(block.data) : {},
    };
  }
  return null;
}

/** Consume the plan-36 notification SSE stream (GET, fetch-based: the
 * endpoint needs the bearer header, which native EventSource cannot send).
 * Reconnect with `last-event-id` on drop; backoff is linear up to 30s. */
export async function streamNotifications(
  onEvent: (event: NotificationStreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let lastEventId = "";
  let backoff = 1000;
  while (!signal.aborted) {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch("/api/v1/notifications/stream", {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(lastEventId ? { "Last-Event-Id": lastEventId } : {}),
        },
        signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`stream unavailable (${response.status})`);
      }
      backoff = 1000;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of parseBlocks(blocks.join("\n\n"))) {
          if (block.id) lastEventId = block.id;
          const parsed = parseStreamEvent(block);
          if (parsed) onEvent(parsed);
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof TypeError) {
        // Network layer gone (server restart) — retry after backoff.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, backoff));
    backoff = Math.min(backoff * 2, 30000);
  }
}
