import type { FlowStep, FlowStepStatus } from "@/components/ui";

/** Family chat events carried on the SSE stream ( +
 * tool trace). */
export type ChatFlowEvent =
  | { event: "flow_started"; payload: { flow: string; steps: { id: string; label: string }[] } }
  | { event: "node_started"; payload: { id: string; label?: string } }
  | { event: "node_finished"; payload: { id: string; duration_ms?: number } }
  | {
      event: "tool_call";
      payload: {
        id: string;
        name: string;
        title?: string;
        status?: "running" | "done" | "failed";
        args?: string;
        result?: string;
        duration_ms?: number;
      };
    }
  | { event: "flow_finished"; payload: Record<string, unknown> }
  | { event: "flow_failed"; payload: { code: string; message: string; retryable: boolean } };

export interface ChatFlowState {
  flow: string;
  steps: FlowStep[];
  status: FlowStepStatus;
}

/** Reduce family flow events into FlowStatusCard state (pure, tested). */
export function reduceChatFlowEvent(
  state: ChatFlowState | null,
  event: ChatFlowEvent,
): ChatFlowState | null {
  if (event.event === "flow_started") {
    return {
      flow: event.payload.flow,
      steps: event.payload.steps.map((step) => ({ ...step, status: "pending" })),
      status: "running",
    };
  }
  if (state === null) return null;

  const mapStep = (id: string, status: FlowStepStatus): FlowStep[] =>
    state.steps.map((step) => (step.id === id ? { ...step, status } : step));

  switch (event.event) {
    case "node_started":
      return {
        ...state,
        steps: mapStep(event.payload.id, "running"),
        status: state.status === "failed" ? state.status : "running",
      };
    case "node_finished":
      return { ...state, steps: mapStep(event.payload.id, "done") };
    case "flow_finished":
      return { ...state, status: "done" };
    case "flow_failed":
      return { ...state, status: "failed" };
    default:
      return state;
  }
}
