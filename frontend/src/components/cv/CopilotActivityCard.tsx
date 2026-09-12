import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Bot, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { useCvLiveTurn } from "@/stores/cvBuilderLinkStore";
import { useChatStore } from "@/stores/chatStore";
import { isCvBoundSession } from "@/components/chat/cvChatLink";
import { traceFromLiveTurn, traceFromTurnMeta } from "@/lib/cvBuildTrace";
import { ChatToolCard } from "@/components/ui/chat";
import type { ChatMessage } from "@/types";

type TurnMeta = NonNullable<ChatMessage["metadata_json"]>;
type ToolCardInput = {
  name: string;
  title?: string;
  status: "running" | "done" | "failed";
  args?: string;
  result?: string;
  durationMs?: number;
};

/**
 * The builder's "now" face for copilot turns (plan 67.2): the live
 * turn mirrored from the chat stream (works with the dock closed),
 * falling back after reset to the CV session's latest persisted turn
 * trace (plan 66 metadata) — never a blank card after a finished turn.
 */
export function CopilotActivityCard({ cvId }: { cvId: string }) {
  const { t } = useTranslation();
  const liveTurn = useCvLiveTurn(cvId);
  const messages = useChatStore((state) => state.messages);
  const sessionId = useChatStore((state) => state.activeSessionId);
  const sessions = useChatStore((state) => state.sessions);

  const persistedMeta = useMemo<TurnMeta | null>(() => {
    const active = sessions.find((session) => session.id === sessionId);
    if (isCvBoundSession(active) !== cvId) return null;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role !== "assistant") continue;
      const meta = message.metadata_json;
      if (!meta || meta.surface !== "cv_builder") continue;
      if ((meta.nodes ?? []).length > 0 || (meta.tools ?? []).length > 0) {
        return meta;
      }
    }
    return null;
  }, [messages, sessionId, sessions, cvId]);

  if (liveTurn === null && persistedMeta === null) {
    return null;
  }

  const live = liveTurn !== null;
  const running = live && (liveTurn.status === "pending" || liveTurn.status === "streaming");
  const error = live && liveTurn.error != null;
  const trace = live ? traceFromLiveTurn(liveTurn) : traceFromTurnMeta(persistedMeta);
  const stages = trace.stages;
  const toolCalls: ToolCardInput[] = live
    ? (liveTurn.toolCalls ?? [])
    : (persistedMeta?.tools ?? []).map((tool) => ({
        name: tool.name,
        title: tool.title,
        status: tool.status === "failed" ? ("failed" as const) : ("done" as const),
        args: tool.args_summary ?? undefined,
        result: tool.result_summary ?? undefined,
        durationMs: tool.duration_ms ?? undefined,
      }));

  return (
    <div
      className="rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
      data-testid="cv-copilot-activity"
      data-active={live ? "live" : "final"}
    >
      <div className="flex items-center gap-2">
        <Bot className="size-4 shrink-0 text-[var(--as-accent)]" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-xs font-medium" data-testid="cv-copilot-title">
          {t("cvBuilder.copilotActivity.title", "Copilot activity")}
        </span>
        {running ? (
          <span
            className="flex items-center gap-1.5 rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
            data-testid="cv-copilot-running"
          >
            <Loader2 className="size-3 animate-spin" aria-hidden />
            {t("cvBuilder.copilotActivity.working", "Working…")}
          </span>
        ) : error ? (
          <span
            className="flex items-center gap-1.5 rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-red-700"
            data-testid="cv-copilot-error"
          >
            <XCircle className="size-3" aria-hidden />
            {t("cvBuilder.copilotActivity.error", "Turn failed")}
          </span>
        ) : (
          <span
            className="flex items-center gap-1.5 rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
            data-testid="cv-copilot-done"
          >
            <CheckCircle2 className="size-3" aria-hidden />
            {t("cvBuilder.copilotActivity.done", "Turn finished")}
          </span>
        )}
      </div>
      {stages.length > 0 ? (
        <div className="mt-2 space-y-1" data-testid="cv-copilot-stages">
          {stages.map((stage, index) => (
            <div key={`${stage.label}-${index}`} className="flex min-w-0 items-center gap-2 text-xs">
              {stage.note === null ? (
                <CheckCircle2 className="size-3 shrink-0 text-emerald-600" aria-hidden />
              ) : stage.note === "failed" ? (
                <XCircle className="size-3 shrink-0 text-red-600" aria-hidden />
              ) : (
                <Loader2 className="size-3 shrink-0 animate-spin text-[var(--as-accent)]" aria-hidden />
              )}
              <span className="min-w-0 flex-1 truncate">{stage.label}</span>
            </div>
          ))}
        </div>
      ) : null}
      {toolCalls.length > 0 ? (
        <div className="mt-2 flex w-full flex-col gap-1" data-testid="cv-copilot-tools">
          {toolCalls.map((call, index) => (
            <ChatToolCard
              key={`${call.name}-${index}`}
              name={call.name}
              title={call.title}
              status={call.status}
              args={call.args}
              result={call.result}
              durationMs={call.durationMs}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
