import type { ReactNode } from "react";

/** Plan-109 traceability: the tool card's result pane gets a legible,
 copyable view scoped to the message; JSON pretty-prints when parseable,
 raw text otherwise (the library ChatToolCard renders whatever the app
 returns through `renderResult` — no library change needed). */
export function prettyToolResult(result: string | null | undefined): string {
  if (!result) {
    return "";
  }
  const trimmed = result.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return result;
  }
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return result;
  }
}

export function renderToolResult(result: string): ReactNode {
  const pretty = prettyToolResult(result);
  if (pretty === result && !result) {
    return null;
  }
  return (
    <div
      className="relative max-h-72 overflow-auto rounded-md bg-[var(--as-muted)] p-2"
      data-testid="chat-tool-result"
    >
      <button
        type="button"
        aria-label="Copy tool result"
        onClick={async () => {
          await navigator.clipboard?.writeText?.(pretty ?? "");
        }}
        className="absolute right-1 top-1 rounded px-1.5 text-[10px] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
      >
        Copy
      </button>
      <pre className="whitespace-pre-wrap break-words pr-6 font-mono text-[11px] leading-relaxed text-[var(--as-fg)]">
        {pretty}
      </pre>
    </div>
  );
}
