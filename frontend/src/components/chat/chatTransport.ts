import {
  streamChatEdit,
  streamChatMessage,
  streamChatRegenerate,
} from "@/api/chatStream";
import type { ChatFlowEvent } from "@/lib/chatFlow";
import type { ChatStreamEvent, ChatStreamTransport } from "@/components/ui/chat";

function mapFlowEvent(event: ChatFlowEvent): ChatStreamEvent {
  switch (event.event) {
    case "flow_started":
      return { event: "flow_started", flow: event.payload.flow, steps: event.payload.steps };
    case "node_started":
      return { event: "node_started", node: event.payload.id, label: event.payload.label };
    case "node_finished":
      return { event: "node_finished", node: event.payload.id, outcome: "done" };
    case "tool_call":
      return {
        event: "tool_call",
        id: event.payload.id,
        name: event.payload.name,
        title: event.payload.title,
        status: event.payload.status ?? "done",
        args: event.payload.args,
        result: event.payload.result,
        durationMs: event.payload.duration_ms,
      };
    case "flow_finished":
      return { event: "flow_finished" };
    case "flow_failed":
      return {
        event: "flow_failed",
        code: event.payload.code,
        message: event.payload.message,
        retryable: event.payload.retryable,
      };
  }
}

type Intent = { kind: "send" } | { kind: "edit"; messageId: string } | { kind: "regenerate"; messageId: string };

export interface ChatTransportDeps {
  getSessionId: () => string | null;
  /**: the CV builder copilot's terminal `builder_state` payload. */
  onBuilderState?: (state: Record<string, unknown>) => void;
}

export interface CareerChatTransport extends ChatStreamTransport {
  /** Route the next `send` to the edit-branch endpoint. */
  beginEdit: (messageId: string) => void;
  /** Route the next `send` to the regenerate endpoint. */
  beginRegenerate: (messageId: string) => void;
}

/**
 * App-side adapter (family): maps career's SSE stream (legacy
 * status/delta/meta/done + family flow events) onto the library's
 * `ChatStreamEvent` vocabulary for `useChatStream`. Career's accumulated
 * deltas are diffed into incremental chunks; a mutable intent routes
 * `send` to the edit/regenerate endpoints (branching).
 */
export function createChatTransport(deps: ChatTransportDeps): CareerChatTransport {
  let onEvent: ((event: ChatStreamEvent) => void) | null = null;
  let controller: AbortController | null = null;
  let intent: Intent = { kind: "send" };

  const run = (stream: (callbacks: Parameters<typeof streamChatMessage>[2]) => Promise<void>) => {
    let sent = 0;
    return stream({
      onDelta: (accumulated) => {
        if (accumulated.length > sent) {
          onEvent?.({ event: "delta", text: accumulated.slice(sent) });
          sent = accumulated.length;
        }
      },
      onFlowEvent: (event) => onEvent?.(mapFlowEvent(event)),
      onBuilderState: (state) => deps.onBuilderState?.(state),
    });
  };

  return {
    subscribe: (handlers) => {
      onEvent = handlers.onEvent;
      return () => {
        onEvent = null;
      };
    },
    send: async ({ text }) => {
      const current = intent;
      intent = { kind: "send" };
      const sessionId = deps.getSessionId();
      if (current.kind === "send") {
        if (sessionId === null) {
          throw new Error("No active chat session");
        }
        controller = new AbortController();
        try {
          await run((callbacks) => streamChatMessage(sessionId, text, callbacks, controller!.signal));
          onEvent?.({ event: "flow_finished" });
        } finally {
          controller = null;
        }
        return;
      }
      controller = new AbortController();
      try {
        if (current.kind === "edit") {
          await run((callbacks) => streamChatEdit(current.messageId, text, callbacks, controller!.signal));
        } else {
          await run((callbacks) => streamChatRegenerate(current.messageId, callbacks, controller!.signal));
        }
        onEvent?.({ event: "flow_finished" });
      } finally {
        controller = null;
      }
    },
    stop: async () => {
      controller?.abort();
    },
    beginEdit: (messageId) => {
      intent = { kind: "edit", messageId };
    },
    beginRegenerate: (messageId) => {
      intent = { kind: "regenerate", messageId };
    },
  };
}
