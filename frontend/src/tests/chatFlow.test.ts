import { describe, expect, it } from "vitest";
import {
  reduceChatFlowEvent,
  type ChatFlowEvent,
  type ChatFlowState,
} from "@/lib/chatFlow";

const started: ChatFlowEvent = {
  event: "flow_started",
  payload: {
    flow: "chat",
    steps: [
      { id: "ground", label: "searching the catalog" },
      { id: "generate", label: "writing the reply" },
    ],
  },
};

describe("reduceChatFlowEvent", () => {
  it("starts a flow with all steps pending", () => {
    const state = reduceChatFlowEvent(null, started);
    expect(state).not.toBeNull();
    expect(state!.flow).toBe("chat");
    expect(state!.status).toBe("running");
    expect(state!.steps.map((s) => s.status)).toEqual(["pending", "pending"]);
  });

  it("tracks node transitions in order", () => {
    let state: ChatFlowState | null = reduceChatFlowEvent(null, started);
    const step = (event: ChatFlowEvent) => {
      state = reduceChatFlowEvent(state, event);
    };
    step({ event: "node_started", payload: { id: "ground" } });
    expect(state!.steps.find((s) => s.id === "ground")!.status).toBe("running");
    step({ event: "node_finished", payload: { id: "ground" } });
    step({ event: "node_started", payload: { id: "generate" } });
    step({ event: "node_finished", payload: { id: "generate" } });
    expect(state!.steps.map((s) => s.status)).toEqual(["done", "done"]);
    step({ event: "flow_finished", payload: {} });
    expect(state!.status).toBe("done");
  });

  it("marks the flow failed on flow_failed", () => {
    let state: ChatFlowState | null = reduceChatFlowEvent(null, started);
    state = reduceChatFlowEvent(state, {
      event: "node_started",
      payload: { id: "ground" },
    });
    state = reduceChatFlowEvent(state, {
      event: "flow_failed",
      payload: { code: "ai_error", message: "boom", retryable: true },
    });
    expect(state!.status).toBe("failed");
  });

  it("ignores node events before flow_started", () => {
    expect(
      reduceChatFlowEvent(null, { event: "node_started", payload: { id: "x" } }),
    ).toBeNull();
  });
});
