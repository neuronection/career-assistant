import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Link, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bot, FileText, GitBranch, Plus, Sparkles, Wrench, X } from "lucide-react";

import { MessageProposals, ProposalCards } from "@/features/chat/components/chat/MessageProposals";
import { ChatSelectionMenu } from "@/features/chat/components/chat/ChatSelectionMenu";
import { AiSetupPrompt } from "@/components/ai/AiSetupPrompt";
import { copyText } from "@/lib/clipboard";
import { aiFailureCopyKey, aiFailureKind } from "@/lib/aiErrorCopy";
import {
  LiveTemplatePreviews,
  MessageTemplatePreviews,
} from "@/features/chat/components/chat/TemplatePreviews";
import { CvAttachButton, CvAttachChips } from "@/features/chat/components/chat/CvAttachBar";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";
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
  ChatWelcome,
  ChatSuggestionCard,
  MarkdownSurface,
  buildBranchTree,
  type BranchTree,
  type ChatMessageView,
  type ChatPanelVariant,
  type HitlDensity,
} from "@/components/ui/chat";
import type { ChatMessage as ChatMessageRow } from "@/types";
import { Button, Popover, PopoverButton, PopoverContent, PopoverTrigger } from "@/components/ui";
import {
  DictationButton,
  DictationStrip,
  DictationUnavailable,
  useDictation,
} from "@/components/ui/dictation";
import { useConfigSummary } from "@/hooks/useConfigSummary";
import { fetchChatTree, type ChatTree } from "@/api/universities";
import { transcribeAudio, classifyDictationError } from "@/api/ai";
import { effectiveChatMode, useChatStore } from "@/stores/chatStore";
import { ChatViewSwitcher } from "@/features/chat/components/chat/ChatViewSwitcher";
import { CV_PROMPT_KEYS, GENERIC_SUGGESTION_KEYS } from "@/lib/assistantPrompts";
import { SessionList } from "@/features/chat/components/chat/SessionList";
import { ToolsDialog } from "@/features/chat/components/chat/ToolsDialog";
import { renderToolResult } from "@/features/chat/components/chat/toolResultView";
import { MessagePathDraft } from "@/features/chat/components/chat/PathDraftCard";
import {
  CareerChatProvider,
  useCareerChatContext,
  useOpenStudioCv,
} from "@/features/chat/components/chat/useCareerChat";


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
 * Post-turn trace for an assistant reply (persisted-trace wave): the
 * `ChatTraceTimeline` is the SINGLE trace surface — its tool rows carry
 * the expandable parsed args/response, so no separate per-tool card
 * stack. Legacy messages without execution windows keep the compact
 * badges.
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
    return (
      <div className="mt-1 flex w-full flex-col gap-1">
        <TraceMeta message={message} />
      </div>
    );
  }
  return (
    <div className="mt-1 flex w-full flex-col gap-1" data-testid="chat-message-trace">
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
            args: tool.args_summary ?? null,
            response: tool.result_summary ?? null,
            startMs: tool.start_ms ?? null,
            durationMs: tool.duration_ms ?? null,
          })),
        ]}
      />
    </div>
  );
}

function CvRefChip({
  cvId,
  title,
}: {
  cvId: string;
  title?: string;
}) {
  return (
    <Link
      to={`/cv/${cvId}`}
      data-testid={`cv-ref-chip-${cvId}`}
      className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full hover:bg-primary-100"
    >
      {title}
    </Link>
  );
}

