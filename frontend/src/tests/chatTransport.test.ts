import { describe, expect, it, vi, beforeEach } from "vitest";

import { createChatTransport } from "@/components/chat/chatTransport";
import type { ChatStreamEvent } from "@/components/ui/chat";
import type { ChatStreamCallbacks } from "@/api/chatStream";

const streamChatMessage = vi.hoisted(() => vi.fn());

vi.mock("@/api/chatStream", () => ({
  streamChatMessage: (
    sessionId: string,
    content: string,
    callbacks: ChatStreamCallbacks,
    signal?: AbortSignal,
  ) => streamChatMessage(sessionId, content, callbacks, signal),
}));

function captureCallbacks() {
  const callbacks = {} as ChatStreamCallbacks;
  streamChatMessage.mockImplementation(
    async (_id: string, _content: string, cbs: ChatStreamCallbacks) => {
      Object.assign(callbacks, cbs);
    },
  );
  return callbacks;
}

describe("createChatTransport", () => {
  beforeEach(() => {
    streamChatMessage.mockReset();
  });

  it("fails sends without an active session", async () => {
    const transport = createChatTransport({ getSessionId: () => null });
    await expect(transport.send({ text: "hi" })).rejects.toThrow("No active chat session");
  });

  it("diffs accumulated deltas into incremental family events", async () => {
    const events: ChatStreamEvent[] = [];
    streamChatMessage.mockImplementation(
      async (_id: string, _content: string, callbacks: ChatStreamCallbacks) => {
        callbacks.onDelta?.("Hel");
        callbacks.onDelta?.("Hello");
        callbacks.onDelta?.("Hello world");
      },
    );
    const transport = createChatTransport({ getSessionId: () => "s1" });
    transport.subscribe({ onEvent: (event) => events.push(event) });
    await transport.send({ text: "hi" });
    expect(events).toEqual([
      { event: "delta", text: "Hel" },
      { event: "delta", text: "lo" },
      { event: "delta", text: " world" },
      { event: "flow_finished" },
    ]);
  });

  it("maps career flow events onto the family vocabulary", async () => {
    const callbacks = captureCallbacks();
    const events: ChatStreamEvent[] = [];
    const transport = createChatTransport({ getSessionId: () => "s1" });
    transport.subscribe({ onEvent: (event) => events.push(event) });
    await transport.send({ text: "hi" });
    callbacks.onFlowEvent?.({
      event: "flow_started",
      payload: { flow: "chat", steps: [{ id: "search", label: "Searching the catalog" }] },
    });
    callbacks.onFlowEvent?.({ event: "node_started", payload: { id: "search", label: "Searching the catalog" } });
    callbacks.onFlowEvent?.({ event: "node_finished", payload: { id: "search" } });
    callbacks.onFlowEvent?.({
      event: "flow_failed",
      payload: { code: "rate_limit", message: "slow", retryable: true },
    });
    expect(events).toContainEqual({
      event: "flow_started",
      flow: "chat",
      steps: [{ id: "search", label: "Searching the catalog" }],
    });
    expect(events).toContainEqual({ event: "node_started", node: "search", label: "Searching the catalog" });
    expect(events).toContainEqual({ event: "node_finished", node: "search", outcome: "done" });
    expect(events).toContainEqual({
      event: "flow_failed",
      code: "rate_limit",
      message: "slow",
      retryable: true,
    });
  });

  it("maps tool_call trace events onto the family vocabulary", async () => {
    const callbacks = captureCallbacks();
    const events: ChatStreamEvent[] = [];
    const transport = createChatTransport({ getSessionId: () => "s1" });
    transport.subscribe({ onEvent: (event) => events.push(event) });
    await transport.send({ text: "hi" });
    callbacks.onFlowEvent?.({
      event: "tool_call",
      payload: {
        id: "search_jobs-0",
        name: "search_jobs",
        title: "Searching the job catalog",
        status: "done",
        args: '{"query": "nurse"}',
        result: '["NO-1210"]',
        duration_ms: 12,
      },
    });
    expect(events).toContainEqual({
      event: "tool_call",
      id: "search_jobs-0",
      name: "search_jobs",
      title: "Searching the job catalog",
      status: "done",
      args: '{"query": "nurse"}',
      result: '["NO-1210"]',
      durationMs: 12,
    });
  });

  it("aborts the in-flight request on stop", async () => {
    let capturedSignal: AbortSignal | undefined;
    let resolveStream: (() => void) | undefined;
    streamChatMessage.mockImplementation(
      (_id: string, _content: string, _cbs: ChatStreamCallbacks, signal?: AbortSignal) => {
        capturedSignal = signal;
        return new Promise<void>((resolve) => {
          resolveStream = resolve;
        });
      },
    );
    const transport = createChatTransport({ getSessionId: () => "s1" });
    const sendPromise = transport.send({ text: "hi" });
    await Promise.resolve();
    await transport.stop?.();
    expect(capturedSignal?.aborted).toBe(true);
    resolveStream?.();
    await sendPromise;
  });
});
