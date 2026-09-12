import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { PartyPopper, FileSearch } from "lucide-react";
import {
  Button,
  ConfirmationModal,
  EmptyState,
  Spinner,
  UploadDropzone,
} from "@neuronection/assistant-ui";
import {
  applyCvDraft,
  discardCvDraft,
  getCvDrafts,
  isNotFound,
  reparseCv,
  uploadCv,
} from "@/api/cvIntake";
import { fetchBackgroundJob, isTerminal } from "@/api/backgroundJobs";
import { apiDetail } from "@/api/client";
import { LandedLinks } from "./CvDraftViewer";
import { isStatusSection } from "./CvStatus";
import { SuggestionReviewList, sectionViews } from "./SuggestionReviewList";
import type { SectionCardHandle } from "@/components/profile/sections/shared";
import type {
  CvAppliedEntity,
  CvApplyReport,
  CvDraft,
  CvIntakeSection,
  CvSelections,
} from "@/types/cvIntake";

type Phase = "idle" | "working" | "review" | "applied" | "empty";

const DRAFT_POLL_TRIES = 20;
const DRAFT_POLL_MS = 1200;
const JOB_POLL_TRIES = 40;
const JOB_POLL_MS = 1500;

/** Wait until the enqueued parse job reaches a terminal state (plan
 * 57.7): re-processing used to read the stale draft the instant the job
 * was enqueued. Terminal-failed jobs still resolve — openDraft then
 * reports what it finds. */
async function waitForParseJob(jobId: string): Promise<void> {
  for (let tries = JOB_POLL_TRIES; tries > 0; tries -= 1) {
    try {
      const job = await fetchBackgroundJob(jobId);
      if (isTerminal(job)) return;
    } catch {
      /* transient polling error — retry */
    }
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
  }
}
function defaultSelections(draft: CvDraft): CvSelections {
  const selections: CvSelections = {};
  for (const view of sectionViews(draft.payload)) {
    selections[view.key] = view.items.map((_, i) => i);
  }
  return selections;
}

function appliedSummary(report: CvApplyReport): string {
  const t = i18next.t;
  const counts = Object.entries(report.created ?? {})
    .filter(([, n]) => n > 0)
    .map(([key, n]) =>
      t("intake.createdCount", {
        count: n,
        label: t(`intake.created.${key}`, {
          defaultValue: key.replace(/_/g, " "),
        }),
      })
    );
  const base = counts.length
    ? t("intake.appliedBase", { parts: counts.join(", ") })
    : t("intake.nothingNew");
  const proposed = report.proposed_skills?.length ?? 0;
  return proposed > 0
    ? `${base} ${t("intake.proposedSuffix", { count: proposed })}`
    : base;
}

/** CV import flow: upload `kind=cv` → poll for the parse
 * draft (the extract-text job auto-enqueues it) → review-first
 * apply/discard. Import is optional by design: `save()` always passes so
 * the wizard can advance without a CV. */
export const CvIntakeFlow = forwardRef<
  SectionCardHandle,
  {
    onApplied?: () => void;
    pollMs?: number;
    initialDocumentId?: string;
    reprocess?: boolean;
    onExit?: () => void;
  }
