import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "@neuronection/assistant-ui/textarea";

import {
  addApplicationNote,
  closeApplication,
  fetchApplication,
  linkApplicationDocument,
  snoozeApplicationFollowup,
  transitionApplication,
} from "@/api/applications";
import { fetchCvs } from "@/api/cv";
import { apiDetail } from "@/api/client";
import { Button, PanelModal, Spinner } from "@/components/ui";
import { SelectField, StepperRow, TextareaField } from "@/components/cv/formPrimitives";
import type {
  ApplicationDetail,
  ApplicationOutcome,
  ApplicationStage,
} from "@/types/application";
import type { CvDocumentOut } from "@/types/cv";

const STAGES: ApplicationStage[] = [
  "applied",
  "screening",
  "interview",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
];

const OUTCOMES: ApplicationOutcome[] = [
  "accepted",
  "rejected",
  "withdrawn",
  "expired",
  "ghosted",
];

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

function stageLabel(stage: string, t: (key: string) => string): string {
  return t(`applications.stage.${stage}`);
}

/** The application detail drawer (plan 116.4): reverse-chron timeline,
 * note composer, stage control, document links, follow-up snooze and
 * close-with-outcome. Every mutation resolves through the service API. */
export function ApplicationDrawer({
  applicationId,
  open,
  onOpenChange,
  onChanged,
}: {
  applicationId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [cvs, setCvs] = useState<CvDocumentOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<ApplicationStage>("applied");
  const [note, setNote] = useState("");
  const [snoozeDays, setSnoozeDays] = useState(7);
  const [outcome, setOutcome] = useState<ApplicationOutcome>("rejected");
  const [closeNote, setCloseNote] = useState("");
  const [cvId, setCvId] = useState("");
  const [coverLetterId, setCoverLetterId] = useState("");

  useEffect(() => {
    if (applicationId === null) {
      setDetail(null);
      return;
    }
    void fetchApplication(applicationId)
      .then((row) => {
        setDetail(row);
        setStage(row.stage);
        setCvId(row.cv_id ?? "");
        setCoverLetterId(row.cover_letter_id ?? "");
      })
      .catch((exc) => setError(apiDetail(exc)));
  }, [applicationId]);

  useEffect(() => {
    if (!open) return;
    void fetchCvs()
      .then(setCvs)
      .catch(() => setCvs([]));
  }, [open]);

  const resumes = useMemo(() => cvs.filter((cv) => cv.kind !== "cover_letter"), [cvs]);
  const letters = useMemo(() => cvs.filter((cv) => cv.kind === "cover_letter"), [cvs]);

  const run = async (action: () => Promise<ApplicationDetail>) => {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      setDetail(next);
      setStage(next.stage);
      setCvId(next.cv_id ?? "");
      setCoverLetterId(next.cover_letter_id ?? "");
      onChanged();
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(false);
    }
  };

  const timeline = detail?.timeline ?? [];

  return (
    <PanelModal
      open={open}
      onOpenChange={onOpenChange}
      title={detail?.posting_title ?? t("applications.drawerTitle")}
      size="lg"
      data-testid="application-drawer"
    >
      {detail === null ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <div className="space-y-5" data-testid="application-drawer-body">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-[var(--as-muted-fg)]">
              {detail.posting_org}
            </span>
            <span
              className="rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-fg)]"
              data-testid="application-drawer-stage"
            >
              {stageLabel(detail.stage, t)}
            </span>
            {detail.outcome !== null && (
              <span className="rounded-full bg-[var(--as-surface-raised)] px-2 py-0.5 text-xs text-[var(--as-muted-fg)]">
                {t(`applications.outcome.${detail.outcome}`)}
              </span>
            )}
          </div>

          <section className="grid gap-3 sm:grid-cols-3">
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("applications.appliedOn")}{" "}
              <span className="text-[var(--as-fg)]">
                {detail.applied_at ? new Date(detail.applied_at).toLocaleDateString() : "—"}
              </span>
            </p>
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("applications.deadlineOn")}{" "}
              <span className="text-[var(--as-fg)]">
                {detail.deadline_at ? new Date(detail.deadline_at).toLocaleDateString() : "—"}
              </span>
            </p>
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("applications.nextFollowup")}{" "}
              <span className="text-[var(--as-fg)]">
                {detail.next_followup_at
                  ? new Date(detail.next_followup_at).toLocaleDateString()
                  : "—"}
              </span>
            </p>
          </section>

          <section className="space-y-2" data-testid="application-stage-control">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.moveStage")}
            </h3>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <SelectField
                  label={t("applications.stageLabel")}
                  value={stage}
                  onChange={(value) => setStage(value as ApplicationStage)}
                  options={STAGES.map((value) => ({
                    value,
                    label: stageLabel(value, t),
                  }))}
                  testId="application-stage-select"
                />
              </div>
              <Button
                size="sm"
                disabled={busy || stage === detail.stage}
                data-testid="application-stage-save"
                onClick={() => void run(() => transitionApplication(detail.id, stage))}
              >
                {t("applications.move")}
              </Button>
            </div>
          </section>

          <section className="space-y-2" data-testid="application-note">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.addNote")}
            </h3>
            <Textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={t("applications.notePlaceholder")}
              aria-label={t("applications.notePlaceholder")}
              data-testid="application-note-input"
              rows={3}
            />
            <Button
              size="sm"
              disabled={busy || note.trim() === ""}
              data-testid="application-note-save"
              onClick={() =>
                void run(async () => {
                  const next = await addApplicationNote(detail.id, note.trim());
                  setNote("");
                  return next;
                })
              }
            >
              {t("applications.saveNote")}
            </Button>
          </section>

          <section className="space-y-2" data-testid="application-documents">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.documents")}
            </h3>
            <div className="grid gap-2 sm:grid-cols-2">
              <SelectField
                label={t("applications.cv")}
                value={cvId}
                onChange={setCvId}
                options={[
                  { value: "", label: t("applications.noDocument") },
                  ...resumes.map((cv) => ({ value: cv.id, label: cv.title })),
                ]}
                testId="application-cv-select"
              />
              <SelectField
                label={t("applications.coverLetter")}
                value={coverLetterId}
                onChange={setCoverLetterId}
                options={[
                  { value: "", label: t("applications.noDocument") },
                  ...letters.map((cv) => ({ value: cv.id, label: cv.title })),
                ]}
                testId="application-letter-select"
              />
            </div>
            <Button
              size="sm"
              disabled={busy || (cvId === "" && coverLetterId === "")}
              data-testid="application-docs-save"
              onClick={() =>
                void run(() =>
                  linkApplicationDocument(detail.id, {
                    cv_id: cvId === "" ? null : cvId,
                    cover_letter_id: coverLetterId === "" ? null : coverLetterId,
                  })
                )
              }
            >
              {t("applications.linkDocuments")}
            </Button>
          </section>

          <section className="space-y-2" data-testid="application-followup">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.followup")}
            </h3>
            <StepperRow
              label={t("applications.snoozeDays")}
              value={snoozeDays}
              min={1}
              max={120}
              onChange={setSnoozeDays}
            />
            <Button
              size="sm"
              disabled={busy || detail.closed_at !== null}
              data-testid="application-snooze-save"
              onClick={() => void run(() => snoozeApplicationFollowup(detail.id, snoozeDays))}
            >
              {t("applications.snooze")}
            </Button>
          </section>

          <section className="space-y-2" data-testid="application-close">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.closeTitle")}
            </h3>
            <SelectField
              label={t("applications.outcomeLabel")}
              value={outcome}
              onChange={(value) => setOutcome(value as ApplicationOutcome)}
              options={OUTCOMES.map((value) => ({
                value,
                label: t(`applications.outcome.${value}`),
              }))}
              testId="application-close-outcome"
            />
            <TextareaField
              label={t("applications.closeNote")}
              value={closeNote}
              onChange={setCloseNote}
              rows={2}
              testId="application-close-note"
            />
            <Button
              variant="destructive"
              size="sm"
              disabled={busy || detail.closed_at !== null}
              data-testid="application-close-save"
              onClick={() =>
                void run(async () => {
                  const next = await closeApplication(
                    detail.id,
                    outcome,
                    closeNote.trim()
                  );
                  setCloseNote("");
                  return next;
                })
              }
            >
              {t("applications.closeApplication")}
            </Button>
          </section>

          {error !== null && (
            <p className="text-xs text-rose-600" data-testid="application-error">
              {error}
            </p>
          )}

          <section className="space-y-2" data-testid="application-timeline">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.timeline")}
            </h3>
            {timeline.length === 0 ? (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.timelineEmpty")}
              </p>
            ) : (
              <ol className="space-y-2">
                {timeline.map((event) => (
                  <li
                    key={event.id}
                    className="flex gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2"
                    data-testid={`application-event-${event.kind}`}
                  >
                    <span aria-hidden className="text-sm">
                      {KIND_ICONS[event.kind] ?? "•"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-[var(--as-fg)]">
                        {event.kind === "stage_change"
                          ? t("applications.eventStage", {
                              from:
                                event.stage_from === null
                                  ? t("applications.tracked")
                                  : stageLabel(event.stage_from, t),
                              to: stageLabel(event.stage_to ?? "", t),
                            })
                          : event.body || t(`applications.event.${event.kind}`)}
                      </p>
                      <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                        {new Date(event.at).toLocaleString()} · {event.actor}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      )}
    </PanelModal>
  );
}
