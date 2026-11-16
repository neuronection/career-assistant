import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bookmark, ExternalLink, EyeOff } from "lucide-react";
import { fetchJob, fetchJobRelations, publishJob } from "@/api/jobs";
import { fetchJobMatchDetail, rateJob, scoreJobForMe } from "@/api/matching";
import { fetchJobPathGraph, fetchJobPaths } from "@/api/paths";
import { PathRenderer } from "@/features/paths/PathRenderer";
import { buildPathView } from "@/features/paths/viewModel";
import { fetchSkillGaps } from "@/api/skills";
import { hideJob, markSeen, saveJob } from "@/api/engagement";
import { fetchMarketSnapshot, fetchMarketTrend, type MarketTrendPoint } from "@/api/growth";
import { AiButton } from "@/components/AiButton";
import { DemandBadge } from "@/features/postings/components/DemandBadge";
import { ScoreLegend } from "@/features/catalog/components/ScoreLegend";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import { MarketTrendStrip } from "@/features/postings/components/MarketTrendStrip";
import { ScoreBreakdown } from "@/components/score/ScoreBreakdown";
import { rankedDimensions } from "@/features/catalog/components/RankedJobCard";
import { JobMatchRails } from "@/features/catalog/components/JobMatchRails";
import { EmptyState, RangeBar, Table } from "@/components/ui";
import { useCompareStore } from "@/stores/compareStore";
import { useTranslation } from "react-i18next";
import { formatNumber } from "@/lib/format";
import { apiDetail } from "@/api/client";
import type { CareerPath, Job, JobLink, MarketSnapshot, MatchInsight, MatchStatus, Relation, SkillGapReport } from "@/types/wire";
import type { JobMatchDetail } from "@/types";

const EDUCATION_LABEL: Record<string, string> = {
  no_formal: "jobDetail.educationLevel.no_formal",
  middle_school: "jobDetail.educationLevel.middle_school",
  high_school: "jobDetail.educationLevel.high_school",
  vocational: "jobDetail.educationLevel.vocational",
  bachelor: "jobDetail.educationLevel.bachelor",
  master: "jobDetail.educationLevel.master",
  doctorate: "jobDetail.educationLevel.doctorate",
};

const LINK_KIND_LABEL: Record<JobLink["kind"], string> = {
  apply: "jobDetail.linkKind.apply",
  learn: "jobDetail.linkKind.learn",
  certification: "jobDetail.linkKind.certification",
  video: "jobDetail.linkKind.video",
};

