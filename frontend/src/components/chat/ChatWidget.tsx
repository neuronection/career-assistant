import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bot, GitBranch, Plus, Wrench, X } from "lucide-react";

import {
  ChatBranchTree,
  ChatComposer,
  ChatHistoryButton,
  ChatLauncher,
  ChatMessage,
  ChatPanel,
  ChatToolCard,
  ChatTraceMeta,
  ChatTraceTimeline,
  ChatTranscript,
  ChatTurnStatus,
  MarkdownSurface,
  buildBranchTree,
  type BranchTree,
  type ChatMessageView,
} from "@/components/ui/chat";
import { Button, PopoverButton } from "@/components/ui";
import {
  DictationButton,
  DictationStrip,
  useDictation,
} from "@/components/ui/dictation";
import { fetchChatTree, type ChatTree } from "@/api/universities";
import { transcribeAudio, classifyDictationError } from "@/api/ai";
import { useChatStore } from "@/stores/chatStore";
import { ChatViewSwitcher } from "@/components/chat/ChatViewSwitcher";
import { activeCvId } from "@/components/chat/cvChatLink";
import {
  cvPromptChips,
  GENERIC_SUGGESTIONS,
  removeCustomPrompt,
  saveCustomPrompt,
} from "@/lib/assistantPrompts";
import { SessionList } from "@/components/chat/SessionList";
import { ToolsDialog } from "@/components/chat/ToolsDialog";
import {
  CareerChatProvider,
  useCareerChatContext,
} from "@/components/chat/useCareerChat";
import type { ChatMessage as ChatMessageRow } from "@/types";

function TraceMeta({ message }: { message: ChatMessageRow }) {
  const meta = message.metadata_json;
  const model = meta?.model;
  const elapsedMs = meta?.elapsed_ms;
  const tools = meta?.tools;
  const hasTrace =
    (typeof model === "string" && model !== "") ||
    typeof elapsedMs === "number" ||
    (Array.isArray(tools) && tools.length > 0);
  if (!hasTrace) {
    return null;
  }
  return (
    <div data-testid="chat-meta-badges" className="contents">
      <ChatTraceMeta
        model={typeof model === "string" ? model : undefined}
        durationMs={typeof elapsedMs === "number" ? elapsedMs : undefined}
        toolCount={Array.isArray(tools) ? tools.length : undefined}
      />
    </div>
  );
}

/**
 * Post-turn trace for an assistant reply (persisted-trace wave): per-tool
 * observation cards + the phase/tool timeline from `metadata_json`.
 * Legacy messages without execution windows keep the compact badges.
 */
function MessageTrace({ message }: { message: ChatMessageRow }) {
  const meta = message.metadata_json;
  const tools = meta?.tools ?? [];
  const nodes = meta?.nodes ?? [];
  const hasTrace =
    (typeof meta?.model === "string" && meta.model !== "") ||
    typeof meta?.elapsed_ms === "number" ||
    tools.length > 0 ||
    nodes.length > 0;
  if (!hasTrace) {
    return null;
  }
  const hasTimeline =
    nodes.length > 0 || tools.some((tool) => typeof tool.start_ms === "number");
  if (!hasTimeline) {
    return <TraceMeta message={message} />;
  }
  return (
    <div className="mt-1 flex w-full flex-col gap-1" data-testid="chat-message-trace">
      {tools.map((tool, index) => (
        <ChatToolCard
          key={`${tool.name}-${index}`}
          name={tool.name}
          title={tool.title}
          status={tool.status === "failed" ? "failed" : "done"}
          args={tool.args_summary}
          result={tool.result_summary}
          durationMs={tool.duration_ms}
        />
      ))}
      <ChatTraceTimeline
        trace={{
          model: meta?.model ?? null,
          latencyMs: meta?.elapsed_ms ?? null,
          outputTokens: meta?.tokens_out ?? null,
        }}
        entries={[
          ...nodes.map((node) => ({
            kind: "phase" as const,
            label: node.label ?? node.id,
            startMs: node.start_ms ?? null,
            durationMs: node.duration_ms ?? null,
          })),
          ...tools.map((tool) => ({
            kind: "tool" as const,
            label: tool.name,
            detail: tool.args_summary ?? null,
            startMs: tool.start_ms ?? null,
            durationMs: tool.duration_ms ?? null,
          })),
        ]}
      />
    </div>
  );
}

