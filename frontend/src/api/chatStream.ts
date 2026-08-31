import { TOKEN_KEY } from "./client";

export interface ChatStreamCallbacks {
  onStatus?: (stage: string, found?: number) => void;
  /** Receives the accumulated assistant text so far. */
  onDelta?: (accumulated: string) => void;
  onMeta?: (meta: { message_id: string; referenced_job_codes: string[] }) => void;
}

interface SseBlock {
  event: string;
  data: string;
}

function parseBlocks(buffer: string): SseBlock[] {
  return buffer
    .split("\n\n")
    .filter((block) => block.trim().length > 0)
    .map((block) => {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      return { event, data };
    });
}

/** POST a chat message and consume its SSE stream (fetch-based; no
 * EventSource because SSE-over-POST isn't supported there). */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  const response = await fetch(
    `/api/v1/chat/sessions/${sessionId}/messages?stream=true`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content }),
      signal,
    },
  );
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `Chat failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let accumulated = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of parseBlocks(blocks.join("\n\n"))) {
      const payload = block.data ? JSON.parse(block.data) : {};
      if (block.event === "status") {
        callbacks.onStatus?.(payload.stage ?? "thinking…", payload.found);
      } else if (block.event === "delta") {
        accumulated += payload.text ?? "";
        callbacks.onDelta?.(accumulated);
      } else if (block.event === "meta") {
        callbacks.onMeta?.({
          message_id: payload.message_id,
          referenced_job_codes: payload.referenced_job_codes ?? [],
        });
      } else if (block.event === "error") {
        throw new Error(payload.detail ?? "AI error");
      } else if (block.event === "done") {
        return;
      }
    }
  }
}