export function JobDetail() {
  const { t } = useTranslation();
  const { code = "" } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [relations, setRelations] = useState<Relation[]>([]);
  const [detail, setDetail] = useState<JobMatchDetail | null>(null);
  const [insight, setInsight] = useState<MatchInsight | null>(null);
  const [userScore, setUserScore] = useState<number | null>(null);
  const [status, setStatus] = useState<MatchStatus | null>(null);
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [gaps, setGaps] = useState<SkillGapReport | null>(null);
  const [paths, setPaths] = useState<CareerPath[]>([]);
  const [pathNodes, setPathNodes] = useState<{ code: string; title: string; depth: number }[]>([]);
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [trend, setTrend] = useState<MarketTrendPoint[]>([]);
  const navigate = useNavigate();
  const comparing = useCompareStore((s) => (job ? s.items.some((i) => i.id === job.id) : false));
  const toggleCompare = useCompareStore((s) => s.toggle);

  useEffect(() => {
    void (async () => {
      try {
        const jobData = await fetchJob(code);
        setJob(jobData);
        const [rels, matchDetail] = await Promise.all([fetchJobRelations(code), fetchJobMatchDetail(code)]);
        setRelations(rels);
        setDetail(matchDetail);
        setInsight(matchDetail.insight);
        setUserScore(matchDetail.insight?.user_score ?? null);
        setStatus(matchDetail.insight?.status ?? null);
        setNotes(matchDetail.insight?.user_notes ?? "");
        setSaved(matchDetail.insight?.saved_at != null);
        setHidden(matchDetail.insight?.hidden_at != null);
        void markSeen([jobData.id]).catch(() => undefined);
        void fetchMarketSnapshot({ job_id: jobData.id })
          .then(setSnapshot)
          .catch(() => setSnapshot(null));
        void fetchMarketTrend({ job_id: jobData.id })
          .then(setTrend)
          .catch(() => setTrend([]));
      } catch (err) {
        setError(apiDetail(err));
      }
    })();
    void (async () => {
      try {
        setGaps(await fetchSkillGaps(code));
      } catch {
        setGaps(null);
      }
    })();
    void (async () => {
      try {
        const [curated, graph] = await Promise.all([
          fetchJobPaths(code),
          fetchJobPathGraph(code),
        ]);
        setPaths(curated);
        setPathNodes((graph.nodes ?? []).filter((n) => n.depth > 0));
      } catch {
        setPaths([]);
        setPathNodes([]);
      }
    })();
  }, [code]);

  const score = async () => {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      setInsight(await scoreJobForMe(job));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const fitScore = insight?.fit_score != null ? Number(insight.fit_score) : null;
  const aiScore = insight?.ai_score != null ? Number(insight.ai_score) : null;
  const matchScore =
    fitScore != null
      ? Math.round((0.6 * fitScore + 0.4 * (aiScore ?? fitScore)) * 100) / 100
      : null;

  const saveRating = async (nextScore: number | null, nextStatus: MatchStatus | null) => {
    if (!job) return;
    try {
      const savedInsight = await rateJob({
        job_id: job.id,
        user_score: nextScore ?? undefined,
        status: nextStatus ?? undefined,
        notes: notes || undefined,
      });
      setInsight(savedInsight);
      setUserScore(savedInsight.user_score ?? null);
      setStatus(savedInsight.status ?? null);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const toggleSaved = async () => {
    if (!job) return;
    setSaved((v) => !v);
    try {
      await saveJob(job.id, !saved);
    } catch {
      setSaved(saved);
    }
  };

  const toggleHidden = async () => {
    if (!job) return;
    setHidden((v) => !v);
    try {
      await hideJob(job.id, !hidden);
    } catch {
      setHidden(hidden);
    }
  };

  if (error && !job) return <p className="text-[var(--as-danger)]">{error}</p>;
  if (!job) return <p className="text-[var(--as-muted-fg)]">{t("common.loading")}</p>;
  const attrs = job.attributes;

  return (
    <div className="space-y-6 max-w-5xl mx-auto" data-testid="job-detail">
      <div className="flex items-start justify-between gap-4">
        <div>
          <button onClick={() => navigate(-1)} className="text-sm text-[var(--as-muted-fg)] hover:text-[var(--as-muted-fg)]">{t("common.back")}</button>
          {job.status === "retired" && (
            <div
              className="mt-2 rounded-lg border border-[color-mix(in_srgb,var(--as-warning)_25%,transparent)] bg-[color-mix(in_srgb,var(--as-warning)_8%,transparent)] px-3 py-2 text-sm text-[var(--as-warning)]"
              data-testid="job-retired-banner"
            >
              {t("jobDetail.retiredBanner")}{" "}
              {job.retired_into ? (
                <Link to={`/jobs/${job.retired_into.code}`} className="font-medium underline">
                  {t("jobDetail.retiredSuccessor", {
                    title: job.retired_into.title || job.retired_into.code,
                  })}
                </Link>
              ) : null}
            </div>
          )}
          <h1 className="text-2xl font-bold text-[var(--as-fg)] flex items-center gap-3">
            {job.title} <DemandBadge outlook={attrs?.demand?.outlook} />
          </h1>
          <p className="text-[var(--as-muted-fg)] mt-1 max-w-2xl">{job.short_description}</p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-[var(--as-muted-fg)]">
            <span data-testid="job-open-roles">
              {t("jobDetail.openRoles", { count: job.open_roles ?? 0 })}
            </span>
            <Link
              to={`/postings?job=${job.code}`}
              data-testid="job-browse-postings"
              className="font-medium text-[var(--as-accent)] hover:underline"
            >
              {t("jobDetail.browsePostings")} →
            </Link>
          </div>
          <div className="mt-2 flex gap-2 items-center">
            <AiButton
              page="job_detail"
              jobCode={job.code}
              question={t("jobDetail.aiWhyQuestion")}
              label={t("jobDetail.aiWhyLabel")}
            />
            <AiButton
              page="job_detail"
              jobCode={job.code}
              question={t("jobDetail.aiStudyQuestion")}
              label={t("jobDetail.aiStudyLabel")}
            />
            <button
              onClick={() => void toggleSaved()}
              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${
                saved ? "bg-[var(--as-accent)] text-[var(--as-primary-fg)] border-[var(--as-accent)]" : "border-[var(--as-border)] text-[var(--as-muted-fg)]"
              }`}
              data-testid="save-job"
            >
              <Bookmark className={`w-3.5 h-3.5 ${saved ? "fill-white" : ""}`} />
              {saved ? t("jobDetail.saved") : t("jobDetail.save")}
            </button>
            <button
              onClick={() => void toggleHidden()}
              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${
                hidden ? "bg-[var(--as-fg)] text-[var(--as-surface)] border-[var(--as-fg)]" : "border-[var(--as-border)] text-[var(--as-muted-fg)]"
              }`}
              data-testid="hide-job"
              title={t("jobDetail.hideTitle")}
            >
              <EyeOff className="w-3.5 h-3.5" />
              {hidden ? t("jobDetail.hidden") : t("jobDetail.hide")}
            </button>
            <button
              onClick={() => toggleCompare({ id: job.id, title: job.title })}
              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${
                comparing ? "bg-[var(--as-success)] text-[var(--as-success-fg)] border-[var(--as-success)]" : "border-[var(--as-border)] text-[var(--as-muted-fg)]"
              }`}
              data-testid="add-compare"
              title={t("jobDetail.addToComparison")}
            >
              ⇄
              {comparing ? t("jobDetail.comparing") : t("jobDetail.compare")}
            </button>
          </div>
        </div>
        <div className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4 shrink-0" data-testid="job-score-card">
          <div className="flex items-center gap-4">
            <div className="flex flex-col items-center gap-0.5">
              <ScoreBubble score={matchScore} size={72} />
              <span className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("rankings.match")}
                <ScoreLegend />
              </span>
            </div>
            <div className="flex items-center gap-4 px-4 border-l border-[var(--as-border)] self-stretch" data-testid="job-scores">
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">{t("rankings.fit")}</p>
                <p className="text-sm font-semibold text-[var(--as-fg)]">{fitScore != null ? fitScore.toFixed(1) : "–"}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">{t("rankings.aiScore")}</p>
                <p className="text-sm font-semibold text-[var(--as-fg)]">{aiScore != null ? aiScore.toFixed(1) : "–"}</p>
              </div>
              <div className="text-center">
                <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">{t("rankings.yourScore")}</p>
                <p className="text-sm font-semibold text-[var(--as-fg)]">{userScore ?? "–"}</p>
              </div>
            </div>
          </div>
          {aiScore == null ? (
            <button
              onClick={() => void score()}
              disabled={busy}
              className="mt-3 w-full text-xs bg-[var(--as-accent)] text-[var(--as-primary-fg)] rounded-lg px-3 py-1.5 disabled:opacity-50"
            >
              {busy ? t("jobDetail.scoring") : t("jobDetail.scoreForMe")}
            </button>
          ) : (
            <button onClick={() => void score()} disabled={busy} className="mt-3 w-full text-xs text-[var(--as-accent)]">
              {t("jobDetail.rescore")}
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-[var(--as-danger)]">{error}</p>}

      {insight?.fit_breakdown && (
        <section className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4" data-testid="fit-breakdown-panel">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-medium">{t("jobDetail.whyThisFits")}</h3>
            {insight.fit_breakdown.specialist_dimension && (
              <span className="text-xs bg-[color-mix(in_srgb,var(--as-warning)_12%,transparent)] text-[var(--as-warning)] px-2 py-0.5 rounded-full">
                {t("jobDetail.strongIn")} {insight.fit_breakdown.specialist_dimension}
              </span>
            )}
          </div>
          <ScoreBreakdown
            dimensions={rankedDimensions(insight.fit_breakdown, t)}
            defaultWeight={3}
            showDetails
            detailsLayout="inline"
            testId="fit-breakdown"
            detailsTestId="fit-breakdown-detail"
          />
        </section>
      )}

      {insight && (
        <section className="grid md:grid-cols-2 gap-4">
          <div className="bg-[color-mix(in_srgb,var(--as-success)_8%,transparent)] border border-[color-mix(in_srgb,var(--as-success)_25%,transparent)] rounded-xl p-4">
            <h3 className="font-medium text-[var(--as-success)] mb-2">{t("jobDetail.positivesForYou")}</h3>
            <ul className="space-y-2">
              {insight.ai_positives.map((p, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{p.title}</span>
                  {p.detail && <span className="text-[var(--as-muted-fg)]"> — {p.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-[color-mix(in_srgb,var(--as-danger)_8%,transparent)] border border-[color-mix(in_srgb,var(--as-danger)_25%,transparent)] rounded-xl p-4">
            <h3 className="font-medium text-[var(--as-danger)] mb-2">{t("jobDetail.negativesForYou")}</h3>
            <ul className="space-y-2">
              {insight.ai_negatives.map((n, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{n.title}</span>
                  {n.detail && <span className="text-[var(--as-muted-fg)]"> — {n.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
          {insight.prerequisites.length > 0 && (
            <div className="md:col-span-2 bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4">
              <h3 className="font-medium mb-2">{t("jobDetail.prerequisites")}</h3>
              <ul className="space-y-1.5">
                {insight.prerequisites.map((p, i) => (
                  <li key={i} className="text-sm flex items-center gap-2">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                        p.status === "met"
                          ? "bg-[color-mix(in_srgb,var(--as-success)_12%,transparent)] text-[var(--as-success)]"
                          : p.status === "unmet"
                            ? "bg-[color-mix(in_srgb,var(--as-danger)_12%,transparent)] text-[var(--as-danger)]"
                            : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
                      }`}
                    >
                      {p.status}
                    </span>
                    {p.requirement}
                    {p.detail && <span className="text-[var(--as-muted-fg)]">· {p.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <section className="grid md:grid-cols-2 gap-4">
        <div className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4" data-testid="job-skills">
          <h3 className="font-medium mb-2">{t("jobDetail.skillsRequired")}</h3>
          {gaps && (gaps.gaps ?? []).length > 0 ? (
            <ul className="space-y-2">
              {(gaps.gaps ?? []).map((g) => (
                <li key={g.key} className="text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{g.label}</span>
                    <span className="text-xs text-[var(--as-muted-fg)]">
                      {g.importance}
                      {g.importance !== "bonus" ? ` · ${t("jobDetail.levelSuffix", { level: g.required_level })}` : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-[var(--as-muted)] rounded-full overflow-hidden">
                      <div
                        className={`h-1.5 rounded-full ${
                          g.user_level == null
                            ? "bg-[var(--as-muted-fg)]"
                            : (g.delta ?? 0) < 0
                              ? "bg-[color-mix(in_srgb,var(--as-warning)_8%,transparent)]"
                              : "bg-[color-mix(in_srgb,var(--as-success)_8%,transparent)]"
                        }`}
                        data-testid={`job-gap-bar-${g.key}`}
                        style={{
                          width: `${(Math.min(g.user_level ?? 0, g.required_level) / 10) * 100}%`,
                        }}
                      />
                    </div>
                    <span className={`text-xs ${g.user_level == null ? "text-[var(--as-muted-fg)]" : (g.delta ?? 0) < 0 ? "text-[var(--as-warning)]" : "text-[var(--as-success)]"}`}>
                      {t("jobDetail.youVsRequired", { you: g.user_level ?? "–", required: g.required_level })}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--as-muted-fg)] mt-0.5">{g.suggestion}</p>
                  {g.next_step && (
                    <p className="text-xs text-[var(--as-accent)] mt-0.5">{t("jobDetail.nextStep", { step: g.next_step })}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--as-muted-fg)]">
              {(job.skills ?? []).map((s) => s.label).join(", ") || t("jobDetail.noSpecificSkills")}
            </p>
          )}
        </div>
        <div className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4" data-testid="job-paths">
          <h3 className="font-medium mb-2">{t("jobDetail.yourPath")}</h3>
          {paths.length > 0 ? (
            <div className="space-y-3">
              {paths.slice(0, 2).map((path) => (
                <div key={path.id}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{path.title}</p>
                    <Link
                      to="/paths"
                      className="text-xs font-medium text-[var(--as-accent)] hover:underline"
                      data-testid="job-paths-open"
                    >
                      {t("jobDetail.openInPaths")}
                    </Link>
                  </div>
                  <div className="mt-1">
                    <PathRenderer view={buildPathView(path)} compact />
                  </div>
                </div>
              ))}
            </div>
          ) : pathNodes.length > 0 ? (
            <div>
              <p className="text-xs text-[var(--as-muted-fg)] mb-2">{t("jobDetail.commonlyLeadsHere")}</p>
              <div className="flex flex-wrap gap-2">
                {pathNodes.map((n) => (
                  <Link
                    key={n.code}
                    to={`/jobs/${n.code}`}
                    className="text-xs border border-[var(--as-border)] rounded-lg px-2 py-1 hover:border-[var(--as-accent)]"
                  >
                    {n.title}
                  </Link>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState compact title={t("jobDetail.noPathTitle")} description={t("jobDetail.noPathBody")} />
          )}
        </div>
      </section>

      <section className="grid md:grid-cols-3 gap-4">
        <InfoBlock title={t("jobDetail.education")}>
          <p>
            {t(EDUCATION_LABEL[attrs?.education?.level ?? ""] ?? attrs?.education?.level ?? "", {
              defaultValue: attrs?.education?.level ?? "",
            })}
          </p>
          {(attrs?.education?.fields ?? []).length > 0 && (
            <p className="text-[var(--as-muted-fg)]">{(attrs?.education?.fields ?? []).join(", ")}</p>
          )}
          {(job.links ?? []).length > 0 && (
            <div className="pt-2 space-y-1" data-testid="job-links">
              {(job.links ?? []).map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 text-[var(--as-accent)] hover:underline text-sm"
                >
                  <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                  {t(LINK_KIND_LABEL[link.kind])}: {link.label}
                </a>
              ))}
            </div>
          )}
        </InfoBlock>
        <InfoBlock title={t("jobDetail.marketSnapshot")}>
          {snapshot && snapshot.sample_size > 0 ? (
            <div className="text-sm space-y-0.5" data-testid="market-snapshot">
              <p>
                {t("jobDetail.livePostings", { count: snapshot.sample_size })}
                {(snapshot.months ?? []).length > 0 && (
                  <span className="text-[var(--as-muted-fg)]">
                    {" · "}
                    {t("jobDetail.last30d", {
                      count: (snapshot.months ?? [])[(snapshot.months ?? []).length - 1]?.postings ?? 0,
                    })}
                  </span>
                )}
              </p>
              {snapshot.salary_band ? (
                <p>
                  p25–p75: {snapshot.salary_band.p25 != null
                    ? formatNumber(snapshot.salary_band.p25)
                    : "—"}
                  –
                  {snapshot.salary_band.p75 != null
                    ? formatNumber(snapshot.salary_band.p75)
                    : "—"}
                </p>
              ) : (
                <p className="text-[var(--as-muted-fg)]">{t("jobDetail.salaryBandHidden", { sample: snapshot.sample_size })}</p>
              )}
              {(snapshot.top_skills ?? []).length > 0 && (
                <p className="text-[var(--as-muted-fg)]">
                  {t("jobDetail.demanded")}{" "}
                  {(snapshot.top_skills ?? []).slice(0, 4).map((s) => s.key).join(", ")}
                </p>
              )}
              <MarketTrendStrip history={trend} />
            </div>
          ) : (
            <p className="text-[var(--as-muted-fg)]">{t("jobDetail.noPostingsData")}</p>
          )}
        </InfoBlock>
        <InfoBlock title={t("jobDetail.salary")}>
          <RangeBar
            label={t("jobDetail.salaryMedian")}
            low={attrs?.salary?.median?.[0] ?? 0}
            high={attrs?.salary?.median?.[1] ?? 1}
            min={0}
            unit="USD"
            className="mb-2"
          />
          <RangeBar
            label={t("jobDetail.salaryRange")}
            low={attrs?.salary?.entry?.[0] ?? 0}
            high={attrs?.salary?.senior?.[1] ?? attrs?.salary?.median?.[1] ?? 1}
            min={0}
            unit="USD"
          />
        </InfoBlock>
        <InfoBlock title={t("jobDetail.physicalEnvironment")}>
          <p>{t("jobDetail.activity")}: {(attrs?.physical?.activity ?? "").replace(/_/g, " ")}</p>
          <p>{(attrs?.environments ?? []).join(", ").replace(/_/g, " ")}</p>
        </InfoBlock>
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <InfoBlock title={t("jobDetail.typicalPositives")}>
          <ul className="list-disc ml-4 space-y-1">
            {(attrs?.typical_positives ?? []).map((p, i) => (
              <li key={i} className="text-sm">{p.title}{p.detail && ` — ${p.detail}`}</li>
            ))}
          </ul>
        </InfoBlock>
        <InfoBlock title={t("jobDetail.typicalNegatives")}>
          <ul className="list-disc ml-4 space-y-1">
            {(attrs?.typical_negatives ?? []).map((n, i) => (
              <li key={i} className="text-sm">{n.title}{n.detail && ` — ${n.detail}`}</li>
            ))}
          </ul>
        </InfoBlock>
      </section>

      <section className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">{t("jobDetail.yourRating")}</h3>
          <div className="flex gap-2">
            {(["interested", "considering", "dismissed"] as MatchStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => void saveRating(userScore, s)}
                className={`text-xs px-3 py-1.5 rounded-full border ${
                  status === s ? "bg-[var(--as-accent)] text-[var(--as-primary-fg)] border-[var(--as-accent)]" : "border-[var(--as-border)]"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3 mt-3">
          <input
            type="range"
            min={0}
            max={10}
            value={userScore ?? 5}
            onChange={(e) => setUserScore(Number(e.target.value))}
            onMouseUp={() => void saveRating(userScore, status)}
            onTouchEnd={() => void saveRating(userScore, status)}
            className="flex-1"
          />
          <span className="text-lg font-semibold w-8 text-center">{userScore ?? "–"}</span>
        </div>
        <label className="block mt-3">
          <span className="text-xs font-medium text-[var(--as-muted-fg)] uppercase">{t("jobDetail.yourNotes")}</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => void saveRating(userScore, status)}
            rows={2}
            placeholder={t("jobDetail.notesPlaceholder")}
            className="mt-1 w-full border border-[var(--as-border)] rounded-lg px-3 py-2 text-sm"
            data-testid="job-notes"
          />
        </label>
      </section>

      <section>
        <h3 className="font-medium mb-2">{t("jobDetail.relatedJobs")}</h3>
        {relations.length === 0 ? (
          <EmptyState compact title={t("jobDetail.noRelationsTitle")} description={t("jobDetail.noRelationsBody")} />
        ) : (
          <div className="flex flex-wrap gap-2">
            {relations.map((r) => {
              const other = r.from_code === job.code ? r.to_code : r.from_code;
              return (
                <Link
                  key={r.id}
                  to={`/jobs/${other}`}
                  className="text-sm border border-[var(--as-border)] rounded-lg px-3 py-1.5 hover:border-[var(--as-accent)]"
                >
                  <span className="text-[var(--as-muted-fg)] text-xs block">{r.relation_type.replace(/_/g, " ")}</span>
                  {r.from_code === job.code ? r.to_title : r.from_title}
                </Link>
              );
            })}
          </div>
        )}
        {job.source === "ai" && (
          <button
            onClick={async () => {
              const updated = await publishJob(job.code);
              setJob(updated);
            }}
            className="mt-3 text-sm bg-[var(--as-success)] text-[var(--as-success-fg)] rounded-lg px-3 py-1.5"
          >
            {t("jobDetail.publishToCatalog")}
          </button>
        )}
      </section>

      <JobMatchRails jobCode={job.code} />

      {detail && detail.university_pathways.length > 0 && (
        <section>
          <h3 className="font-medium mb-2">{t("jobDetail.universityPathways")}</h3>
          <div className="space-y-3">
            {detail.university_pathways.map((p, i) => (
              <div key={i} className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <Link to={`/universities/${p.department.university.id}`} className="font-medium hover:text-[var(--as-accent)]">
                      {p.department.university.name}
                    </Link>
                    <p className="text-sm text-[var(--as-muted-fg)]">
                      {p.department.name} · {p.department.degree} · {p.department.duration_years}y
                      {p.department.application_deadline && (
                        <span className="text-[var(--as-warning)]"> · {t("jobDetail.appliesBy", { date: p.department.application_deadline })}</span>
                      )}
                    </p>
                  </div>
                  <span className="text-sm text-[var(--as-muted-fg)]">{t("jobDetail.relevance", { score: p.relevance })}</span>
                </div>
                {p.admissions.length > 0 && (
                  <Table
                    className="mt-3"
                    headers={[t("jobDetail.year"), t("jobDetail.baseline"), t("jobDetail.units")]}
                    rows={p.admissions.map((a) => [String(a.year), String(a.baseline_score ?? "–"), a.units])}
                  />
                )}
                {p.required_subjects.length > 0 && (
                  <p className="text-sm text-[var(--as-muted-fg)] mt-2">{t("jobDetail.subjects")}: {p.required_subjects.join(", ")}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function InfoBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[var(--as-surface)] border border-[var(--as-border)] rounded-xl p-4">
      <h3 className="font-medium mb-2">{title}</h3>
      <div className="text-sm space-y-0.5 text-[var(--as-fg)]">{children}</div>
    </div>
  );
}