function ReferenceChips({
  message,
  cvTitles,
}: {
  message: ChatMessageRow;
  cvTitles?: Record<string, string>;
}) {
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
              to={`/postings/${ref}`}
              className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full hover:bg-emerald-100"
              data-testid={`chat-posting-ref-${ref}`}
            >
              {ref}
            </Link>
          ))}
        </div>
      ) : null}
      {(meta.referenced_cv_ids ?? []).length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {meta.referenced_cv_ids!.map((cvId) => (
            <CvRefChip key={cvId} cvId={cvId} title={cvTitles?.[cvId]} />
          ))}
        </div>
      ) : null}
      {(meta.attachments ?? []).length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {meta.attachments!.map((entry) => (
            <Link
              key={entry.cv_id}
              to={`/cv/${entry.cv_id}`}
              data-testid={`cv-ref-chip-${entry.cv_id}`}
              className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded-full hover:bg-primary-100"
            >
              {entry.title}
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

function AssistantAvatar() {
  return (
    <span
      aria-hidden
      className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,var(--as-primary),var(--as-ai))] text-[var(--as-ai-fg)] shadow-[var(--as-shadow-1)]"
    >
      <Sparkles className="size-3.5" />
    </span>
  );
}

function ChatEmptyState({ variant }: { variant: ChatPanelVariant }) {
  const { t } = useTranslation();
  const chat = useCareerChatContext();
  // Plan 78: with a CV open in Studio, the CV prompt chips replace the
  // generic suggestions — the suggested attach chip rides in the composer.
  const studioMatch = useMatch("/cv/:id");
  const studioCv = studioMatch?.params.id ?? null;
  const welcomeVariant =
    variant === "page" ? "page" : variant === "bubble" ? "bubble" : "sidebar";
  const setup = (
    <AiSetupPrompt variant="card" className="w-full text-left sm:col-span-2" />
  );
  if (studioCv !== null) {
    return (
      <ChatWelcome
        variant={welcomeVariant}
        title={t("chat.cvWelcomeTitle")}
        subtitle={t("chat.cvEmptyBody")}
        icon={<FileText className="size-5 text-[var(--as-ai-fg)]" aria-hidden />}
        suggestions={
          <>
            {setup}
            {CV_PROMPT_KEYS.resume.map((key) => (
              <ChatSuggestionCard
                key={key}
                icon={Sparkles}
                data-testid="cv-chat-prompt"
                onClick={() => chat.setDraft(t(key))}
              >
                {t(key)}
              </ChatSuggestionCard>
            ))}
          </>
        }
      />
    );
  }
  return (
    <ChatWelcome
      variant={welcomeVariant}
      title={t("chat.welcomeTitle")}
      subtitle={t("chat.emptyBody")}
      icon={<Bot className="size-5 text-[var(--as-ai-fg)]" aria-hidden />}
      suggestions={
        <>
          {setup}
          {GENERIC_SUGGESTION_KEYS.map((key) => (
            <ChatSuggestionCard
              key={key}
              icon={Sparkles}
              data-testid="chat-suggestion"
              onClick={() => chat.setDraft(t(key))}
            >
              {t(key)}
            </ChatSuggestionCard>
          ))}
        </>
      }
    />
  );
}

function MessageList({
  variant,
  density,
}: {
  variant: ChatPanelVariant;
  density: HitlDensity;
}) {
  const chat = useCareerChatContext();
  const { t } = useTranslation();
  const compact = variant === "bubble";
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const renderItem = (
    message: ChatMessageView,
    _index: number,
    groupPos?: "single" | "start" | "mid" | "end",
  ) => {
    const raw = chat.messages.find((candidate) => candidate.id === message.id);
    const showAvatar =
      message.role === "assistant" &&
      (groupPos === undefined || groupPos === "single" || groupPos === "start");
    const avatar = showAvatar ? <AssistantAvatar /> : undefined;
    const parentUser =
      raw?.role === "assistant"
        ? chat.messages.find((candidate) => candidate.id === raw.parent_id)
        : undefined;
    const cvTitles = Object.fromEntries(
      ((parentUser ?? raw)?.metadata_json?.attachments ?? []).map((entry) => [
        entry.cv_id,
        entry.title,
      ]),
    );
    // Persisted turn-failure marker (uniform chat error display): the
    // failed assistant turn renders as the error card from HISTORY —
    // surviving page refreshes — with regenerate + the settings deep-link.
    const turnFailed =
      raw?.role === "assistant"
        ? ((raw.metadata_json as
            | { turn_failed?: { code: string; detail: string } }
            | null
            | undefined)?.turn_failed ?? null)
        : null;
    if (turnFailed !== null) {
      return (
        <ChatMessage
          key={message.id}
          role="assistant"
          status="error"
          design="flat"
          avatar={avatar}
          content={null}
          error={{
            code: turnFailed.code,
            message: turnFailed.detail,
            retryable: parentUser !== undefined,
          }}
          actions={{
            onRetry:
              parentUser !== undefined
                ? () =>
                    void chat.regenerate(
                      message.parentId ?? "",
                      parentUser.content,
                    )
                : undefined,
            errorExtra: (
              <Link
                to="/settings/ai"
                className="inline-flex items-center rounded-[var(--as-radius-sm)] border border-current px-2 py-1 text-xs font-medium transition-colors hover:opacity-80"
              >
                {t("chat.openAiSettings")}
              </Link>
            ),
          }}
          labels={{ retry: t("chat.retryLabel") }}
        />
      );
    }
    return (
      <ChatMessage
        key={message.id}
        role={message.role}
        design="flat"
        avatar={avatar}
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
          onCopy: () => void copyText(message.content),
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
        chips={raw ? <ReferenceChips message={raw} cvTitles={cvTitles} /> : undefined}
        meta={
          raw && raw.role === "assistant" ? (
            <>
              <MessageTrace message={raw} />
              <MessageTemplatePreviews message={raw} />
              <MessagePathDraft message={raw} />
              <MessageProposals message={raw} density={density} />
            </>
          ) : undefined
        }
      />
    );
  };

  const live = chat.stream.live !== null;
  const failureKind = aiFailureKind(chat.stream.error?.code);
  const streamError =
    chat.stream.error !== null
      ? {
          ...chat.stream.error,
          message: failureKind
            ? t(aiFailureCopyKey(failureKind))
            : chat.stream.error.message,
        }
      : undefined;
  const proposalCards = useProfileProposalsStore((state) => state.live);
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
            renderResult={renderToolResult}
            durationMs={call.durationMs}
          />
        ))}
      </div>
    ) : null;
  const livePreviews = live ? <LiveTemplatePreviews /> : null;

  return (
    <ChatSelectionMenu>
      <ChatTranscript
        className="selection:bg-[color-mix(in_srgb,var(--as-accent)_22%,transparent)]"
        items={chat.viewMessages}
        design="flat"
        groupConsecutive
        renderItem={renderItem}
        emptyState={<ChatEmptyState variant={variant} />}
        live={
          live ? (
            <ChatMessage
              role="assistant"
              design="flat"
              avatar={<AssistantAvatar />}
              status={
                chat.stream.status === "interrupted"
                  ? "interrupted"
                  : chat.stream.status === "error"
                    ? "error"
                    : "streaming"
              }
              error={streamError}
              actions={
                chat.stream.error?.retryable
                  ? {
                      onRetry: () => void chat.retry(),
                      errorExtra:
                        failureKind === "unconfigured" ? (
                          <Link
                            to="/settings/ai"
                            className="inline-flex items-center rounded-[var(--as-radius-sm)] border border-current px-2 py-1 text-xs font-medium transition-colors hover:opacity-80"
                          >
                            {t("chat.openAiSettings")}
                          </Link>
                        ) : undefined,
                    }
                  : undefined
              }
              content={
                <>
                  {toolCards}
                  {livePreviews}
                  <ProposalCards cards={proposalCards} density={density} />
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
    </ChatSelectionMenu>
  );
}

function ComposerBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const chat = useCareerChatContext();
  const configSummary = useConfigSummary();
  const transcribeAssignment = configSummary.data?.tasks.find(
    (task) => task.task_type === "transcribe",
  );
  const dictationUnavailable =
    configSummary.error === null &&
    transcribeAssignment?.source === "unconfigured";
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

  // Reference chips + dictation share the composer's context strip —
  // rendered only when either has content (an always-truthy fragment
  // would leave an empty rail above the input).
  const openCvId = useOpenStudioCv();
  const dictationStrip =
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
    ) : undefined;
  const attachStripVisible =
    chat.attachments.length > 0 || openCvId !== null;

  // Quiet mic: when speech-to-text is unconfigured the mic stays visible
  // in its muted state and explains itself on demand — no persistent
  // notice competing with the draft.
  const mic = dictationUnavailable ? (
    <Popover>
      <PopoverTrigger asChild>
        <DictationButton
          unavailable
          status={dictation.status}
          onStart={() => void dictation.start()}
          unavailableLabel={t("dictation.unavailable")}
        />
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-72 p-2">
        <DictationUnavailable
          label={t("dictation.unavailable")}
          detail={t("dictation.notConfigured")}
          action={{
            label: t("dictation.openSettings"),
            onClick: () => navigate("/settings/ai?tab=tasks"),
          }}
        />
      </PopoverContent>
    </Popover>
  ) : micHidden ? undefined : (
    <DictationButton
      status={dictation.status}
      onStart={() => void dictation.start()}
    />
  );

  return (
    <ChatComposer
      value={chat.draft}
      onValueChange={chat.setDraft}
      onSubmit={() => void chat.submit()}
      sending={chat.sending}
      onStop={() => void chat.stream.stop()}
      placeholder={t("chat.composerPlaceholder")}
      toolbarStart={<CvAttachButton />}
      toolbarEnd={mic}
      suggestions={
        attachStripVisible || dictationStrip !== undefined ? (
          <>
            {attachStripVisible ? <CvAttachChips /> : null}
            {dictationStrip}
          </>
        ) : undefined
      }
    />
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
  const density: HitlDensity = variant === "page" ? "full" : "compact";
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
          <Button variant="ghost" size="sm" aria-label={t("chat.newChatAria")} onClick={() => useChatStore.getState().resetToDraft()}>
            <Plus className="size-4" />
          </Button>
          {onClose && (
            <Button variant="ghost" size="sm" aria-label={t("chat.closePanelAria")} onClick={onClose} title={t("chat.closeChat")}>
              <X className="size-4" />
            </Button>
          )}
        </>
      }
      transcript={<MessageList variant={variant} density={density} />}
      composer={<ComposerBar />}
    />
  );
}

