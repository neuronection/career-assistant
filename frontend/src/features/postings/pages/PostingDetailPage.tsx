import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ExternalLink, GraduationCap, Sparkles, Target } from "lucide-react";

import { trackApplication } from "@/api/applications";
import { reextractPosting } from "@/api/postings";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";
import { createCoverLetter } from "@/api/cv";
import { createInterviewSession, startInterviewSession } from "@/api/interview";
import {
  fetchPostingDetail,
  hidePosting,
  markApplied,
  markPostingsSeen,
  savePosting,
} from "@/api/postings";
import { openInterviewChat } from "@/features/chat/components/chat/interviewChatLink";
import { MatchCard } from "@/features/postings/components/posting-detail/MatchCard";
import {
  CompactSkillChip,
  SkillChip,
} from "@/features/postings/components/posting-detail/SkillChip";
import { groupByPriority, normalizeSkills } from "@/features/postings/components/posting-detail/skills";
import { Button, EmptyState, SegmentedTabs } from "@/components/ui";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";
import { safeExternalUrl } from "@/lib/url";
import type { PostingDetailOut } from "@/types/wire";

type Extract = NonNullable<PostingDetailOut["extract"]>;

function RelativeTime({ iso }: { iso: string | null | undefined }) {
  const { t } = useTranslation();
  const rel = formatRelativeTime(iso);
  const abs = formatAbsolute(iso);
  if (!abs) return <span className="text-slate-400">—</span>;
  return <span title={abs}>{rel ? t(rel.key, { count: rel.count }) : abs}</span>;
}

function TimelineRow({ label, iso }: { label: string; iso: string | null | undefined }) {
  const abs = formatAbsolute(iso);
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-xs text-slate-400">{label}</span>
      <span className="text-sm text-slate-700 text-right">
        <RelativeTime iso={iso} />
        {abs && <span className="block text-[11px] text-slate-400">{abs}</span>}
      </span>
    </div>
  );
}

/**
 * The posting detail page (`/postings/:ref`): the in-app home of one
 * vacancy — everything the system knows (description, facts, timeline,
 * categories, extract with evidence, match card) with the external board
 * one prominent button away. Links render through `safeExternalUrl`.
 */
