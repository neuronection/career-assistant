import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Brain,
  ChevronDown,
  ChevronUp,
  GraduationCap,
  ListChecks,
  MessagesSquare,
  Plus,
  RefreshCw,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@neuronection/assistant-ui";
import { Button, Modal, ModalContent, ModalFooter, ModalHeader, ModalTitle } from "@/components/ui";
import { ComboboxField, SelectField } from "@/components/cv/formPrimitives";
import { apiDetail } from "@/api/client";
import { fetchJobs } from "@/api/jobs";
import {
  createInterviewSession,
  debriefInterviewSession,
  fetchInterviewSession,
  fetchInterviewSessions,
  patchInterviewPlan,
  retryInterviewWeakAreas,
  startInterviewSession,
} from "@/api/interview";
import { openInterviewChat } from "@/components/chat/interviewChatLink";
import type {
  InterviewKind,
  InterviewQuestion,
  InterviewSessionOut,
} from "@/types/interview";
import type { Job } from "@/types";

const KIND_OPTIONS: { value: InterviewKind; labelKey: string }[] = [
  { value: "mixed", labelKey: "interviews.kind.mixed" },
  { value: "technical", labelKey: "interviews.kind.technical" },
  { value: "behavioral", labelKey: "interviews.kind.behavioral" },
  { value: "research", labelKey: "interviews.kind.research" },
];

const KIND_ICONS: Record<string, LucideIcon> = {
  technical: Brain,
  behavioral: MessagesSquare,
  research: BookOpen,
};

const STATUS_TONES: Record<
  string,
  "secondary" | "ai" | "success" | "danger"
> = {
  planned: "secondary",
  active: "ai",
  completed: "success",
  abandoned: "danger",
};

