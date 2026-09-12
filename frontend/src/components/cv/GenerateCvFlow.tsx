import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  fetchContextSources,
  fetchGeneratePreview,
  generateCv,
  polishCv,
  previewSynthMatches,
} from "@/api/cv";
import type {
  CvGeneratePreviewOut,
  CvGenerateResult,
  CvPolishTrace,
} from "@/types/cv";
import { fetchPostings } from "@/api/postings";
import { fetchTemplates } from "@/api/cvTemplates";
import { cancelBackgroundJob } from "@/api/backgroundJobs";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { openCvChat } from "@/components/chat/cvChatLink";
import { JobFlowStatus } from "@/components/JobFlowStatus";
import { RunTelemetryStrip } from "@/components/cv/RunsPanel";
import { PolishPreviewIframe } from "@/components/cv/PolishTrace";
import { traceFromPolishTrace } from "@/lib/cvBuildTrace";
import { FlowTraceCard } from "@/components/ui";
import {
  ChipTogglesRow,
  SegmentedRow,
  SelectField,
  StepperRow,
  TextareaField,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import type {
  CvContextSourceOut,
  CvContextSelection,
  CvGenerateRequest,
  CvGenerateSectionKind,
} from "@/types/cv";
import type { CvTemplateSummary } from "@/types/cvTemplate";

const GENERATABLE: CvGenerateSectionKind[] = [
  "summary",
  "experience",
  "projects",
  "volunteer",
  "education",
  "certifications",
  "skills",
  "languages",
  "achievements",
  "interests",
];

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "de", label: "Deutsch" },
  { value: "el", label: "Ελληνικά" },
];

/** The generate-with-AI flow: preferences form → background
 * job progress (cancel supported) → navigate into the builder. Hosts
 * mount it fresh per open; it always navigates on success. */