export function PostingDetailPage() {
  const { ref = "" } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const [extractBusy, setExtractBusy] = useState(false);
  const [extractNote, setExtractNote] = useState("");
  const [posting, setPosting] = useState<PostingDetailOut | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const [skillsView, setSkillsView] = useState<"compact" | "detailed">("compact");
  const skillGroups = groupByPriority(normalizeSkills(posting?.extract?.skills ?? []));
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [showRawDescription, setShowRawDescription] = useState(false);
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackError, setTrackError] = useState("");
  const [letterBusy, setLetterBusy] = useState(false);
  const [letterError, setLetterError] = useState("");
  const [interviewBusy, setInterviewBusy] = useState(false);
  const [interviewError, setInterviewError] = useState("");

  const load = useCallback(() => {
    setMissing(false);
    setError("");
    void fetchPostingDetail(ref)
      .then(setPosting)
      .catch((err) => {
        const detail = apiDetail(err);
        if (/not found/i.test(detail)) {
          setMissing(true);
          setPosting(null);
        } else {
          setError(detail);
        }
      });
  }, [ref]);

  useEffect(() => {
    setPosting(null);
    setDescriptionOpen(false);
    load();
  }, [load]);

  const valueLabel = (value: string | null | undefined): string | null =>
    value ? t(`explore.facetValue.${value}`, { defaultValue: value.replace(/_/g, " ") }) : null;

  async function track() {
    if (posting === null) return;
    setTrackBusy(true);
    setTrackError("");
    try {
      const application = await trackApplication({
        posting_id: posting.id,
        applied_via: "url",
        applied_via_url: posting.url,
      });
      navigate(`/applications?application=${application.id}`);
    } catch (err) {
      setTrackError(apiDetail(err));
      setTrackBusy(false);
    }
  }

  async function draftLetter() {
    if (posting === null) return;
    setLetterBusy(true);
    setLetterError("");
    try {
      const letter = await createCoverLetter({ posting_id: posting.id });
      navigate(`/cv/${letter.id}`);
    } catch (err) {
      setLetterError(apiDetail(err));
      setLetterBusy(false);
    }
  }

  async function practiceInterview() {
    if (posting === null) return;
    setInterviewBusy(true);
    setInterviewError("");
    try {
      const session = await createInterviewSession({
        posting_ref: posting.id,
        kind: "mixed",
      });
      const started = await startInterviewSession(session.id);
      await openInterviewChat(started.chat_session_id as string, "docked");
      navigate("/chat");
    } catch (err) {
      setInterviewError(apiDetail(err));
      setInterviewBusy(false);
    }
  }

  function toggleSave() {
    if (posting === null) return;
    void savePosting(posting.id, !posting.saved).then(load);
  }

  function hide() {
    if (posting === null) return;
    void hidePosting(posting.id, true).then(() => navigate("/postings"));
  }

  const backLink = (
    <Link
      to="/postings"
      className="inline-flex items-center gap-1.5 text-sm text-primary-700 hover:underline"
    >
      <ArrowLeft className="w-4 h-4" /> {t("postingDetail.backToPostings")}
    </Link>
  );

  if (missing) {
    return (
      <div className="max-w-4xl mx-auto space-y-4" data-testid="posting-detail">
        {backLink}
        <EmptyState title={t("postingDetail.notFound")} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="max-w-4xl mx-auto space-y-4" data-testid="posting-detail">
        {backLink}
        <p className="text-sm text-rose-600" role="alert">
          {error}
        </p>
      </div>
    );
  }
  if (!posting) {
    return <p className="text-sm text-slate-400">{t("postingDetail.loadingPosting")}</p>;
  }

  const extract: Extract | null = posting.extract ?? null;

  const provenance =
    posting.extract_version != null
      ? "extracted"
      : posting.mapping_method
        ? "fast-mapped"
        : "raw";
  const match = posting.match ?? null;
  const originalUrl = safeExternalUrl(posting.url);
  const location = [posting.location?.city, posting.location?.country].filter(Boolean).join(", ");
  const hoursRange =
    posting.hours_per_week_min != null || posting.hours_per_week_max != null
      ? t("postingDetail.hoursPerWeek", {
          range: [posting.hours_per_week_min, posting.hours_per_week_max]
            .filter((v) => v != null)
            .join("–"),
        })
      : "";
  const hoursValue = [valueLabel(posting.work_hours), hoursRange].filter(Boolean).join(" · ");
  const onsiteValue = [
    posting.location?.remote ? t("postingCard.remote") : null,
    valueLabel(posting.onsite_policy),
    extract?.onsite_policy?.office_days_per_week != null
      ? t("postingDetail.officeDays", { count: extract.onsite_policy.office_days_per_week })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const travelValue = extract?.travel_required
    ? [
        valueLabel(extract.travel_required.level),
        extract.travel_required.days_per_month != null
          ? t("postingDetail.travelDays", { count: extract.travel_required.days_per_month })
          : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : posting.travel_class?.replace(/_/g, " ");
  const educationValue = [posting.education_level?.replace(/_/g, " "), extract?.education?.field]
    .filter(Boolean)
    .join(" · ");
  const salaryValue =
    posting.salary_min != null || posting.salary_max != null
      ? [
          [
            posting.salary_currency,
            [posting.salary_min, posting.salary_max]
              .filter((v) => v != null)
              .map((v) => Number(v).toLocaleString())
              .join("–"),
          ]
            .filter(Boolean)
            .join(" "),
          `/ ${posting.salary_period ?? t("postingDetail.year")}`,
          posting.salary_basis ? `(${t(`postingCard.salaryBasis.${posting.salary_basis}`)})` : "",
        ]
          .filter(Boolean)
          .join(" ")
      : null;

  const facts: Array<[string, string | null | undefined]> = [
    [t("postingDetail.fact.location"), location || null],
    [t("postingDetail.fact.remote"), onsiteValue || null],
    [t("postingDetail.fact.employment"), valueLabel(posting.employment_type)],
    [t("postingDetail.fact.contract"), valueLabel(posting.contract_type)],
    [t("postingDetail.fact.seniority"), posting.seniority ? t(`autopilot.seniority.${posting.seniority}`, { defaultValue: posting.seniority }) : null],
    [t("postingDetail.fact.hours"), hoursValue || null],
    [t("postingDetail.fact.travel"), travelValue || null],
    [t("postingDetail.fact.education"), educationValue || null],
    [t("postingDetail.fact.languages"), (extract?.languages ?? []).join(", ") || null],
    [t("postingDetail.fact.salary"), salaryValue],
  ];

  const scheduleCues = extract?.schedule_cues ?? [];
  const description = (posting.description ?? "").trim();
  const descriptionClean = (posting.extract?.description_clean ?? "").trim();

  return (
    <div className="ca-workspace max-w-6xl mx-auto space-y-4" data-testid="posting-detail">
      {backLink}
      <div className="ca-detail-cols grid gap-6">
        <div className="space-y-6 min-w-0">
          <header className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="space-y-1 min-w-0">
                <h1 className="text-xl font-semibold text-slate-900">{posting.title}</h1>
                <div className="flex items-center gap-2 flex-wrap text-sm">
                  {posting.org_key ? (
                    <Link
                      to={`/companies/${posting.org_key}`}
                      className="font-medium text-slate-700 hover:text-primary-700"
                    >
                      {posting.org}
                    </Link>
                  ) : (
                    <span className="font-medium text-slate-700">{posting.org}</span>
                  )}
                  <span
                    className="text-xs font-mono text-slate-400 border border-slate-200 rounded px-1.5 py-0.5"
                    title={t("postingDetail.refTitle")}
                    data-testid="posting-ref"
                  >
                    {posting.ref}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
                  {posting.source_key || posting.ref}
                </span>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    provenance === "extracted"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                  data-testid="provenance"
                >
                  {t(`postingCard.provenanceValue.${provenance}`, { defaultValue: provenance })}
                </span>
                {posting.needs_review && (
                  <span
                    className="px-2 py-0.5 rounded text-xs bg-amber-50 text-amber-700"
                    data-testid="needs-review"
                  >
                    {t("postingCard.needsReview")}
                  </span>
                )}
                {posting.coverage != null && (
                  <span
                    className="px-2 py-0.5 rounded text-xs bg-primary-50 text-primary-700"
                    data-testid="coverage"
                  >
                    {t("postingDetail.coverage", { score: posting.coverage.toFixed(1) })}
                  </span>
                )}
                {posting.applied_at && (
                  <span className="text-xs text-emerald-600">{t("postingCard.applied")}</span>
                )}
              </div>
            </div>
            {extractNote ? (
              <p role="status" className="text-xs text-[var(--as-muted-fg)]" data-testid="reextract-note">
                {extractNote}
              </p>
            ) : null}
            <div className="flex items-center gap-2 flex-wrap">
              {originalUrl && (
                <Button asChild size="sm">
                  <a
                    href={originalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="open-original"
                    onClick={() => {
                      void markPostingsSeen([posting.id]).catch(() => undefined);
                      void markApplied(posting.id, posting.url).catch(() => undefined);
                    }}
                  >
                    <ExternalLink className="mr-1 h-3.5 w-3.5" />
                    {t("postingDetail.openOnSource", {
                      source: posting.source_title || posting.source_key || t("postingDetail.source"),
                    })}
                  </a>
                </Button>
              )}
              {posting.application_id ? (
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="open-application"
                  onClick={() => navigate(`/applications?application=${posting.application_id}`)}
                >
                  <Target className="mr-1 h-3.5 w-3.5" />
                  {t("postingDetail.openApplication")}
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={trackBusy}
                  onClick={() => void track()}
                  data-testid="track-application"
                >
                  <Target className="mr-1 h-3.5 w-3.5" />
                  {t("postingDetail.trackApplication")}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                disabled={letterBusy}
                onClick={() => void draftLetter()}
                data-testid="draft-cover-letter"
              >
                <Sparkles className="mr-1 h-3.5 w-3.5" />
                {t("postingDetail.draftLetter")}
              </Button>
              {isAdmin ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={extractBusy}
                  onClick={() =>
                    void (async () => {
                      setExtractBusy(true);
                      setExtractNote("");
                      try {
                        await reextractPosting(posting.id);
                        setExtractNote(t("jobDetail.reextractQueued"));
                      } catch (err) {
                        setExtractNote(err instanceof Error ? err.message : String(err));
                      } finally {
                        setExtractBusy(false);
                      }
                    })()
                  }
                  data-testid="reextract-posting"
                >
                  {t("jobDetail.reextract")}
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                disabled={interviewBusy}
                onClick={() => void practiceInterview()}
                data-testid="practice-interview-posting"
              >
                <GraduationCap className="mr-1 h-3.5 w-3.5" />
                {t("postingDetail.practiceInterview")}
              </Button>
              <Button variant="ghost" size="sm" onClick={toggleSave} data-testid="save-posting">
                {posting.saved ? t("postingCard.unsave") : t("common.save")}
              </Button>
              <Button variant="ghost" size="sm" onClick={hide} data-testid="hide-posting">
                {t("postingCard.hide")}
              </Button>
            </div>
            {interviewError && (
              <p role="alert" className="text-xs text-red-600" data-testid="interview-error">
                {interviewError}
              </p>
            )}
            {letterError && (
              <p role="alert" className="text-xs text-red-600" data-testid="letter-error">
                {letterError}
              </p>
            )}
            {trackError && (
              <p role="alert" className="text-xs text-red-600" data-testid="track-error">
                {trackError}
              </p>
            )}
          </header>

          <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-700">
                {t("postingDetail.descriptionHeading")}
              </h2>
              {description ? (
                <button
                  type="button"
                  className="text-xs text-slate-400 hover:text-slate-600"
                  onClick={() => setShowRawDescription((v) => !v)}
                  data-testid="description-raw-toggle"
                >
                  {showRawDescription
                    ? t("postingDetail.hideOriginal")
                    : t("postingDetail.showOriginal")}
                </button>
              ) : null}
            </div>
            {showRawDescription && description ? (
              <>
                <p
                  className={`text-sm text-slate-600 whitespace-pre-wrap ${
                    descriptionOpen ? "" : "line-clamp-6"
                  }`}
                  data-testid="posting-description-raw"
                >
                  {description}
                </p>
                <button
                  type="button"
                  className="text-xs text-primary-700 hover:underline"
                  onClick={() => setDescriptionOpen((v) => !v)}
                  data-testid="description-toggle"
                >
                  {descriptionOpen ? t("postingDetail.showLess") : t("postingDetail.showMore")}
                </button>
              </>
            ) : descriptionClean ? (
              <div
                className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed"
                data-testid="posting-description"
              >
                {descriptionClean}
              </div>
            ) : (
              <p className="text-sm text-slate-400" data-testid="posting-description">
                {t("postingDetail.noDescription")}
              </p>
            )}
          </section>

          {skillGroups.length > 0 && (
            <section
              className="bg-white border border-slate-200 rounded-xl p-4 space-y-3"
              data-testid="extract-skills"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-700">
                  {t("postingDetail.skillsHeading")}
                </h2>
                <SegmentedTabs
                  items={[
                    { value: "compact", label: t("postingDetail.skillsCompact") },
                    { value: "detailed", label: t("postingDetail.skillsDetailed") },
                  ]}
                  value={skillsView}
                  onValueChange={(value) => setSkillsView(value as "compact" | "detailed")}
                  ariaLabel={t("postingDetail.skillsHeading")}
                />
              </div>
              {skillGroups.map((group) => (
                <div key={group.priority} className="space-y-1.5">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-[var(--as-muted-fg)]">
                      {t(`postingDetail.priority.${group.priority}`, {
                        defaultValue: group.priority.replace(/_/g, " "),
                      })}
                    </span>
                    <span className="text-[11px] text-[var(--as-border)]">
                      · {t("postingDetail.skillsCount", { count: group.skills.length })}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {skillsView === "compact"
                      ? group.skills.map((skill) => <CompactSkillChip key={skill.key} skill={skill} />)
                      : group.skills.map((skill) => <SkillChip key={skill.key} skill={skill} />)}
                  </div>
                </div>
              ))}
            </section>
          )}

          {match && <MatchCard match={match} />}

          {(extract?.prerequisites?.length ?? 0) > 0 && (
            <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-700">
                {t("postingDetail.prerequisitesHeading")}
              </h2>
              <ul className="space-y-1" data-testid="extract-prerequisites">
                {(extract?.prerequisites ?? []).map((prereq, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm text-slate-600">
                    <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded uppercase">
                      {t(`postingDetail.prereqKind.${prereq.kind}`, { defaultValue: prereq.kind })}
                    </span>
                    <span>{prereq.label}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(extract?.responsibilities?.length ?? 0) > 0 && (
            <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-700">
                {t("postingDetail.responsibilitiesHeading")}
              </h2>
              <ul className="space-y-1" data-testid="extract-responsibilities">
                {(extract?.responsibilities ?? []).map((r, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm text-slate-600">
                    <span>{r.text}</span>
                    {r.time_pct != null && (
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                        {t("postingDetail.timePct", { percent: r.time_pct })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {provenance !== "extracted" && (
            <p className="text-xs text-slate-400">{t("postingDetail.noExtraction")}</p>
          )}

          {(posting.similar?.length ?? 0) > 0 && (
            <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
              <h2 className="text-sm font-semibold text-slate-700">
                {t("postingDetail.similarHeading")}
              </h2>
              <div className="flex flex-col gap-1" data-testid="similar-rail">
                {posting.similar?.map((s) => (
                  <button
                    key={s.ref}
                    onClick={() => navigate(`/postings/${s.ref}`)}
                    className="text-left text-xs text-slate-600 hover:text-primary-700 flex items-center justify-between border border-slate-100 rounded-lg px-2 py-1.5"
                  >
                    <span>
                      <span className="font-mono text-slate-400 mr-1.5">{s.ref}</span>
                      {s.title} · {s.org}
                    </span>
                    <span className="text-slate-400">{Math.round(s.score * 100)}%</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>

        <div className="space-y-6 min-w-0">
          <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2">
            <h2 className="text-sm font-semibold text-slate-700">
              {t("postingDetail.factsHeading")}
            </h2>
            <dl className="space-y-1" data-testid="posting-facts">
              {facts.map(([label, value]) =>
                value ? (
                  <div key={label} className="flex gap-3 text-sm">
                    <dt className="text-slate-400 w-28 shrink-0">{label}</dt>
                    <dd className="text-slate-700">{value}</dd>
                  </div>
                ) : null,
              )}
            </dl>
            {(posting.salary_normalized_min != null || posting.salary_normalized_max != null) && (
              <p className="text-xs text-slate-400" data-testid="salary-annualized">
                {t("postingDetail.salaryAnnual", {
                  range: [posting.salary_normalized_min, posting.salary_normalized_max]
                    .filter((v) => v != null)
                    .map((v) => Number(v).toLocaleString())
                    .join("–"),
                  currency: posting.salary_currency ?? "",
                })}
              </p>
            )}
            {scheduleCues.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1" data-testid="posting-schedule">
                {scheduleCues.map((cue) => (
                  <span
                    key={cue.cue}
                    className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded"
                    title={cue.evidence_quote}
                  >
                    {valueLabel(cue.cue)}
                  </span>
                ))}
              </div>
            )}
          </section>

          <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-1">
            <h2 className="text-sm font-semibold text-slate-700">
              {t("postingDetail.timelineHeading")}
            </h2>
            <div data-testid="posting-timeline">
              <TimelineRow label={t("postingDetail.time.posted")} iso={posting.posted_at} />
              <TimelineRow label={t("postingDetail.time.firstSeen")} iso={posting.created_at} />
              <TimelineRow label={t("postingDetail.time.updated")} iso={posting.updated_at} />
              <TimelineRow label={t("postingDetail.time.expires")} iso={posting.expires_at} />
            </div>
            {(posting.status === "expired" ||
              (posting.expires_at != null && new Date(posting.expires_at) < new Date())) && (
              <span
                className="inline-block text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded"
                data-testid="posting-closed"
              >
                {t("postingDetail.closed")}
              </span>
            )}
          </section>

          <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
            <h2 className="text-sm font-semibold text-slate-700">
              {t("postingDetail.categoriesHeading")}
            </h2>
            {posting.catalog_job && (
              <div className="space-y-1">
                <p className="text-xs text-slate-400">{t("postingDetail.mappedRole")}</p>
                <Link
                  to={`/jobs/${posting.catalog_job.code}`}
                  className="text-sm text-primary-700 hover:underline"
                  data-testid="mapped-job"
                >
                  {posting.catalog_job.title}
                </Link>
                {posting.catalog_job.family_label && (
                  <p className="text-xs text-slate-500">{posting.catalog_job.family_label}</p>
                )}
              </div>
            )}
            {(posting.catalog_job?.interests?.length ?? 0) > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-slate-400">{t("postingDetail.interests")}</p>
                <div className="flex flex-wrap gap-1">
                  {(posting.catalog_job?.interests ?? []).map((tag) => (
                    <span
                      key={tag.key}
                      className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded"
                    >
                      {tag.label}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(extract?.benefits?.length ?? 0) > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-slate-400">{t("postingDetail.benefitsHeading")}</p>
                <div className="flex flex-wrap gap-1" data-testid="extract-benefits">
                  {(extract?.benefits ?? []).map((benefit, i) => (
                    <span
                      key={`${benefit.kind}-${i}`}
                      className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded"
                      title={t(`postingDetail.benefitKind.${benefit.kind}`, {
                        defaultValue: benefit.kind.replace(/_/g, " "),
                      })}
                    >
                      {benefit.raw}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>

          <section
            className="bg-slate-50 border border-slate-100 rounded-xl p-3 space-y-1 text-xs text-slate-400"
            data-testid="source-attribution"
          >
            <p>
              {t("postingDetail.sourceLabel")}{" "}
              <span className="text-slate-600">
                {posting.source_title ||
                  posting.source_connector ||
                  posting.source_key ||
                  t("postingDetail.unknown")}
              </span>
            </p>
            {posting.source_synced_at && (
              <p>
                {t("postingDetail.synced", {
                  date: new Date(posting.source_synced_at).toLocaleDateString(),
                })}
              </p>
            )}
            {originalUrl && (
              <a
                href={originalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary-700 hover:underline"
              >
                <ExternalLink className="w-3 h-3" /> {t("postingDetail.originalListing")}
              </a>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
