import type { ChatFlowEvent } from "@/lib/chatFlow";
import type { ChatTemplatePreview, ProfileProposalCardData } from "@/types";

export interface ChatCvAttachmentInput {
  kind: "cv";
  cv_id: string;
}

export interface ChatStreamCallbacks {
  /** Receives the accumulated assistant text so far. */
  onDelta?: (accumulated: string) => void;
  onMeta?: (meta: { message_id: string; referenced_job_codes: string[] }) => void;
  /** Family event vocabulary (ai-features §5). */
  onFlowEvent?: (event: ChatFlowEvent) => void;
  /**: the CV builder copilot's final full-state payload. */
  onBuilderState?: (state: Record<string, unknown>) => void;
  /**: one persisted HITL proposal card (plan 77). */
  onProposal?: (card: ProfileProposalCardData) => void;
  /**: one template first-page preview (plan 83). */
  onPreview?: (preview: ChatTemplatePreview) => void;
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

/** POST a chat turn and consume its SSE stream (fetch-based; no
 * EventSource because SSE-over-POST isn't supported there). Shared by
 * send / edit-branch / regenerate. */
export async function streamChatRequest(
  path: string,
  body: unknown,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal,
  });
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
      if (block.event === "delta") {
        accumulated += payload.text ?? "";
        callbacks.onDelta?.(accumulated);
      } else if (block.event === "meta") {
        callbacks.onMeta?.({
          message_id: payload.message_id,
          referenced_job_codes: payload.referenced_job_codes ?? [],
        });
      } else if (block.event === "builder_state") {
        callbacks.onBuilderState?.(payload);
      } else if (block.event === "proposal") {
        callbacks.onProposal?.(payload as ProfileProposalCardData);
      } else if (block.event === "preview") {
        callbacks.onPreview?.(payload as ChatTemplatePreview);
      } else if (
        block.event === "flow_started" ||
        block.event === "node_started" ||
        block.event === "node_finished" ||
        block.event === "tool_call" ||
        block.event === "flow_finished"
      ) {
        callbacks.onFlowEvent?.({
          event: block.event,
          payload,
        } as ChatFlowEvent);
      } else if (block.event === "flow_failed") {
        throw new Error(payload.message ?? "AI error");
      }
      // Unknown events are ignored — the stream is additive by contract.
    }
  }
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
  attachments: ChatCvAttachmentInput[] = [],
): Promise<void> {
  return streamChatRequest(
    `/api/v1/chat/sessions/${sessionId}/messages?stream=true`,
    { content, attachments },
    callbacks,
    signal,
  );
}

export async function streamChatEdit(
  messageId: string,
  content: string,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
  attachments: ChatCvAttachmentInput[] = [],
): Promise<void> {
  return streamChatRequest(
    `/api/v1/chat/messages/${messageId}/edit?stream=true`,
    { content, attachments },
    callbacks,
    signal,
  );
}

export async function streamChatRegenerate(
  messageId: string,
  callbacks: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return streamChatRequest(
    `/api/v1/chat/messages/${messageId}/regenerate?stream=true`,
    {},
    callbacks,
    signal,
  );
}