>(function CvIntakeFlow(
  { onApplied, pollMs = DRAFT_POLL_MS, initialDocumentId, reprocess, onExit },
  ref
) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CvDraft | null>(null);
  const [selected, setSelected] = useState<CvSelections>({});
  const [draftAll, setDraftAll] = useState(false);
  const [draftItems, setDraftItems] = useState<
    Partial<Record<CvIntakeSection, number[]>>
  >({});
  const [applied, setApplied] = useState<CvApplyReport | null>(null);
  const [appliedEntities, setAppliedEntities] = useState<CvAppliedEntity[]>([]);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { t } = useTranslation();
  const pollRef = useRef<number | null>(null);
  const appliedRef = useRef(onApplied);
  appliedRef.current = onApplied;

  useImperativeHandle(
    ref,
    () => ({
      save: async () => true,
      isDirty: () => false,
    }),
    []
  );

  useEffect(
    () => () => {
      if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    },
    []
  );

  const pollForDraft = useCallback(
    (id: string, triesLeft: number) => {
      pollRef.current = window.setTimeout(async () => {
        try {
          const found = await getCvDrafts(id);
          setDraft(found);
          setSelected(defaultSelections(found));
          setPhase(
            sectionViews(found.payload).length ? "review" : "empty"
          );
        } catch (err) {
          if (isNotFound(err) && triesLeft > 1) {
            pollForDraft(id, triesLeft - 1);
            return;
          }
          setError(
            isNotFound(err)
              ? t("intake.slowParse")
              : apiDetail(err)
          );
          setPhase("idle");
        }
      }, pollMs);
    },
    [pollMs, t]
  );

  const openDraft = useCallback(
    async (id: string, triesLeft: number) => {
      try {
        const found = await getCvDrafts(id);
        setDraft(found);
        setSelected(defaultSelections(found));
        setPhase(sectionViews(found.payload).length ? "review" : "empty");
      } catch (err) {
        if (isNotFound(err) && triesLeft > 1) {
          pollForDraft(id, triesLeft - 1);
          return;
        }
        setError(
          isNotFound(err)
            ? t("intake.slowParse")
            : apiDetail(err)
        );
        setPhase("idle");
      }
    },
    [pollForDraft, t]
  );

  useEffect(() => {
    if (!initialDocumentId) return;
    setDocumentId(initialDocumentId);
    setPhase("working");
    if (reprocess) {
      setStage(t("intake.stage.reread"));
      (async () => {
        try {
          const { job_id } = await reparseCv(initialDocumentId);
          await waitForParseJob(job_id);
        } catch (err) {
          setError(apiDetail(err));
          setPhase("idle");
          return;
        }
        openDraft(initialDocumentId, DRAFT_POLL_TRIES);
      })();
    } else {
      setStage(t("intake.stage.openDraft"));
      void openDraft(initialDocumentId, DRAFT_POLL_TRIES);
    }
  }, [initialDocumentId, reprocess, openDraft, t]);

  const start = async (files: File[]) => {
    const file = files[0];
    if (!file) return;
    setError("");
    setDraft(null);
    setApplied(null);
    setStage(t("intake.stage.uploading"));
    setPhase("working");
    try {
      const { document } = await uploadCv(file);
      setDocumentId(document.id);
      setStage(t("intake.stage.reading"));
      pollForDraft(document.id, DRAFT_POLL_TRIES);
    } catch (err) {
      setError(apiDetail(err));
      setPhase("idle");
    }
  };

  const itemCount = useMemo(
    () =>
      draft
        ? sectionViews(draft.payload).reduce(
            (sum, view) =>
              sum +
              (Array.isArray(selected[view.key])
                ? (selected[view.key] as number[]).length
                : selected[view.key] === true
                  ? view.items.length
                  : 0),
            0
          )
        : 0,
    [draft, selected]
  );

  const selectionsPayload = useMemo(() => {
    if (!draft) return {};
    const payload: CvSelections = {};
    for (const view of sectionViews(draft.payload)) {
      const entry = selected[view.key];
      if (entry === true) payload[view.key] = true;
      else if (Array.isArray(entry) && entry.length) payload[view.key] = entry;
    }
    return payload;
  }, [draft, selected]);

  const draftsPayload = useMemo(() => {
    const payload: CvSelections = {};
    if (!draft) return payload;
    for (const view of sectionViews(draft.payload)) {
      if (!isStatusSection(view.key)) continue;
      if (draftAll) payload[view.key] = true;
      else {
        const list = draftItems[view.key] ?? [];
        if (list.length) payload[view.key] = list;
      }
    }
    return payload;
  }, [draft, draftAll, draftItems]);

  const toggleItemDraft = useCallback(
    (section: CvIntakeSection, index: number) => {
      setDraftItems((prev) => {
        const list = prev[section] ?? [];
        const next = list.includes(index)
          ? list.filter((i) => i !== index)
          : [...list, index];
        return { ...prev, [section]: next };
      });
    },
    []
  );

  const flipDraftAll = useCallback((all: boolean) => {
    setDraftAll(all);
    if (all) setDraftItems({});
  }, []);

  const apply = async () => {
    if (!draft || !documentId) return;
    setSubmitting(true);
    setError("");
    try {
      const { report, applied } = await applyCvDraft(
        documentId,
        selectionsPayload,
        draftsPayload
      );
      setApplied(report);
      setAppliedEntities(applied ?? []);
      setPhase("applied");
      appliedRef.current?.();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSubmitting(false);
    }
  };

  const discard = async () => {
    if (!documentId) return;
    setConfirmDiscard(false);
    setError("");
    try {
      await discardCvDraft(documentId);
    } catch {
      /* draft already gone — nothing to clean up */
    }
      setDraft(null);
      setDocumentId(null);
      setSelected({});
      setPhase("idle");
      onExit?.();
    };

  return (
    <div data-testid="cv-intake-flow">
      {phase === "idle" && (
        <div className="space-y-4">
          <UploadDropzone
            onFiles={(files) => void start(files)}
            multiple={false}
            accept="application/pdf,text/plain,image/png,image/jpeg"
            label={t("intake.dropLabel")}
            hint={t("intake.dropHint")}
          />
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </div>
      )}

      {phase === "working" && (
        <div
          className="flex flex-col items-center gap-3 py-14 text-center"
          data-testid="cv-intake-working"
        >
          <Spinner size="lg" />
          <p className="text-sm text-[var(--as-muted-fg)]">{stage}</p>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("intake.scannedNote")}
          </p>
        </div>
      )}

      {phase === "review" && draft && (
        <div className="space-y-4" data-testid="cv-intake-review">
          <div>
            <h3 className="font-semibold text-[var(--as-fg)]">
              {t("intake.reviewTitle")}
            </h3>
            <p className="text-sm text-[var(--as-muted-fg)]">
              {t("intake.reviewCount", {
                chosen: itemCount,
                total: sectionViews(draft.payload).reduce(
                  (sum, view) => sum + view.items.length,
                  0
                ),
              })}
            </p>
          </div>
          <SuggestionReviewList
            payload={draft.payload}
            selected={selected}
            onChange={setSelected}
            documentId={documentId ?? undefined}
            draftItems={draftItems}
            onDraftToggle={toggleItemDraft}
            draftAll={draftAll}
          />
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setConfirmDiscard(true)}
              className="text-sm text-[var(--as-muted-fg)] underline-offset-2 hover:text-[var(--as-fg)] hover:underline"
              data-testid="cv-intake-discard"
            >
              {t("intake.discard")}
            </button>
            <div className="flex items-center gap-3">
              <div
                className="inline-flex rounded-lg border border-[var(--as-border)] p-0.5"
                data-testid="cv-intake-apply-mode"
              >
                {(["active", "draft"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => flipDraftAll(mode === "draft")}
                    aria-pressed={(mode === "draft") === draftAll}
                    className={`rounded-md px-3 py-1.5 text-sm ${
                      (mode === "draft") === draftAll
                        ? "bg-[var(--as-muted)] text-[var(--as-fg)]"
                        : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                    }`}
                    data-testid={`cv-intake-apply-mode-${mode}`}
                  >
                    {t(mode === "active" ? "intake.applyActive" : "intake.applyDraft")}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => void apply()}
                disabled={submitting || itemCount === 0}
                className="rounded-lg bg-primary-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
                data-testid="cv-intake-apply"
              >
                {submitting
                  ? t("intake.importing")
                  : t("intake.importCount", { count: itemCount })}
              </button>
            </div>
          </div>
        </div>
      )}

      {phase === "empty" && (
        <EmptyState
          icon={FileSearch}
          title={t("intake.emptyTitle")}
          description={t("intake.emptyBody")}
          action={
            <button
              type="button"
              onClick={() =>
                onExit ? onExit() : setPhase("idle")
              }
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white"
              data-testid="cv-intake-empty-retry"
            >
              {onExit ? t("intake.backToCvs") : t("intake.tryAnother")}
            </button>
          }
        />
      )}

      {phase === "applied" && applied && (
        <div className="space-y-3">
          <EmptyState
            icon={PartyPopper}
            title={t("intake.importedTitle")}
            description={appliedSummary(applied)}
          />
          <div className="mx-auto max-w-xl" data-testid="cv-intake-landed">
            <LandedLinks applied={appliedEntities} />
          </div>
          <div className="flex justify-center">
            {onExit ? (
              <Button variant="outline" size="sm" onClick={onExit} data-testid="cv-intake-done">
                {t("intake.backToCvs")}
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setApplied(null);
                  setDraft(null);
                  setDocumentId(null);
                  setSelected({});
                  setPhase("idle");
                }}
                data-testid="cv-intake-again"
              >
                {t("intake.importAnother")}
              </Button>
            )}
          </div>
        </div>
      )}

      <ConfirmationModal
        open={confirmDiscard}
        onOpenChange={setConfirmDiscard}
        onConfirm={() => void discard()}
        title={t("intake.discardTitle")}
        description={t("intake.discardBody")}
        confirmLabel={t("intake.discardConfirm")}
        destructive
      />
    </div>
  );
});