export function GenerateCvFlow({
  onClose,
  onPreviewActiveChange,
}: {
  onClose?: () => void;
  /** Fired on transitions of "a preview HTML exists" — hosts use it to
   * resize the dialog (compact until the first preview, then wide). */
  onPreviewActiveChange?: (active: boolean) => void;
}) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<"form" | "running" | "cancelled" | "failed">("form");
  const [error, setError] = useState("");
  const [failedCvId, setFailedCvId] = useState("");
  const [resuming, setResuming] = useState(false);
  const [jobId, setJobId] = useState("");
  const [sources, setSources] = useState<CvContextSourceOut[]>([]);
  const [postings, setPostings] = useState<{ id: string; title: string; org: string }[]>([]);
  const [templates, setTemplates] = useState<CvTemplateSummary[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [postingId, setPostingId] = useState("");
  const [postingText, setPostingText] = useState("");
  const [language, setLanguage] = useState(
    i18n.language?.startsWith("de") ? "de" : i18n.language?.startsWith("el") ? "el" : "en"
  );
  const [tone, setTone] = useState("");
  const [length, setLength] = useState("standard");
  const [maxPages, setMaxPages] = useState(1);
  const [templateId, setTemplateId] = useState("auto");
  const [includePhoto, setIncludePhoto] = useState(false);
  const [enabledSources, setEnabledSources] = useState<Set<string>>(new Set());
  const [sectionsOn, setSectionsOn] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState("");
  const [preferSynth, setPreferSynth] = useState(false);
  const [synthMatches, setSynthMatches] = useState<number | null>(null);
  const [finishedCv, setFinishedCv] = useState<{
    cvId: string;
    applied: number;
    proposed: number;
  } | null>(null);
  const [preview, setPreview] = useState<CvGeneratePreviewOut | null>(null);

  const previewActive = Boolean(preview?.html);
  const previewActiveCb = useRef(onPreviewActiveChange);
  previewActiveCb.current = onPreviewActiveChange;
  useEffect(() => {
    previewActiveCb.current?.(previewActive);
  }, [previewActive]);

  useEffect(() => {
    if (phase !== "running" || !jobId) {
      setPreview(null);
      return;
    }
    const fetchPreview = () => {
      fetchGeneratePreview(jobId)
        .then((out) => setPreview(out))
        .catch(() => {});
    };
    fetchPreview();
    const timer = window.setInterval(fetchPreview, 2500);
    return () => {
      window.clearInterval(timer);
    };
  }, [phase, jobId]);

  const { job, track, stop } = useBackgroundJob((finished) => {
    if (finished.status === "succeeded") {
      const cvId = finished.result?.cv_id;
      if (typeof cvId === "string" && cvId) {
        const result = (finished.result ?? {}) as unknown as CvGenerateResult;
        const applied = Object.keys(result.synth_applied ?? {}).length;
        const proposed = result.synth_proposed?.length ?? 0;
        if (applied > 0 || proposed > 0) {
          // Plan 69.4: surface what the library contributed before the
          // builder hands over (advance is an explicit click).
          setFinishedCv({ cvId, applied, proposed });
          return;
        }
        navigate(`/cv/${cvId}`);
        // Land in the builder with the copilot docked on this CV's
        // session — chat is the driver for the freshly generated draft
        // (plan 67; pinned-session entry, never a second chatbot).
        void openCvChat(cvId, "docked");
      }
      return;
    }
    if (finished.status === "cancelled") {
      setPhase("cancelled");
      return;
    }
    const cvId = typeof finished.result?.cv_id === "string" ? finished.result.cv_id : "";
    if (cvId) {
      setFailedCvId(cvId);
      setPhase("failed");
      setError(finished.error ?? t("cvGenerate.failed"));
      return;
    }
    setPhase("form");
    setError(finished.error || t("cvGenerate.failed"));
  });

  useEffect(() => {
    let cancelled = false;
    fetchContextSources()
      .then((out) => {
        if (cancelled) return;
        const offerable = out.sources.filter(
          (source) => source.key !== "basics" && source.items.length > 0
        );
        setSources(offerable);
        setEnabledSources(new Set(offerable.map((source) => source.key)));
        setSectionsOn(new Set(offerable.map((source) => source.key)));
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    fetchPostings({ saved: true })
      .then((page) =>
        setPostings(
          page.items.map((row) => ({
            id: String(row.id),
            title: row.title,
            org: row.org,
          }))
        )
      )
      .catch(() => setPostings([]));
    fetchTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const offerable = sources.filter(
    (source) =>
      source.key !== "basics" &&
      source.items.length > 0 &&
      GENERATABLE.includes(source.key as CvGenerateSectionKind)
  );
  const sectionOptions = offerable
    .filter((source) => enabledSources.has(source.key))
    .map((source) => ({ value: source.key, label: source.label }));
  const totalItems = offerable.reduce((sum, source) => sum + source.items.length, 0);
  const canGenerate = totalItems > 0;

  useEffect(() => {
    if (!preferSynth) {
      setSynthMatches(null);
      return;
    }
    const refs = sources
      .filter((source) => enabledSources.has(source.key))
      .flatMap((source) =>
        source.items.map((item) => ({
          source_key: source.key,
          item_id: item.item_id,
        }))
      );
    const timer = window.setTimeout(() => {
      previewSynthMatches({
        language,
        target_posting_id: postingId || undefined,
        refs,
      })
        .then((out) => setSynthMatches(out.total))
        .catch(() => setSynthMatches(null));
    }, 400);
    return () => {
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferSynth, language, postingId, enabledSources, sources]);

  async function handleGenerate() {
    setError("");
    const allOn = offerable.every((source) => enabledSources.has(source.key));
    const selection: CvContextSelection = allOn
      ? { mode: "all", include: [], exclude: [], synth_mode: preferSynth ? "prefer" : "off" }
      : {
          mode: "none",
          include: sources
            .filter((source) => enabledSources.has(source.key))
            .flatMap((source) =>
              source.items.map((item) => ({
                source_key: source.key,
                item_id: item.item_id,
              }))
            ),
          exclude: [],
          synth_mode: preferSynth ? "prefer" : "off",
        };
    const request: CvGenerateRequest = {
      target_posting_id: postingId || undefined,
      posting_text: postingText.trim() || undefined,
      language,
      tone: tone ? (tone as CvGenerateRequest["tone"]) : undefined,
      length: length as CvGenerateRequest["length"],
      max_pages: maxPages,
      // The AI template pick runs inside the background job
      // (`resolvedTemplateId` never blocks the submit — plan-67 stall).
      template_pick: templateId === "auto" ? "ai" : "none",
      template_id: templateId === "auto" || templateId === "none" ? undefined : templateId,
      include_photo: includePhoto,
      sections: sectionOptions
        .map((option) => option.value)
        .filter((key) => sectionsOn.has(key)) as CvGenerateSectionKind[],
      context: selection,
      notes: notes.trim() || undefined,
    };
    try {
      const accepted = await generateCv(request);
      setJobId(accepted.job_id);
      setPhase("running");
      track(accepted.job_id, 1000);
    } catch (err) {
      setError(apiDetail(err));
    }
  }

  async function handleResumePolish() {
    if (!failedCvId) return;
    setResuming(true);
    setError("");
    try {
      const accepted = await polishCv(failedCvId, jobId || undefined);
      setFailedCvId("");
      setJobId(accepted.job_id);
      setPhase("running");
      track(accepted.job_id, 1000);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setResuming(false);
    }
  }


  if (finishedCv) {
    return (
      <div className="space-y-4 p-4 pt-0" data-testid="cv-generate-finished">
        <div className="rounded border border-[var(--as-border)] bg-[var(--as-muted)] p-3 text-xs">
          <p className="font-medium">{t("cvGenerate.synthSuccess")}</p>
          {finishedCv.applied > 0 && (
            <p className="mt-1 text-[var(--as-muted-fg)]">
              {t("cvGenerate.synthAppliedCount", { n: finishedCv.applied })}
            </p>
          )}
          {finishedCv.proposed > 0 && (
            <p className="mt-1 text-[var(--as-muted-fg)]">
              {t("cvGenerate.synthProposedCount", { n: finishedCv.proposed })}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2">
          {finishedCv.proposed > 0 && (
            <Button
              variant="outline"
              onClick={() => navigate("/cv/synth")}
              data-testid="cv-generate-review-variants"
            >
              {t("cvGenerate.reviewVariants")}
            </Button>
          )}
          <Button
            onClick={() => {
              const cvId = finishedCv.cvId;
              setFinishedCv(null);
              navigate(`/cv/${cvId}`);
              void openCvChat(cvId, "docked");
            }}
            data-testid="cv-generate-open-finished"
          >
            {t("cvGenerate.openBuilder")}
          </Button>
        </div>
      </div>
    );
  }

  if (phase === "running") {
    const trace = (preview?.trace as CvPolishTrace | undefined) ?? (job?.result?.polish as CvPolishTrace | undefined);
    return (
      <div
        className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(300px,620px)]"
        data-testid="cv-generate-progress"
      >
        <div className="space-y-4">
          {job ? (
            <JobFlowStatus job={job} title={t("cvGenerate.running")} testId="cv-generate-flow-status" />
          ) : (
            <p className="text-sm text-[var(--as-muted-fg)]">{t("cvGenerate.running")}</p>
          )}
          {preview && preview.iteration > 0 && (
            <p className="text-xs text-[var(--as-muted-fg)]" data-testid="cv-generate-polish-step">
              {t("cvGenerate.polish.running", { n: preview.iteration })}
            </p>
          )}
          <RunTelemetryStrip trace={trace} />
          {trace?.iterations?.length ? (
            <FlowTraceCard
              trace={traceFromPolishTrace(trace)}
              labels={{
                title: t("cvBuilder.runs.traceTitle"),
                stages: t("cvBuilder.runs.stages"),
                calls: t("cvBuilder.runs.calls"),
                ops: t("cvBuilder.runs.ops"),
              }}
            />
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                void cancelBackgroundJob(jobId);
                stop();
                setPhase("cancelled");
              }}
              data-testid="cv-generate-cancel"
            >
              {t("cvGenerate.cancel")}
            </Button>
          </div>
        </div>
        <div className="min-h-0 h-[60dvh] xl:h-[calc(85vh-11rem)]">
          {preview?.html ? (
            <PolishPreviewIframe
              html={preview.html}
              title={t("cvGenerate.preview")}
              fill
              testId="cv-generate-preview"
            />
          ) : null}
        </div>
      </div>
    );
  }

  if (phase === "cancelled") {
    return (
      <div className="space-y-4 p-4 pt-0" data-testid="cv-generate-cancelled">
        <p className="text-sm text-[var(--as-muted-fg)]">{t("cvGenerate.cancelled")}</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setPhase("form")} data-testid="cv-generate-back">
            {t("cvGenerate.backToForm")}
          </Button>
          {onClose && (
            <Button onClick={() => onClose()}>{t("common.close")}</Button>
          )}
        </div>
      </div>
    );
  }

  if (phase === "failed") {
    return (
      <div className="space-y-4 p-4 pt-0" data-testid="cv-generate-failed">
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-700">
          {error || t("cvGenerate.failed")}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setPhase("form")} data-testid="cv-generate-back">
            {t("cvGenerate.backToForm")}
          </Button>
          {failedCvId && (
            <Button
              variant="outline"
              disabled={resuming}
              onClick={() => void handleResumePolish()}
              data-testid="cv-generate-resume-polish"
            >
              {t("cvGenerate.resumePolish")}
            </Button>
          )}
          {failedCvId && (
            <Button onClick={() => navigate(`/cv/${failedCvId}`)} data-testid="cv-generate-open-builder">
              {t("cvGenerate.openBuilder")}
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 pt-0" data-testid="cv-generate-form">
      <p className="text-sm text-[var(--as-muted-fg)]">{t("cvGenerate.subtitle")}</p>

      <SelectField
        label={t("cvGenerate.target")}
        value={postingId}
        onChange={setPostingId}
        options={[
          { value: "", label: t("cvGenerate.noTarget") },
          ...postings.map((posting) => ({
            value: posting.id,
            label: posting.org ? `${posting.title} — ${posting.org}` : posting.title,
          })),
        ]}
        testId="cv-generate-target"
      />

      <TextareaField
        label={t("cvGenerate.postingPaste")}
        value={postingText}
        onChange={setPostingText}
        maxLength={5000}
        rows={3}
        autoGrow
        autoGrowMaxHeight={280}
        counter
        hint={t("cvGenerate.postingPasteHint")}
        placeholder={t("cvGenerate.postingPastePlaceholder")}
        testId="cv-generate-posting-text"
      />

      <SelectField
        label={t("cvGenerate.language")}
        value={language}
        onChange={setLanguage}
        options={LANGUAGES}
        testId="cv-generate-language"
      />

      <SelectField
        label={t("cvGenerate.template")}
        value={templateId}
        onChange={setTemplateId}
        options={[
          { value: "auto", label: t("cvGenerate.templateAuto") },
          { value: "none", label: t("cvGenerate.templateDefault") },
          ...templates.map((template) => ({
            value: String(template.id),
            label: template.title,
          })),
        ]}
        testId="cv-generate-template"
      />

      <TextareaField
        label={t("cvGenerate.notes")}
        value={notes}
        onChange={setNotes}
        maxLength={5000}
        rows={5}
        autoGrow
        autoGrowMaxHeight={400}
        placeholder={t("cvGenerate.notesPlaceholder")}
        testId="cv-generate-notes"
      />

      <button
        type="button"
        onClick={() => setAdvancedOpen((open) => !open)}
        className="cursor-pointer text-xs font-medium text-[var(--as-muted-fg)] underline-offset-2 hover:text-[var(--as-fg)] hover:underline"
        data-testid="cv-generate-advanced"
      >
        {advancedOpen ? t("cvGenerate.hideAdvanced") : t("cvGenerate.advanced")}
      </button>

      {advancedOpen && (
        <div className="space-y-4 rounded-lg border border-[var(--as-border)] p-3">
          <SegmentedRow
            label={t("cvGenerate.voice")}
            value={tone}
            onChange={setTone}
            options={[
              { value: "", label: t("cvGenerate.toneDefault") },
              { value: "professional", label: t("cvGenerate.toneProfessional") },
              { value: "warm", label: t("cvGenerate.toneWarm") },
              { value: "concise", label: t("cvGenerate.toneConcise") },
              { value: "confident", label: t("cvGenerate.toneConfident") },
            ]}
          />
          <SegmentedRow
            label={t("cvGenerate.length")}
            value={length}
            onChange={setLength}
            options={[
              { value: "concise", label: t("cvGenerate.lengthConcise") },
              { value: "standard", label: t("cvGenerate.lengthStandard") },
              { value: "detailed", label: t("cvGenerate.lengthDetailed") },
            ]}
          />
          <StepperRow
            label={t("cvGenerate.maxPages")}
            value={maxPages}
            min={1}
            max={3}
            onChange={setMaxPages}
          />
          <ToggleRow
            label={t("cvGenerate.includePhoto")}
            checked={includePhoto}
            onChange={setIncludePhoto}
          />
          {sectionOptions.length > 0 && (
            <ChipTogglesRow
              label={t("cvGenerate.sections")}
              values={sectionOptions
                .map((option) => option.value)
                .filter((key) => sectionsOn.has(key))}
              options={sectionOptions}
              onChange={(next) => setSectionsOn(new Set(next))}
            />
          )}
          <div className="space-y-1">
            <p className="text-xs text-[var(--as-muted-fg)]">{t("cvGenerate.context")}</p>
            <ToggleRow
              label={t("cvGenerate.preferSynth")}
              checked={preferSynth}
              onChange={setPreferSynth}
            />
            {preferSynth && synthMatches !== null && (
              <p
                className="text-xs text-[var(--as-muted-fg)]"
                data-testid="cv-generate-synth-hint"
              >
                {synthMatches > 0
                  ? t("cvGenerate.synthMatchCount", { n: synthMatches })
                  : t("cvGenerate.synthMatchNone")}
              </p>
            )}
            {offerable.map((source) => (
              <ToggleRow
                key={source.key}
                label={`${source.label} (${source.items.length})`}
                checked={enabledSources.has(source.key)}
                onChange={(checked) =>
                  setEnabledSources((current) => {
                    const next = new Set(current);
                    if (checked) next.add(source.key);
                    else next.delete(source.key);
                    return next;
                  })
                }
              />
            ))}
          </div>
        </div>
      )}

      {!canGenerate && (
        <p className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800" role="note">
          {t("cvGenerate.sparseHint")}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-700">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-2">
        {onClose && (
          <Button variant="ghost" onClick={() => onClose()}>
            {t("common.cancel")}
          </Button>
        )}
        <Button
          onClick={() => void handleGenerate()}
          disabled={!canGenerate}
          data-testid="cv-generate-submit"
        >
          {t("cvGenerate.generate")}
        </Button>
      </div>
    </div>
  );
}
