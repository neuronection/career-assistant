import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { PackageCheck } from "lucide-react";
import { Textarea } from "@neuronection/assistant-ui/textarea";

import {
  addApplicationNote,
  clearApplicationOffer,
  closeApplication,
  fetchApplication,
  linkApplicationDocument,
  setApplicationOffer,
  snoozeApplicationFollowup,
  transitionApplication,
} from "@/api/applications";
import { fetchCvs } from "@/api/cv";
import { fetchContacts, setApplicationContact, type Contact } from "@/api/contacts";
import { apiDetail } from "@/api/client";
import { Button, PanelModal, Spinner } from "@/components/ui";
import { SelectField, StepperRow, TextareaField } from "@/features/cv/components/cv/formPrimitives";
import type {
  ApplicationDetail,
  ApplicationOffer,
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
interface OfferForm {
  currency: string;
  amount: string;
  period: ApplicationOffer["period"];
  benefits: string;
  location: string;
  cost_of_living: string;
  deadline: string;
}

const EMPTY_OFFER: OfferForm = {
  currency: "EUR",
  amount: "",
  period: "year",
  benefits: "",
  location: "",
  cost_of_living: "",
  deadline: "",
};

function offerFormFrom(offer: Partial<ApplicationOffer>): OfferForm {
  return {
    currency: offer.currency ?? "EUR",
    amount: offer.amount == null ? "" : String(offer.amount),
    period: offer.period ?? "year",
    benefits: (offer.benefits ?? []).join(", "),
    location: offer.location ?? "",
    cost_of_living:
      offer.cost_of_living == null ? "" : String(offer.cost_of_living),
    deadline: offer.deadline ?? "",
  };
}

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
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactId, setContactId] = useState("");
  const [offerForm, setOfferForm] = useState<OfferForm>(EMPTY_OFFER);

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
        setContactId(row.contact_id ?? "");
        setOfferForm(offerFormFrom(row.offer));
      })
      .catch((exc) => setError(apiDetail(exc)));
  }, [applicationId]);

  useEffect(() => {
    if (!open) return;
    void fetchContacts()
      .then(setContacts)
      .catch(() => setContacts([]));
  }, [open]);

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
      setOfferForm(offerFormFrom(next.offer));
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
            <Link
              to={`/applications/${detail.id}`}
              className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-[var(--as-accent)] hover:underline"
              data-testid="application-drawer-kit"
            >
              <PackageCheck className="size-3.5" aria-hidden />
              {t("applications.kit.drawerAction")}
            </Link>
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

          <section className="space-y-2" data-testid="application-contact">
            <h3 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("applications.contactTitle")}
            </h3>
            <select
              value={contactId}
              onChange={(event) => {
                const next = event.target.value;
                setContactId(next);
                void setApplicationContact(detail.id, next || null)
                  .then(onChanged)
                  .catch((exc) => setError(apiDetail(exc)));
              }}
              aria-label={t("applications.contactTitle")}
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm"
              data-testid="application-contact-select"
            >
              <option value="">{t("applications.noContact")}</option>
              {contacts.map((contact) => (
                <option key={contact.id} value={contact.id}>
                  {[contact.name, contact.org].filter(Boolean).join(" · ")}
                </option>
              ))}
            </select>
            <Link to="/contacts" className="text-xs text-[var(--as-accent)] underline">
              {t("applications.manageContacts")}
            </Link>
          </section>

          <section className="space-y-2" data-testid="application-offer">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-[var(--as-fg)]">
                {t("applications.offer.title")}
              </h3>
              <Link
                to="/applications/offers"
                className="text-xs text-[var(--as-accent)] underline"
                data-testid="application-offer-compare-link"
              >
                {t("applications.offer.compare")}
              </Link>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.offer.currency")}
                <input
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.currency}
                  maxLength={3}
                  onChange={(event) =>
                    setOfferForm((prev) => ({
                      ...prev,
                      currency: event.target.value.toUpperCase(),
                    }))
                  }
                  data-testid="application-offer-currency"
                />
              </label>
              <label className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.offer.amount")}
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.amount}
                  onChange={(event) =>
                    setOfferForm((prev) => ({ ...prev, amount: event.target.value }))
                  }
                  data-testid="application-offer-amount"
                />
              </label>
              <SelectField
                label={t("applications.offer.period")}
                value={offerForm.period}
                onChange={(value) =>
                  setOfferForm((prev) => ({
                    ...prev,
                    period: value as ApplicationOffer["period"],
                  }))
                }
                options={(["year", "month", "hour"] as const).map((value) => ({
                  value,
                  label: t(`applications.offer.periods.${value}`),
                }))}
                testId="application-offer-period"
              />
              <label className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.offer.location")}
                <input
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.location}
                  onChange={(event) =>
                    setOfferForm((prev) => ({ ...prev, location: event.target.value }))
                  }
                  data-testid="application-offer-location"
                />
              </label>
              <label className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.offer.costOfLiving")}
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.cost_of_living}
                  onChange={(event) =>
                    setOfferForm((prev) => ({
                      ...prev,
                      cost_of_living: event.target.value,
                    }))
                  }
                  data-testid="application-offer-col"
                />
              </label>
              <label className="text-xs text-[var(--as-muted-fg)]">
                {t("applications.offer.deadline")}
                <input
                  type="date"
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.deadline}
                  onChange={(event) =>
                    setOfferForm((prev) => ({ ...prev, deadline: event.target.value }))
                  }
                  data-testid="application-offer-deadline"
                />
              </label>
              <label className="text-xs text-[var(--as-muted-fg)] sm:col-span-2">
                {t("applications.offer.benefits")}
                <textarea
                  rows={2}
                  className="mt-1 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={offerForm.benefits}
                  onChange={(event) =>
                    setOfferForm((prev) => ({ ...prev, benefits: event.target.value }))
                  }
                  data-testid="application-offer-benefits"
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={busy || !offerForm.currency || !offerForm.amount}
                data-testid="application-offer-save"
                onClick={() =>
                  void run(() =>
                    setApplicationOffer(detail.id, {
                      currency: offerForm.currency,
                      amount: Number(offerForm.amount),
                      period: offerForm.period,
                      benefits: offerForm.benefits
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                      location: offerForm.location.trim(),
                      cost_of_living:
                        offerForm.cost_of_living.trim() === ""
                          ? null
                          : Number(offerForm.cost_of_living),
                      deadline: offerForm.deadline || null,
                    })
                  )
                }
              >
                {t("applications.offer.save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                data-testid="application-offer-clear"
                onClick={() =>
                  void run(async () => {
                    const next = await clearApplicationOffer(detail.id);
                    setOfferForm(EMPTY_OFFER);
                    return next;
                  })
                }
              >
                {t("applications.offer.clear")}
              </Button>
            </div>
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
                        {event.meta?.all_day
                          ? new Date(event.at).toLocaleDateString(undefined, {
                              timeZone: "UTC",
                            })
                          : new Date(event.at).toLocaleString()}{" "}
                        · {event.actor}
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