export function ChatWidget() {
  const location = useLocation();
  const chatMode = useChatStore((state) => state.chatMode);
  const chatModeChosen = useChatStore((state) => state.chatModeChosen);

  useEffect(() => {
    if (location.pathname !== "/chat") {
      void useChatStore.getState().loadSessions();
    }
  }, [location.pathname]);

  // Another shape taking over closes the floating window; entering
  // /chat closes it on the page (ChatPage) so the close rides the
  // route commit instead of racing the switcher's navigation.
  useEffect(() => {
    if (chatMode !== "bubble") {
      useChatStore.getState().setBubbleOpen(false);
    }
  }, [chatMode]);

  if (
    location.pathname === "/chat" ||
    effectiveChatMode({ chatMode, chatModeChosen }, location.pathname) !== "bubble"
  ) {
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
 * top of the header actions and intercept their clicks. Open state
 * lives in the chat store, so opening the /chat page closes the
 * floating window and the page takes over its active conversation.
 */
function BubbleLauncher() {
  const { t } = useTranslation();
  const open = useChatStore((state) => state.bubbleOpen);
  const setBubbleOpen = useChatStore((state) => state.setBubbleOpen);
  return (
    <ChatLauncher
      label={t("chat.launcherLabel")}
      open={open}
      onOpenChange={setBubbleOpen}
      showClose={false}
      panel={<ChatSurface variant="bubble" onClose={() => setBubbleOpen(false)} />}
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
 * Closing the dock hands off to the bubble launcher (the quiet
 * re-open surface); only explicit user gestures switch chat mode.
 * The dock yields to the /chat page (never mounted beside it) while
 * chatMode persists — leaving the page brings the dock back with the
 * conversation it had, which the interview hand-off relies on.
 * Width-aware: above lg the dock never takes more than the viewport
 * minus the expanded sidebar and a ~20rem content floor (the page
 * column must stay usable); below lg it becomes a full-screen chat
 * overlay instead of stealing the whole flex row (which collapsed the
 * page to zero width).
 */
export function ChatDock() {
  const location = useLocation();
  const { t } = useTranslation();
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(CHAT_DOCK_WIDTH_KEY));
    return Number.isFinite(stored) && stored >= 320 ? clampChatWidth(stored) : 400;
  });
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  if (location.pathname === "/chat") {
    return null;
  }

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
      className="relative flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-l border-[var(--as-border)] bg-[var(--as-surface)] max-lg:fixed max-lg:inset-0 max-lg:z-40 max-lg:!w-full lg:max-w-[calc(100vw-36rem)]"
      style={{ width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("chat.resizeAria")}
        title={t("chat.resizeAria")}
        data-testid="chat-dock-resize-handle"
        className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize transition-colors hover:bg-[var(--as-accent)] max-lg:hidden"
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onPointerUp={onResizeEnd}
        onPointerCancel={onResizeEnd}
      />
      <CareerChatProvider>
        <ChatSurface
          variant="sidebar"
          onClose={() => useChatStore.getState().setChatMode("bubble")}
        />
      </CareerChatProvider>
    </aside>
  );
}
