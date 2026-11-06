import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { Bell, CalendarClock, KanbanSquare, List, Settings2 } from "lucide-react";
import { Input } from "@neuronection/assistant-ui";

import { fetchApplications } from "@/api/applications";
import { apiDetail } from "@/api/client";
import { ApplicationDrawer } from "@/features/postings/components/applications/ApplicationDrawer";
import { FollowupRulesCard } from "@/features/postings/components/applications/FollowupRulesCard";
import { Button, EmptyState, PanelModal, Spinner } from "@/components/ui";
import { isUnread, markSeen } from "@/lib/applicationSeen";
import type { Application, ApplicationList } from "@/types/application";

const BOARD_STAGES = [
  "applied",
  "screening",
  "interview",
  "offer",
  "accepted",
  "closed",
] as const;

type BoardStage = (typeof BOARD_STAGES)[number];

function formatDate(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleDateString();
}

function columnOf(application: Application): BoardStage {
  if (application.stage === "rejected" || application.stage === "withdrawn") {
    return "closed";
  }
  return application.stage as BoardStage;
}

function DocThumb({ cvId, label }: { cvId: string; label: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      src={`/api/v1/cv/${cvId}/preview.png`}
      alt={label}
      title={label}
      decoding="async"
      loading="lazy"
      className="h-11 w-8 rounded border border-[var(--as-border)] bg-[var(--as-surface)] object-cover object-top"
      onError={() => setFailed(true)}
    />
  );
}

function StageChip({ application }: { application: Application }) {
  const { t } = useTranslation();
  const key =
    application.stage === "rejected" || application.stage === "withdrawn"
      ? application.outcome ?? application.stage
      : application.stage;
  return (
    <span
      className="rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--as-fg)]"
      data-testid={`application-stage-chip-${application.stage}`}
    >
      {t(`applications.stage.${key}`, { defaultValue: key })}
    </span>
  );
}

function ApplicationCard({
  application,
  onOpen,
}: {
  application: Application;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const unread = isUnread(application.id, application.updated_at);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`application-card-${application.id}`}
      className="w-full space-y-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-left transition-colors hover:border-[var(--as-accent)]"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[var(--as-fg)]">
            {application.posting_title}
          </p>
          <p className="truncate text-xs text-[var(--as-muted-fg)]">
            {application.posting_org}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {unread && (
            <span
              aria-label={t("applications.unread")}
              data-testid={`application-unread-${application.id}`}
              className="size-2 rounded-full bg-[var(--as-accent)]"
            />
          )}
          <StageChip application={application} />
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-1 text-[10px] text-[var(--as-muted-fg)]">
        <div>
          <dt className="uppercase tracking-wide">{t("applications.applied")}</dt>
          <dd className="text-[var(--as-fg)]">{formatDate(application.applied_at)}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">{t("applications.deadline")}</dt>
          <dd className="text-[var(--as-fg)]">{formatDate(application.deadline_at)}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">{t("applications.nextFollowup")}</dt>
          <dd className="text-[var(--as-fg)]">
            {formatDate(application.next_followup_at)}
          </dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">{t("applications.updated")}</dt>
          <dd className="text-[var(--as-fg)]">{formatDate(application.updated_at)}</dd>
        </div>
      </dl>
      <div className="flex items-center gap-2">
        {application.cv_id !== null && (
          <DocThumb cvId={application.cv_id} label={t("applications.cv")} />
        )}
        {application.cover_letter_id !== null && (
          <DocThumb
            cvId={application.cover_letter_id}
            label={t("applications.coverLetter")}
          />
        )}
      </div>
    </button>
  );
}

