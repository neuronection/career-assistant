import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { MessageSquareText, Plus, Send, X } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const {
    sessions,
    activeSessionId,
    messages,
    sending,
    streamingText,
    streamingStage,
    loadSessions,
    openSession,
    newSession,
    send,
  } = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) void loadSessions();
  }, [open, loadSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, streamingStage]);

  const submit = async () => {
    const content = draft.trim();
    if (!content || sending) return;
    setDraft("");
    await send(content);
  };

  if (!open) {
    return (
      <button
        type="button"
        aria-label="Open chat assistant"
        data-testid="chat-launcher"
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-50 bg-primary-600 hover:bg-primary-700 text-white rounded-full p-4 shadow-lg"
      >
        <MessageSquareText className="w-6 h-6" />
      </button>
    );
  }

  return (
    <div
      data-testid="chat-panel"
      className="fixed bottom-5 right-5 z-50 w-96 max-w-[calc(100vw-2.5rem)] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col"
      style={{ height: "32rem" }}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
        <span className="font-medium text-sm">Career Assistant</span>
        <div className="flex items-center gap-2">
          <button
            aria-label="New chat"
            onClick={() => void newSession()}
            className="text-slate-400 hover:text-slate-700"
          >
            <Plus className="w-4 h-4" />
          </button>
          <button aria-label="Close chat" onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
      {activeSessionId ? (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.length === 0 && (
              <p className="text-sm text-slate-400">Ask anything about careers, jobs or study paths.</p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={m.role === "user" ? "text-right" : ""}>
                <div
                  className={`inline-block text-sm rounded-xl px-3 py-2 max-w-[85%] whitespace-pre-wrap ${
                    m.role === "user" ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-800"
                  }`}
                >
                  {m.content}
                </div>
                {m.role === "assistant" && (m.metadata_json?.referenced_job_codes ?? []).length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {m.metadata_json!.referenced_job_codes!.map((code) => (
                      <Link
                        key={code}
                        to={`/jobs/${code}`}
                        className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full hover:bg-primary-100"
                      >
                        {code}
                      </Link>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && (m.metadata_json?.referenced_posting_refs ?? []).length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {m.metadata_json!.referenced_posting_refs!.map((ref) => (
                      <Link
                        key={ref}
                        to={`/postings?posting=${ref}`}
                        className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full hover:bg-emerald-100"
                        data-testid={`chat-posting-ref-${ref}`}
                      >
                        {ref}
                      </Link>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && m.metadata_json?.explore_query && (
                  <div className="mt-1">
                    <Link
                      to={`/explore?${m.metadata_json.explore_query}`}
                      className="text-xs text-primary-700 hover:underline"
                      data-testid="chat-explore-link"
                    >
                      Open in Explore →
                    </Link>
                  </div>
                )}
              </div>
            ))}
            {(streamingText !== null || streamingStage !== null) && (
              <div>
                {streamingText ? (
                  <div className="inline-block text-sm rounded-xl px-3 py-2 max-w-[85%] whitespace-pre-wrap bg-slate-100 text-slate-800">
                    {streamingText}
                    <span className="animate-pulse">▍</span>
                  </div>
                ) : (
                  <div className="inline-block text-xs text-slate-400 px-1">
                    {streamingStage ?? "thinking…"}
                  </div>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>
          <div className="border-t border-slate-100 p-3 flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void submit()}
              placeholder="Ask about a job…"
              className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <button
              aria-label="Send message"
              data-testid="chat-send"
              onClick={() => void submit()}
              disabled={sending}
              className="bg-primary-600 text-white rounded-lg px-3 disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </>
      ) : (
        <div className="flex-1 overflow-y-auto p-3">
          <button
            onClick={() => void newSession()}
            className="w-full text-sm bg-primary-50 text-primary-700 rounded-lg py-2 mb-3"
          >
            + New conversation
          </button>
          <div className="space-y-1">
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => void openSession(s.id)}
                className="w-full text-left text-sm px-3 py-2 rounded-lg hover:bg-slate-100 truncate"
              >
                {s.title}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
