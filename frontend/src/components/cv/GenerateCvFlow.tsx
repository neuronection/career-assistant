import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import { fetchContextSources, generateCv } from "@/api/cv";
import { fetchPostings } from "@/api/postings";
import { fetchTemplates } from "@/api/cvTemplates";
import { cancelBackgroundJob } from "@/api/backgroundJobs";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { JobFlowStatus } from "@/components/JobFlowStatus";
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
export function GenerateCvFlow({ onClose }: { onClose?: () => void }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<"form" | "running" | "cancelled">("form");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [sources, setSources] = useState<CvContextSourceOut[]>([]);
  const [postings, setPostings] = useState<{ id: string; title: string; org: string }[]>([]);
  const [templates, setTemplates] = useState<CvTemplateSummary[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [postingId, setPostingId] = useState("");
  const [language, setLanguage] = useState(
    i18n.language?.startsWith("de") ? "de" : i18n.language?.startsWith("el") ? "el" : "en"
  );
  const [tone, setTone] = useState("");
  const [length, setLength] = useState("standard");
  const [maxPages, setMaxPages] = useState(1);
  const [templateId, setTemplateId] = useState("");
  const [includePhoto, setIncludePhoto] = useState(false);
  const [enabledSources, setEnabledSources] = useState<Set<string>>(new Set());
  const [sectionsOn, setSectionsOn] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState("");

  const { job, track, stop } = useBackgroundJob((finished) => {
    if (finished.status === "succeeded") {
      const cvId = finished.result?.cv_id;
      if (typeof cvId === "string" && cvId) navigate(`/cv/${cvId}`);
      return;
    }
    if (finished.status === "cancelled") {
      setPhase("cancelled");
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

  async function handleGenerate() {
    setError("");
    const allOn = offerable.every((source) => enabledSources.has(source.key));
    const selection: CvContextSelection = allOn
      ? { mode: "all", include: [], exclude: [] }
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
        };
    const request: CvGenerateRequest = {
      target_posting_id: postingId || undefined,
      language,
      tone: tone ? (tone as CvGenerateRequest["tone"]) : undefined,
      length: length as CvGenerateRequest["length"],
      max_pages: maxPages,
      template_id: templateId || undefined,
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

  if (phase === "running") {
    return (
      <div className="space-y-4 p-4 pt-0" data-testid="cv-generate-progress">
        {job ? (
          <JobFlowStatus job={job} title={t("cvGenerate.running")} testId="cv-generate-flow-status" />
        ) : (
          <p className="text-sm text-[var(--as-muted-fg)]">{t("cvGenerate.running")}</p>
        )}
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

      <SelectField
        label={t("cvGenerate.language")}
        value={language}
        onChange={setLanguage}
        options={LANGUAGES}
        testId="cv-generate-language"
      />

      <TextareaField
        label={t("cvGenerate.notes")}
        value={notes}
        onChange={setNotes}
        maxLength={2000}
        rows={3}
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
          <SelectField
            label={t("cvGenerate.template")}
            value={templateId}
            onChange={setTemplateId}
            options={[
              { value: "", label: t("cvGenerate.templateDefault") },
              ...templates.map((template) => ({
                value: String(template.id),
                label: template.title,
              })),
            ]}
            testId="cv-generate-template"
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
