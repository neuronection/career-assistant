import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { FileText, Mail, Target } from "lucide-react";

import { Badge, Button, EmptyState } from "@/components/ui";
import type { ApplicationKitEvent } from "@/types/wire";
import type { ApplicationKit } from "@/types/wire";

const KIND_ICONS: Record<string, string> = {
  stage_change: "↗",
  note: "✎",
  document_linked: "📎",
  followup_sent: "🔔",
  followup_snoozed: "⏰",
  interview_scheduled: "🗓",
  offer_received: "🎉",
  external_update: "⇄",
  imported: "⤓",
};

function EventRow({
  event,
  stageLabel,
}: {
  event: ApplicationKitEvent;
  stageLabel: (stage: string) => string;
}) {
  const { t } = useTranslation();
  return (
    <li
      className="flex gap-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-2"
      data-testid={`kit-event-${event.kind}`}
    >
      <span aria-hidden className="text-sm">
        {KIND_ICONS[event.kind] ?? "•"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-[var(--as-fg)]">
          {event.kind === "stage_change"
            ? t("applications.eventStage", {
                from:
                  event.stage_from == null
                    ? t("applications.tracked")
                    : stageLabel(event.stage_from),
                to: stageLabel(event.stage_to ?? ""),
              })
            : event.body || t(`applications.event.${event.kind}`)}
        </p>
        <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
          {new Date(event.at).toLocaleString()} · {event.actor}
        </p>
      </div>
    </li>
  );
}

/** The kit's timeline tab. With an application: the newest-first event
 * timeline plus the linked documents. Without one (the pre-application
 * kit): the honest "not tracked yet" state and the explicit action. */
export function KitTimelineTab({
  kit,
  stageLabel,
  markAppliedAction,
}: {
  kit: ApplicationKit | null;
  stageLabel: (stage: string) => string;
  markAppliedAction?: React.ReactNode;
}) {
  const { t } = useTranslation();
  if (kit === null) {
    return (
      <div className="py-6" data-testid="kit-timeline-untracked">
        <EmptyState
          icon={Target}
          title={t("applications.kit.timeline.notTrackedTitle")}
          description={t("applications.kit.timeline.notTrackedBody")}
          action={markAppliedAction}
        />
      </div>
    );
  }
  const documents = kit.documents ?? {};
  return (
    <div className="space-y-4 py-3" data-testid="kit-timeline-tab">
      <section className="flex flex-wrap items-center gap-2">
        <Badge variant="default" data-testid="kit-stage-chip">
          {stageLabel(kit.application?.stage ?? "applied")}
        </Badge>
        <span className="text-xs text-[var(--as-muted-fg)]">
          {t("applications.kit.timeline.appliedOn", {
            date: kit.application?.applied_at
              ? new Date(kit.application.applied_at).toLocaleDateString()
              : "—",
          })}
        </span>
        {documents.cv != null && (
          <Button asChild size="sm" variant="outline">
            <Link to={`/cv/${documents.cv.id}`} data-testid="kit-doc-cv">
              <FileText className="mr-1 size-3.5" aria-hidden />
              {documents.cv.title || t("applications.cv")}
            </Link>
          </Button>
        )}
        {documents.cover_letter != null && (
          <Button asChild size="sm" variant="outline">
            <Link to={`/cv/${documents.cover_letter.id}`} data-testid="kit-doc-letter">
              <Mail className="mr-1 size-3.5" aria-hidden />
              {documents.cover_letter.title || t("applications.coverLetter")}
            </Link>
          </Button>
        )}
      </section>
      {(kit.timeline ?? []).length === 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]">{t("applications.timelineEmpty")}</p>
      ) : (
        <ol className="space-y-2">
          {(kit.timeline ?? []).map((event) => (
            <EventRow key={event.id} event={event} stageLabel={stageLabel} />
          ))}
        </ol>
      )}
      {kit.timeline_truncated && (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="kit-timeline-truncated">
          {t("applications.kit.timeline.truncated")}
        </p>
      )}
    </div>
  );
}
