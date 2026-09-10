import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChatMessage } from "@/api/chatStream";

const encoder = new TextEncoder();

function sseResponse(chunks: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

function event(name: string, payload: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
}

describe("streamChatMessage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reassembles events split across chunk boundaries", async () => {
    const statusBody = JSON.stringify({
      stage: "searching the catalog",
      found: 3,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          "event: sta",
          `tus\ndata: ${statusBody}\n\n`,
          event("delta", { text: "Hel" }) +
            event("delta", { text: "lo" }) +
            "event: del",
          `ta\ndata: ${JSON.stringify({ text: "!" })}\n\n`,
          event("meta", {
            message_id: "m1",
            referenced_job_codes: ["software-engineer"],
          }),
          event("done", { ok: true }),
        ]),
      ),
    );

    const statuses: Array<[string, number | undefined]> = [];
    const deltas: string[] = [];
    let meta: { message_id: string; referenced_job_codes: string[] } | undefined;

    await streamChatMessage("session-1", "hello", {
      onStatus: (stage, found) => statuses.push([stage, found]),
      onDelta: (accumulated) => deltas.push(accumulated),
      onMeta: (m) => (meta = m),
    });

    expect(statuses).toEqual([["searching the catalog", 3]]);
    expect(deltas).toEqual(["Hel", "Hello", "Hello!"]);
    expect(meta).toEqual({
      message_id: "m1",
      referenced_job_codes: ["software-engineer"],
    });
  });

  it("rejects on a stream error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse([event("error", { detail: "boom" })])),
    );
    await expect(streamChatMessage("s", "hi", {})).rejects.toThrow("boom");
  });

  it("surfaces the API detail on non-OK responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "no session" }), { status: 404 }),
      ),
    );
    await expect(streamChatMessage("s", "hi", {})).rejects.toThrow("no session");
  });

  it("forwards family flow events to onFlowEvent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          event("status", { stage: "searching the catalog", found: 1 }),
          event("flow_started", {
            flow: "chat",
            steps: [
              { id: "ground", label: "searching the catalog" },
              { id: "generate", label: "writing the reply" },
            ],
          }),
          event("node_started", { id: "ground" }),
          event("node_finished", { id: "ground" }),
          event("node_started", { id: "generate" }),
          event("delta", { text: "Hi" }),
          event("node_finished", { id: "generate" }),
          event("meta", { message_id: "m1", referenced_job_codes: [] }),
          event("flow_finished", { flow: "chat" }),
          event("done", { ok: true }),
        ]),
      ),
    );

    const flowEvents: string[] = [];
    let deltas = 0;
    await streamChatMessage("s", "hi", {
      onDelta: () => (deltas += 1),
      onFlowEvent: (e) => flowEvents.push(e.event),
    });

    expect(flowEvents).toEqual([
      "flow_started",
      "node_started",
      "node_finished",
      "node_started",
      "node_finished",
      "flow_finished",
    ]);
    expect(deltas).toBe(1);
  });

  it("ignores unknown additive events", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([event("flow_paused", { why: "later" }), event("done", { ok: true })]),
      ),
    );
    const onFlowEvent = vi.fn();
    await expect(streamChatMessage("s", "hi", { onFlowEvent })).resolves.toBeUndefined();
    expect(onFlowEvent).not.toHaveBeenCalled();
  });

  it("rejects on flow_failed with the family message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          event("flow_failed", {
            code: "ai_unavailable",
            message: "no valid output",
            retryable: true,
          }),
          event("error", { detail: "no valid output" }),
        ]),
      ),
    );
    await expect(streamChatMessage("s", "hi", {})).rejects.toThrow("no valid output");
  });
});