export function Interviews() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<InterviewSessionOut[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InterviewSessionOut | null>(null);
  const [draft, setDraft] = useState<InterviewQuestion[]>([]);
  const [planDirty, setPlanDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    const rows = await fetchInterviewSessions();
    setSessions(rows);
    return rows;
  }, []);

  const openDetail = useCallback(async (id: string) => {
    const fresh = await fetchInterviewSession(id);
    setDetail(fresh);
    setDraft(fresh.plan);
    setPlanDirty(false);
    setSelectedId(id);
  }, []);

  useEffect(() => {
    void load()
      .then(async (rows) => {
        if (rows.length > 0) await openDetail(rows[0].id);
      })
      .catch((err) => setError(apiDetail(err)));
  }, [load, openDetail]);

  const editable = detail?.status === "planned" || detail?.status === "active";

  const moveDraft = (index: number, delta: -1 | 1) => {
    setDraft((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setPlanDirty(true);
  };

  const removeDraft = (id: string) => {
    setDraft((prev) => prev.filter((item) => item.id !== id));
    setPlanDirty(true);
  };

  const savePlan = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const updated = await patchInterviewPlan(detail.id, draft);
      setDetail(updated);
      setDraft(updated.plan);
      setPlanDirty(false);
      void load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const practice = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const started =
        detail.chat_session_id != null
          ? detail
          : await startInterviewSession(detail.id);
      setDetail(started);
      await openInterviewChat(started.chat_session_id as string, "docked");
      navigate("/chat");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const runDebrief = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const updated = await debriefInterviewSession(detail.id);
      setDetail(updated);
      void load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const created = await retryInterviewWeakAreas(detail.id);
      await load();
      await openDetail(created.id);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const answeredCount = detail?.rubric_scores.length ?? 0;

  return (
    <div
      className="flex min-h-0 flex-col gap-3 lg:h-full"
      data-testid="interviews-page"
    >
      <div
        className="flex shrink-0 flex-wrap items-center justify-between gap-3"
        data-testid="interviews-toolbar"
      >
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
            <GraduationCap className="h-5 w-5" aria-hidden />{" "}
            {t("interviews.title")}
          </h1>
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
            {t("interviews.subtitle")}
          </p>
        </div>
        <Button
          variant="default"
          onClick={() => setCreateOpen(true)}
          data-testid="add-interview"
        >
          <Plus className="mr-1 h-4 w-4" aria-hidden /> {t("interviews.newSession")}
        </Button>
      </div>

      {error && (
        <p role="alert" className="shrink-0 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)] lg:gap-4">
        <div
          className="cv-pane-enter min-h-0 flex-col gap-2.5 overflow-y-auto lg:flex"
          data-testid="interviews-rail"
        >
          {sessions.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
              {t("interviews.emptyRail")}
            </p>
          ) : (
            sessions.map((session) => (
              <article
                key={session.id}
                className={`group cursor-pointer rounded-xl border p-3 transition-colors duration-150 ${
                  session.id === selectedId
                    ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)]"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
                }`}
                data-testid={`interview-session-${session.id}`}
                onClick={() => void openDetail(session.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-[var(--as-fg)]">
                    {session.role_label}
                  </span>
                  <Badge variant={STATUS_TONES[session.status] ?? "secondary"}>
                    {t(`interviews.status.${session.status}`, {
                      defaultValue: session.status,
                    })}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
                  {t(`interviews.kind.${session.kind}`, {
                    defaultValue: session.kind,
                  })}{" "}
                  ·{" "}
                  {t("interviews.questionsCount", {
                    count: session.plan.length,
                  })}
                  {session.debrief
                    ? ` · ${session.debrief.aggregate.structure}/` +
                      `${session.debrief.aggregate.evidence}/` +
                      `${session.debrief.aggregate.clarity}`
                    : ""}
                </p>
              </article>
            ))
          )}
        </div>

        <div
          className="cv-pane-enter min-h-0 flex-col overflow-y-auto rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] outline-none lg:flex"
          data-testid="interview-detail"
        >
          {!detail ? (
            <div className="flex min-h-0 flex-1 items-center justify-center p-6">
              <p className="text-sm text-[var(--as-muted-fg)]">
                {t("interviews.pickSession")}
              </p>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-2xl space-y-5 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-[var(--as-fg)]">
                    {detail.role_label}
                  </h2>
                  <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
                    {t(`interviews.kind.${detail.kind}`, {
                      defaultValue: detail.kind,
                    })}{" "}
                    ·{" "}
                    {t("interviews.answeredCount", {
                      answered: answeredCount,
                      total: detail.plan.length,
                    })}
                  </p>
                </div>
                <div className="flex gap-2">
                  {detail.status !== "completed" && (
                    <Button
                      variant="default"
                      size="sm"
                      disabled={busy}
                      onClick={() => void practice()}
                      data-testid="practice-interview"
                    >
                      <MessagesSquare className="mr-1 h-3.5 w-3.5" aria-hidden />
                      {answeredCount > 0
                        ? t("interviews.resumePractice")
                        : t("interviews.practice")}
                    </Button>
                  )}
                  {detail.status === "completed" && !detail.debrief && (
                    <Button
                      variant="default"
                      size="sm"
                      disabled={busy}
                      onClick={() => void runDebrief()}
                      data-testid="generate-debrief"
                    >
                      <ListChecks className="mr-1 h-3.5 w-3.5" aria-hidden />
                      {t("interviews.debrief")}
                    </Button>
                  )}
                </div>
              </div>

              <section className="space-y-2" data-testid="interview-plan">
                <p className="text-xs font-semibold text-[var(--as-fg)]">
                  {t("interviews.questionPlan")}
                  {planDirty && t("interviews.unsavedSuffix")}
                </p>
                {draft.map((item, index) => {
                  const Icon = KIND_ICONS[item.kind] ?? ListChecks;
                  return (
                    <article
                      key={item.id}
                      className="rounded-lg border border-[var(--as-border)] p-3"
                      data-testid={`plan-item-${item.id}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="flex min-w-0 items-start gap-2">
                          <Icon
                            className="mt-0.5 h-4 w-4 shrink-0 text-[var(--as-muted-fg)]"
                            aria-hidden
                          />
                          <span className="min-w-0">
                            <span className="block text-sm text-[var(--as-fg)]">
                              {item.question}
                            </span>
                            <span className="mt-0.5 block text-xs text-[var(--as-muted-fg)]">
                              {t(`interviews.kind.${item.kind}`, {
                                defaultValue: item.kind,
                              })}
                              {item.skill_label
                                ? ` · ${item.skill_label}`
                                : ""}
                              {item.target_level != null
                                ? ` · ${t("interviews.levelTag", {
                                    level: item.target_level,
                                  })}`
                                : ""}
                              {answeredCount > index &&
                              detail.rubric_scores.some(
                                (row) =>
                                  (row as { question_id?: string })
                                    .question_id === item.id
                              )
                                ? ` · ${t("interviews.answeredTag")}`
                                : ""}
                            </span>
                          </span>
                        </span>
                        {editable && (
                          <span className="flex shrink-0 items-center gap-1">
                            <button
                              type="button"
                              aria-label={t("interviews.moveUp")}
                              data-testid={`plan-up-${item.id}`}
                              className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                              onClick={() => moveDraft(index, -1)}
                            >
                              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
                            </button>
                            <button
                              type="button"
                              aria-label={t("interviews.moveDown")}
                              data-testid={`plan-down-${item.id}`}
                              className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                              onClick={() => moveDraft(index, 1)}
                            >
                              <ChevronDown
                                className="h-3.5 w-3.5"
                                aria-hidden
                              />
                            </button>
                            <button
                              type="button"
                              aria-label={t("interviews.removeQuestion")}
                              data-testid={`plan-remove-${item.id}`}
                              className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] hover:text-[var(--as-danger)]"
                              onClick={() => removeDraft(item.id)}
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden />
                            </button>
                          </span>
                        )}
                      </div>
                    </article>
                  );
                })}
                {planDirty && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => void savePlan()}
                    data-testid="save-plan"
                  >
                    {t("interviews.savePlan")}
                  </Button>
                )}
              </section>

              {detail.debrief && (
                <section
                  className="space-y-3 rounded-lg border border-[var(--as-border)] p-4"
                  data-testid="interview-debrief"
                >
                  <p className="text-xs font-semibold text-[var(--as-fg)]">
                    {t("interviews.debrief")}
                  </p>
                  <div
                    className="flex flex-wrap gap-2"
                    data-testid="debrief-aggregate"
                  >
                    <Badge variant="secondary">
                      {t("interviews.structure", {
                        score: detail.debrief.aggregate.structure,
                      })}
                    </Badge>
                    <Badge variant="secondary">
                      {t("interviews.evidence", {
                        score: detail.debrief.aggregate.evidence,
                      })}
                    </Badge>
                    <Badge variant="secondary">
                      {t("interviews.clarity", {
                        score: detail.debrief.aggregate.clarity,
                      })}
                    </Badge>
                  </div>
                  <p className="text-sm text-[var(--as-fg)]">
                    {detail.debrief.summary}
                  </p>
                  <DebriefList
                    title={t("interviews.strengths")}
                    items={detail.debrief.strengths}
                    testid="debrief-strengths"
                  />
                  <DebriefList
                    title={t("interviews.gaps")}
                    items={detail.debrief.gaps}
                    testid="debrief-gaps"
                  />
                  <DebriefList
                    title={t("interviews.recommendations")}
                    items={detail.debrief.recommendations}
                    testid="debrief-recommendations"
                  />
                  {detail.debrief.resources.length > 0 && (
                    <div data-testid="debrief-resources">
                      <p className="text-xs font-semibold text-[var(--as-fg)]">
                        {t("interviews.resources")}
                      </p>
                      <ul className="mt-1 space-y-1">
                        {detail.debrief.resources.map((resource) => (
                          <li key={resource.url} className="text-xs">
                            <a
                              href={resource.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-primary-700 hover:underline"
                            >
                              {resource.title}
                            </a>
                            {resource.provider ? ` — ${resource.provider}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => void retry()}
                    data-testid="retry-weak"
                  >
                    <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden />
                    {t("interviews.retryWeak")}
                  </Button>
                </section>
              )}
            </div>
          )}
        </div>
      </div>

      <CreateSessionModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(created) => {
          setCreateOpen(false);
          void load().then(() => openDetail(created.id));
        }}
        onError={setError}
      />
    </div>
  );
}

function DebriefList({
  title,
  items,
  testid,
}: {
  title: string;
  items: string[];
  testid: string;
}) {
  if (items.length === 0) return null;
  return (
    <div data-testid={testid}>
      <p className="text-xs font-semibold text-[var(--as-fg)]">{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">
        {items.map((item) => (
          <li key={item} className="text-xs text-[var(--as-muted-fg)]">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CreateSessionModal({
  open,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (session: InterviewSessionOut) => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [kind, setKind] = useState("mixed");
  const [jobCode, setJobCode] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || jobs.length > 0) return;
    void fetchJobs()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, [open, jobs.length]);

  const jobOptions = useMemo(
    () => jobs.map((job) => ({ value: job.code, label: job.title })),
    [jobs]
  );

  const create = async () => {
    setBusy(true);
    setError("");
    onError("");
    try {
      const created = await createInterviewSession({
        job_code: jobCode,
        kind: kind as InterviewKind,
      });
      onCreated(created);
    } catch (err) {
      const detail = apiDetail(err);
      setError(detail);
      onError(detail);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("interviews.modalTitle")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <SelectField
            label={t("interviews.focus")}
            value={kind}
            options={KIND_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey),
            }))}
            onChange={setKind}
            testId="interview-kind"
          />
          <ComboboxField
            label={t("interviews.catalogRole")}
            value={jobCode}
            onChange={setJobCode}
            options={jobOptions}
            allowCreate
            createLabel={(term) => t("interviews.useCode", { code: term })}
            hint={t("interviews.roleHint")}
            testId="interview-job"
          />
          {error && (
            <p role="alert" className="text-sm text-[var(--as-danger)]">
              {error}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>
            <X className="mr-1 h-3.5 w-3.5" aria-hidden /> {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void create()}
            disabled={busy || jobCode.trim().length === 0}
            data-testid="create-interview"
          >
            {busy ? t("interviews.preparing") : t("interviews.createPlan")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