export function Applications() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<"board" | "list">("board");
  const [data, setData] = useState<ApplicationList | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [seenRevision, setSeenRevision] = useState(0);

  const activeId = params.get("application");

  const load = useCallback(async () => {
    const next = await fetchApplications({ q: query.trim() === "" ? undefined : query.trim() });
    setData(next);
  }, [query]);

  useEffect(() => {
    void load().catch((exc) => setError(apiDetail(exc)));
  }, [load, seenRevision]);

  const openDrawer = (id: string) => {
    const application = data?.items.find((item) => item.id === id);
    if (application !== undefined) markSeen(application.id, application.updated_at);
    setSeenRevision((value) => value + 1);
    setParams({ application: id });
  };

  const closeDrawer = (open: boolean) => {
    if (!open) {
      setParams({});
      setSeenRevision((value) => value + 1);
    }
  };

  const items = data?.items ?? [];
  const grouped = useMemo(() => {
    const map = new Map<BoardStage, Application[]>();
    for (const stage of BOARD_STAGES) map.set(stage, []);
    for (const application of items) map.get(columnOf(application))?.push(application);
    return map;
  }, [items]);

  return (
    <div
      className="ca-workspace flex min-h-0 flex-col gap-3 lg:h-full"
      data-testid="applications-page"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
          <KanbanSquare className="size-5 text-[var(--as-accent)]" aria-hidden />
          {t("applications.title")}
        </h1>
        <span className="text-sm text-[var(--as-muted-fg)]" data-testid="applications-total">
          {t("applications.count", { count: data?.total ?? 0 })}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("applications.searchPlaceholder")}
            aria-label={t("applications.searchPlaceholder")}
            data-testid="applications-search"
            className="w-48"
          />
          <div
            className="inline-flex rounded-full border border-[var(--as-border)] p-0.5"
            role="group"
            aria-label={t("applications.viewLabel")}
          >
            <button
              type="button"
              aria-pressed={view === "board"}
              data-testid="applications-view-board"
              onClick={() => setView("board")}
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition-colors ${
                view === "board"
                  ? "bg-[var(--as-accent)] text-white"
                  : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              }`}
            >
              <KanbanSquare className="size-3.5" aria-hidden />
              {t("applications.board")}
            </button>
            <button
              type="button"
              aria-pressed={view === "list"}
              data-testid="applications-view-list"
              onClick={() => setView("list")}
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition-colors ${
                view === "list"
                  ? "bg-[var(--as-accent)] text-white"
                  : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              }`}
            >
              <List className="size-3.5" aria-hidden />
              {t("applications.list")}
            </button>
          </div>
          <Button
            variant="outline"
            size="sm"
            data-testid="applications-followup-settings"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings2 className="mr-1 size-3.5" aria-hidden />
            {t("applications.followupSettings")}
          </Button>
        </div>
      </div>

      {data !== null && data.next_followup_at !== null && (
        <p
          className="flex items-center gap-1.5 text-xs text-[var(--as-muted-fg)]"
          data-testid="applications-next-followup"
        >
          <CalendarClock className="size-3.5" aria-hidden />
          {t("applications.nextNudge", {
            date: new Date(data.next_followup_at).toLocaleDateString(),
          })}
        </p>
      )}

      {error !== null && (
        <p className="text-sm text-rose-600" data-testid="applications-error">
          {error}
        </p>
      )}

      {data === null ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            icon={Bell}
            title={t("applications.emptyTitle")}
            description={t("applications.emptyBody")}
            action={
              <Link to="/postings" className="text-sm text-[var(--as-accent)]">
                {t("applications.browsePostings")}
              </Link>
            }
          />
        </div>
      ) : view === "board" ? (
        <div
          className="min-h-0 flex-1 overflow-x-auto pb-2"
          data-testid="applications-board"
        >
          <div className="grid h-full auto-cols-[minmax(220px,1fr)] grid-flow-col gap-3">
            {BOARD_STAGES.map((stage) => {
              const column = grouped.get(stage) ?? [];
              return (
                <section
                  key={stage}
                  className="flex min-h-0 flex-col rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-2"
                  data-testid={`board-column-${stage}`}
                >
                  <header className="flex items-center justify-between px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    <span>{t(`applications.stage.${stage}`)}</span>
                    <span data-testid={`board-count-${stage}`}>{column.length}</span>
                  </header>
                  <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
                    {column.map((application) => (
                      <ApplicationCard
                        key={application.id}
                        application={application}
                        onOpen={() => openDrawer(application.id)}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      ) : (
        <div
          className="min-h-0 flex-1 overflow-y-auto rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)]"
          data-testid="applications-list"
        >
          {items.map((application) => {
            const unread = isUnread(application.id, application.updated_at);
            return (
              <button
                key={application.id}
                type="button"
                onClick={() => openDrawer(application.id)}
                data-testid={`application-row-${application.id}`}
                className="grid w-full grid-cols-[1.4fr_0.8fr_0.7fr_0.7fr_0.7fr] items-center gap-2 border-b border-[var(--as-border)] px-3 py-2 text-left text-xs transition-colors last:border-b-0 hover:bg-[var(--as-muted)]"
              >
                <span className="flex min-w-0 items-center gap-2">
                  {unread && (
                    <span
                      aria-label={t("applications.unread")}
                      className="size-2 shrink-0 rounded-full bg-[var(--as-accent)]"
                    />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-[var(--as-fg)]">
                      {application.posting_title}
                    </span>
                    <span className="block truncate text-[var(--as-muted-fg)]">
                      {application.posting_org}
                    </span>
                  </span>
                </span>
                <span>
                  <StageChip application={application} />
                </span>
                <span className="text-[var(--as-fg)]">
                  {formatDate(application.applied_at)}
                </span>
                <span className="text-[var(--as-fg)]">
                  {formatDate(application.deadline_at)}
                </span>
                <span className="text-[var(--as-fg)]">
                  {formatDate(application.next_followup_at)}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <ApplicationDrawer
        applicationId={activeId}
        open={activeId !== null}
        onOpenChange={closeDrawer}
        onChanged={() => void load()}
      />

      <PanelModal
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title={t("applications.followupSettings")}
        size="md"
      >
        <FollowupRulesCard />
      </PanelModal>
    </div>
  );
}