function ReferenceChips({ message }: { message: ChatMessageRow }) {
  const { t } = useTranslation();
  const meta = message.metadata_json;
  if (meta === null) {
    return null;
  }
  return (
    <>
      {(meta.referenced_job_codes ?? []).length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {meta.referenced_job_codes!.map((code) => (
            <Link
              key={code}
              to={`/jobs/${code}`}
              className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full hover:bg-primary-100"
            >
              {code}
            </Link>
          ))}
        </div>
      ) : null}
      {(meta.referenced_posting_refs ?? []).length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {meta.referenced_posting_refs!.map((ref) => (
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
      ) : null}
      {meta.explore_query ? (
        <div className="mt-1">
          <Link
            to={`/explore?${meta.explore_query}`}
            className="text-xs text-primary-700 hover:underline"
            data-testid="chat-explore-link"
          >
            {t("chat.openInExplore")}
          </Link>
        </div>
      ) : null}
    </>
  );
}

function ChatEmptyState({ compact }: { compact: boolean }) {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const sessions = useChatStore((state) => state.sessions);
  const activeSessionId = useChatStore((state) => state.activeSessionId);
  const cvId = activeCvId(sessions, activeSessionId);
  const [savedPrompts, setSavedPrompts] = useState(() =>
    cvId ? cvPromptChips("resume").filter((chip) => chip.custom).map((chip) => chip.prompt) : [],
  );
  if (cvId) {
    const chips = [
      ...cvPromptChips("resume").filter((chip) => !chip.custom),
      ...savedPrompts.map((prompt) => ({ prompt, custom: true })),
    ];
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <span className="flex size-10 items-center justify-center rounded-full bg-primary-50">
          <Bot className="size-5 text-primary-600" aria-hidden />
        </span>
        <p className="max-w-[16rem] text-sm text-slate-400">
          {t("chat.cvEmptyBody")}
        </p>
        <div className="flex w-full max-w-xs flex-col gap-1.5" data-testid="cv-chat-prompts">
          {chips.map(({ prompt, custom }) => (
            <span key={prompt} className="group relative">
              <button
                type="button"
                data-testid="cv-chat-prompt"
                onClick={() => chat.setDraft(prompt)}
                className="w-full rounded-full border border-slate-200 px-3 py-1.5 pr-7 text-xs text-slate-600 transition-colors hover:bg-slate-50"
              >
                {prompt}
              </button>
              {custom ? (
                <button
                  type="button"
                  aria-label={t("chat.removeSavedPrompt", { prompt })}
                  data-testid="cv-chat-prompt-remove"
                  onClick={() =>
                    setSavedPrompts(removeCustomPrompt(prompt))
                  }
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <X className="size-3" />
                </button>
              ) : null}
            </span>
          ))}
          {chat.draft.trim() ? (
            <button
              type="button"
              data-testid="cv-chat-prompt-save"
              onClick={() => {
                setSavedPrompts(saveCustomPrompt(chat.draft));
                chat.setDraft("");
              }}
              className="rounded-full border border-dashed border-slate-300 px-3 py-1.5 text-xs text-slate-500 transition-colors hover:bg-slate-50"
            >
              {t("chat.saveDraftPrompt")}
            </button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <span className="flex size-10 items-center justify-center rounded-full bg-primary-50">
        <Bot className="size-5 text-primary-600" aria-hidden />
      </span>
      <p className={`text-sm text-slate-400 ${compact ? "max-w-[16rem]" : "max-w-sm"}`}>
        {t("chat.emptyBody")}
      </p>
      <div className="flex flex-col gap-1.5">
        {GENERIC_SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            data-testid="chat-suggestion"
            onClick={() => chat.setDraft(suggestion)}
            className="rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition-colors hover:bg-slate-50"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageList({ compact }: { compact: boolean }) {
  const chat = useCareerChatContext();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const renderItem = (message: ChatMessageView) => {
    const raw = chat.messages.find((candidate) => candidate.id === message.id);
    const parentUser =
      raw?.role === "assistant"
        ? chat.messages.find((candidate) => candidate.id === raw.parent_id)
        : undefined;
    return (
      <ChatMessage
        key={message.id}
        role={message.role}
        content={<MarkdownSurface value={message.content} />}
        compact={compact}
        editing={
          editingId === message.id
            ? {
                value: editDraft,
                onValueChange: setEditDraft,
                onSubmit: () => {
                  void chat.submitEdit(message.id, editDraft);
                  setEditingId(null);
                },
                onCancel: () => setEditingId(null),
                submitDisabled: chat.sending,
              }
            : false
        }
        actions={{
          onCopy: () => void navigator.clipboard.writeText(message.content),
          onEdit:
            message.role === "user"
              ? () => {
                  setEditingId(message.id);
                  setEditDraft(message.content);
                }
              : undefined,
          onRegenerate:
            message.role === "assistant" && parentUser
              ? () => void chat.regenerate(parentUser.id, parentUser.content)
              : undefined,
        }}
        variants={message.variants}
        onSelectVariant={(id) => void chat.selectVariant(id)}
        chips={raw && raw.role === "assistant" ? <ReferenceChips message={raw} /> : undefined}
        meta={raw && raw.role === "assistant" ? <MessageTrace message={raw} /> : undefined}
      />
    );
  };

  const live = chat.stream.live !== null;
  const runningNode = [...chat.stream.nodes]
    .reverse()
    .find((node) => node.status === "running");
  const lastNode = chat.stream.nodes[chat.stream.nodes.length - 1];
  const turnLabel =
    runningNode?.label ?? lastNode?.label ?? "thinking";
  const toolCards =
    chat.stream.toolCalls.length > 0 ? (
      <div className="flex w-full flex-col gap-1" data-testid="chat-live-tools">
        {chat.stream.toolCalls.map((call) => (
          <ChatToolCard
            key={call.id}
            name={call.name}
            title={call.title}
            status={call.status}
            args={call.args}
            result={call.result}
            durationMs={call.durationMs}
          />
        ))}
      </div>
    ) : null;

  return (
    <ChatTranscript
      items={chat.viewMessages}
      renderItem={renderItem}
      emptyState={<ChatEmptyState compact={compact} />}
      live={
        live ? (
          <ChatMessage
            role="assistant"
            status={
              chat.stream.status === "interrupted"
                ? "interrupted"
                : chat.stream.status === "error"
                  ? "error"
                  : "streaming"
            }
            error={chat.stream.error ?? undefined}
            actions={
              chat.stream.error?.retryable
                ? { onRetry: () => void chat.retry() }
                : undefined
            }
            content={
              <>
                {toolCards}
                {chat.stream.text !== null ? (
                  <>
                    <MarkdownSurface value={chat.stream.text} streaming />
                    <span className="animate-pulse text-slate-400">▍</span>
                  </>
                ) : chat.stream.status === "error" ? null : (
                  <ChatTurnStatus
                    variant="card"
                    label={turnLabel}
                    startedAt={chat.stream.startedAt ?? undefined}
                  />
                )}
              </>
            }
          />
        ) : undefined
      }
    />
  );
}

function ComposerBar() {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const draftRef = useRef(chat.draft);
  draftRef.current = chat.draft;
  const dictation = useDictation({
    transcribe: transcribeAudio,
    classifyError: classifyDictationError,
    onResult: (text) => {
      const current = draftRef.current;
      const glue = current !== "" && !current.endsWith(" ") ? " " : "";
      chat.setDraft(`${current}${glue}${text} `);
    },
  });
  const [micHidden, setMicHidden] = useState(false);
  const errorKind = dictation.error?.kind;
  useEffect(() => {
    if (errorKind === "unassigned" || errorKind === "unsupported") {
      setMicHidden(true);
      dictation.dismissError();
    }
  }, [errorKind, dictation]);

  return (
    <ChatComposer
      value={chat.draft}
      onValueChange={chat.setDraft}
      onSubmit={() => void chat.submit()}
      sending={chat.sending}
      onStop={() => void chat.stream.stop()}
      placeholder={t("chat.composerPlaceholder")}
      toolbarEnd={
        micHidden ? undefined : (
          <DictationButton
            status={dictation.status}
            onStart={() => void dictation.start()}
          />
        )
      }
      suggestions={
        dictation.status !== "idle" || dictation.error !== null ? (
          <DictationStrip
            status={dictation.status}
            seconds={dictation.seconds}
            levelRef={dictation.levelRef}
            error={dictation.error}
            onStop={() => void dictation.stop()}
            onCancel={dictation.cancel}
            onDismissError={dictation.dismissError}
          />
        ) : undefined
      }
    />
  );
}

function SessionPicker() {
  return (
    <div className="p-2">
      <SessionList searchable={false} />
    </div>
  );
}

function HistoryButton() {
  const loadSessions = useChatStore((state) => state.loadSessions);
  return (
    <ChatHistoryButton onOpen={() => void loadSessions()}>
      {(close) => <SessionList onPick={close} />}
    </ChatHistoryButton>
  );
}

function ToolsButton() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        aria-label={t("chat.toolsAria")}
        title={t("chat.toolsAria")}
        data-testid="chat-tools-button"
        onClick={() => setOpen(true)}
      >
        <Wrench className="size-4" />
      </Button>
      <ToolsDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

function BranchTreeButton() {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const [tree, setTree] = useState<ChatTree | null>(null);
  if (chat.activeSessionId === null) {
    return null;
  }
  const load = () => {
    void fetchChatTree(chat.activeSessionId!).then(setTree);
  };
  const branchTree: BranchTree | null = tree
    ? buildBranchTree({
        activeRootId: tree.active_root_id,
        nodes: tree.nodes.map((node) => ({
          id: node.id,
          role: node.role === "user" ? "user" : "assistant",
          excerpt: node.excerpt,
          parentId: node.parent_id,
          activeChildId: node.active_child_id,
        })),
      })
    : null;
  return (
    <PopoverButton
      label={t("chat.branchesLabel")}
      trigger={<GitBranch className="size-4" aria-hidden />}
      onOpenChange={(open) => {
        if (open) {
          load();
        }
      }}
    >
      {branchTree ? (
        <ChatBranchTree
          tree={branchTree}
          onSelect={(id) => {
            void chat.selectVariant(id).then(load);
          }}
          className="w-80"
        />
      ) : (
        <p className="px-3 py-2 text-xs text-slate-400">{t("chat.loadingBranches")}</p>
      )}
    </PopoverButton>
  );
}

function ChatSurface({
  variant,
  onClose,
}: {
  variant: "bubble" | "sidebar" | "page";
  onClose?: () => void;
}) {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  const compact = variant === "bubble";
  return (
    <ChatPanel
      variant={variant}
      title={t("app.name")}
      actions={
        <>
          <HistoryButton />
          <ToolsButton />
          <ChatViewSwitcher surface={variant === "sidebar" ? "docked" : variant} />
          <BranchTreeButton />
          <Button variant="ghost" size="sm" aria-label={t("chat.newChatAria")} onClick={() => void chat.newSession()}>
            <Plus className="size-4" />
          </Button>
          {onClose && (
            <Button variant="ghost" size="sm" aria-label={t("chat.closePanelAria")} onClick={onClose} title={t("chat.closeChat")}>
              <X className="size-4" />
            </Button>
          )}
        </>
      }
      transcript={chat.activeSessionId ? <MessageList compact={compact} /> : <SessionPicker />}
      composer={chat.activeSessionId ? <ComposerBar /> : undefined}
    />
  );
}

export function ChatWidget() {
  const location = useLocation();
  const chatMode = useChatStore((state) => state.chatMode);

  useEffect(() => {
    if (location.pathname !== "/chat") {
      void useChatStore.getState().loadSessions();
    }
  }, [location.pathname]);

  if (location.pathname === "/chat" || chatMode === "docked") {
    return null;
  }

  return (
    <div data-testid="chat-widget">
      <CareerChatProvider>
        <BubbleLauncher />
      </CareerChatProvider>
    </div>
  );
}

/**
 * The bubble owns its close inside the panel header (library
 * `showClose={false}`) — the launcher's overlaid close used to sit on
 * top of the header actions and intercept their clicks.
 */
function BubbleLauncher() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <ChatLauncher
      label={t("chat.launcherLabel")}
      open={open}
      onOpenChange={setOpen}
      showClose={false}
      panel={<ChatSurface variant="bubble" onClose={() => setOpen(false)} />}
    />
  );
}

export function ChatSurfacePage() {
  return (
    <CareerChatProvider>
      <ChatSurface variant="page" />
    </CareerChatProvider>
  );
}

const CHAT_DOCK_WIDTH_KEY = "ca:chat:width";

function clampChatWidth(value: number): number {
  return Math.min(720, Math.max(320, Math.round(value)));
}

/**
 * The docked shape of the ONE chatbot (study's tutor panel): a
 * resizable right column the page content reflows beside — no overlay.
 * Same provider, same surface, same session as bubble and page.
 */
export function ChatDock() {
  const { t } = useTranslation();
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(CHAT_DOCK_WIDTH_KEY));
    return Number.isFinite(stored) && stored >= 320 ? clampChatWidth(stored) : 400;
  });
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const onResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = { startX: event.clientX, startWidth: width };
    if (typeof event.currentTarget.setPointerCapture === "function") {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };

  const onResizeMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    setWidth(clampChatWidth(drag.startWidth + (drag.startX - event.clientX)));
  };

  const onResizeEnd = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    localStorage.setItem(CHAT_DOCK_WIDTH_KEY, String(width));
  };

  return (
    <aside
      data-testid="chat-dock"
      className="relative flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-l border-[var(--as-border)] bg-[var(--as-surface)] max-lg:!w-full"
      style={{ width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("chat.resizeAria")}
        title={t("chat.resizeAria")}
        data-testid="chat-dock-resize-handle"
        className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize transition-colors hover:bg-[var(--as-accent)]"
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
      />
      <CareerChatProvider>
        <ChatSurface variant="sidebar" />
      </CareerChatProvider>
    </aside>
  );
}
