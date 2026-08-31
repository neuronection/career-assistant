import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bookmark, ExternalLink, EyeOff } from "lucide-react";
import { fetchJob, fetchJobRelations, publishJob } from "@/api/jobs";
import { fetchJobMatchDetail, rateJob, scoreJobForMe } from "@/api/matching";
import { fetchJobPathGraph, fetchJobPaths, fetchSkillGaps } from "@/api/skills";
import { hideJob, markSeen, saveJob } from "@/api/engagement";
import { fetchMarketSnapshot } from "@/api/growth";
import { AiButton } from "@/components/AiButton";
import { DemandBadge } from "@/components/DemandBadge";
import { ScoreRing } from "@/components/ScoreRing";
import { FitBars } from "@/pages/Rankings";
import { EmptyState, RangeBar, Table } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type {
  CareerPath,
  Job,
  JobLink,
  JobMatchDetail,
  MarketSnapshot,
  MatchInsight,
  MatchStatus,
  Relation,
  SkillGapReport,
} from "@/types";

const EDUCATION_LABEL: Record<string, string> = {
  no_formal: "No formal education",
  middle_school: "Middle school",
  high_school: "High school",
  vocational: "Vocational training",
  bachelor: "Bachelor's degree",
  master: "Master's degree",
  doctorate: "Doctorate",
};

const LINK_KIND_LABEL: Record<JobLink["kind"], string> = {
  apply: "Apply",
  learn: "Learn more",
  certification: "Certification",
  video: "Video",
};

export function JobDetail() {
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
  const navigate = useNavigate();

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
        setPathNodes(graph.nodes.filter((n) => n.depth > 0));
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
      setUserScore(savedInsight.user_score);
      setStatus(savedInsight.status);
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

  if (error && !job) return <p className="text-rose-600">{error}</p>;
  if (!job) return <p className="text-slate-400">Loading…</p>;
  const attrs = job.attributes;

  return (
    <div className="space-y-6 max-w-5xl mx-auto" data-testid="job-detail">
      <div className="flex items-start justify-between gap-4">
        <div>
          <button onClick={() => navigate(-1)} className="text-sm text-slate-400 hover:text-slate-600">← back</button>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-3">
            {job.title} <DemandBadge outlook={attrs?.demand?.outlook} />
          </h1>
          <p className="text-slate-500 mt-1 max-w-2xl">{job.short_description}</p>
          <div className="mt-2 flex gap-2 items-center">
            <AiButton page="job_detail" jobCode={job.code} question="Why does this match me?" label="Why me?" />
            <AiButton page="job_detail" jobCode={job.code} question="What would I study for this?" label="Study path?" />
            <button
              onClick={() => void toggleSaved()}
              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${
                saved ? "bg-primary-600 text-white border-primary-600" : "border-slate-200 text-slate-600"
              }`}
              data-testid="save-job"
            >
              <Bookmark className={`w-3.5 h-3.5 ${saved ? "fill-white" : ""}`} />
              {saved ? "Saved" : "Save"}
            </button>
            <button
              onClick={() => void toggleHidden()}
              className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1 ${
                hidden ? "bg-slate-700 text-white border-slate-700" : "border-slate-200 text-slate-600"
              }`}
              data-testid="hide-job"
              title="Hide from your feed (curation only — your status stays)"
            >
              <EyeOff className="w-3.5 h-3.5" />
              {hidden ? "Hidden" : "Hide"}
            </button>
          </div>
        </div>
        <div className="flex flex-col items-center gap-2 bg-white border border-slate-200 rounded-xl p-4">
          <ScoreRing score={insight?.ai_score != null ? Number(insight.ai_score) : null} size={72} />
          <span className="text-xs text-slate-400">AI match</span>
          {insight?.ai_generated_at ? (
            <span className="text-xs text-slate-400">{Number(insight.ai_score).toFixed(1)}/10</span>
          ) : (
            <button
              onClick={() => void score()}
              disabled={busy}
              className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
            >
              {busy ? "Scoring…" : "Score for me"}
            </button>
          )}
          {insight?.ai_generated_at && (
            <button onClick={() => void score()} disabled={busy} className="text-xs text-primary-700">
              re-score
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {insight?.fit_breakdown && (
        <section className="bg-white border border-slate-200 rounded-xl p-4" data-testid="fit-breakdown-panel">
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-medium">Why this fits — dimension by dimension</h3>
            {insight.fit_breakdown.specialist_dimension && (
              <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
                Strong in {insight.fit_breakdown.specialist_dimension}
              </span>
            )}
          </div>
          <FitBars breakdown={insight.fit_breakdown} />
        </section>
      )}

      {insight && (
        <section className="grid md:grid-cols-2 gap-4">
          <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4">
            <h3 className="font-medium text-emerald-800 mb-2">Positives for you</h3>
            <ul className="space-y-2">
              {insight.ai_positives.map((p, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{p.title}</span>
                  {p.detail && <span className="text-slate-600"> — {p.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
          <div className="bg-rose-50 border border-rose-100 rounded-xl p-4">
            <h3 className="font-medium text-rose-800 mb-2">Negatives for you</h3>
            <ul className="space-y-2">
              {insight.ai_negatives.map((n, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{n.title}</span>
                  {n.detail && <span className="text-slate-600"> — {n.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
          {insight.prerequisites.length > 0 && (
            <div className="md:col-span-2 bg-white border border-slate-200 rounded-xl p-4">
              <h3 className="font-medium mb-2">Prerequisites</h3>
              <ul className="space-y-1.5">
                {insight.prerequisites.map((p, i) => (
                  <li key={i} className="text-sm flex items-center gap-2">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                        p.status === "met"
                          ? "bg-emerald-100 text-emerald-700"
                          : p.status === "unmet"
                            ? "bg-rose-100 text-rose-700"
                            : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {p.status}
                    </span>
                    {p.requirement}
                    {p.detail && <span className="text-slate-400">· {p.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <section className="grid md:grid-cols-2 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="job-skills">
          <h3 className="font-medium mb-2">Skills required</h3>
          {gaps && gaps.gaps.length > 0 ? (
            <ul className="space-y-2">
              {gaps.gaps.map((g) => (
                <li key={g.key} className="text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{g.label}</span>
                    <span className="text-xs text-slate-400">
                      {g.importance}
                      {g.importance !== "bonus" ? ` · level ${g.required_level}/10` : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-1.5 rounded-full ${
                          g.user_level == null
                            ? "bg-slate-300"
                            : (g.delta ?? 0) < 0
                              ? "bg-amber-500"
                              : "bg-emerald-500"
                        }`}
                        style={{
                          width: `${(Math.min(g.user_level ?? 0, g.required_level) / 10) * 100}%`,
                        }}
                      />
                    </div>
                    <span className={`text-xs ${g.user_level == null ? "text-slate-400" : (g.delta ?? 0) < 0 ? "text-amber-600" : "text-emerald-600"}`}>
                      you: {g.user_level ?? "–"}/{g.required_level}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">{g.suggestion}</p>
                  {g.next_step && (
                    <p className="text-xs text-primary-700 mt-0.5">Next step: {g.next_step}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">
              {(job.skills ?? []).map((s) => s.label).join(", ") || "No specific skills listed."}
            </p>
          )}
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="job-paths">
          <h3 className="font-medium mb-2">Your path to this job</h3>
          {paths.length > 0 ? (
            <div className="space-y-3">
              {paths.slice(0, 2).map((path) => (
                <div key={path.id}>
                  <p className="text-sm font-medium">{path.title}</p>
                  <ol className="mt-1 space-y-1">
                    {path.steps.map((step, i) => (
                      <li key={i} className="text-xs text-slate-600 flex gap-2">
                        <span className="w-4 h-4 rounded-full bg-primary-100 text-primary-700 flex items-center justify-center shrink-0">
                          {i + 1}
                        </span>
                        <span>
                          {step.label || step.kind}
                          {step.optional && <span className="text-slate-400"> (optional)</span>}
                          {step.skill_label && (
                            <span className="text-slate-400"> · {step.skill_label}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ) : pathNodes.length > 0 ? (
            <div>
              <p className="text-xs text-slate-500 mb-2">Jobs that commonly lead here:</p>
              <div className="flex flex-wrap gap-2">
                {pathNodes.map((n) => (
                  <Link
                    key={n.code}
                    to={`/jobs/${n.code}`}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1 hover:border-primary-400"
                  >
                    {n.title}
                  </Link>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState compact title="No path mapped yet" description="Curated routes to this job will appear here." />
          )}
        </div>
      </section>

      <section className="grid md:grid-cols-3 gap-4">
        <InfoBlock title="Education">
          <p>{EDUCATION_LABEL[attrs?.education?.level ?? ""] ?? attrs?.education?.level}</p>
          {attrs?.education?.fields.length > 0 && <p className="text-slate-500">{attrs.education.fields.join(", ")}</p>}
          {(job.links ?? []).length > 0 && (
            <div className="pt-2 space-y-1" data-testid="job-links">
              {(job.links ?? []).map((link, i) => (
                <a
                  key={i}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 text-primary-700 hover:underline text-sm"
                >
                  <ExternalLink className="w-3.5 h-3.5 shrink-0" />
                  {LINK_KIND_LABEL[link.kind]}: {link.label}
                </a>
              ))}
            </div>
          )}
        </InfoBlock>
        <InfoBlock title="Market snapshot">
          {snapshot && snapshot.sample_size > 0 ? (
            <div className="text-sm space-y-0.5" data-testid="market-snapshot">
              <p>
                {snapshot.sample_size} live posting{snapshot.sample_size !== 1 ? "s" : ""}
                {snapshot.months.length > 0 && (
                  <span className="text-slate-400"> · last 30d: {snapshot.months[snapshot.months.length - 1].postings}</span>
                )}
              </p>
              {snapshot.salary_band ? (
                <p>
                  p25–p75: {snapshot.salary_band.p25?.toLocaleString()}–
                  {snapshot.salary_band.p75?.toLocaleString()}
                </p>
              ) : (
                <p className="text-slate-400">salary band hidden (thin sample: {snapshot.sample_size})</p>
              )}
              {snapshot.top_skills.length > 0 && (
                <p className="text-slate-500">
                  demanded: {snapshot.top_skills.slice(0, 4).map((s) => s.key).join(", ")}
                </p>
              )}
            </div>
          ) : (
            <p className="text-slate-400">No live postings data for this job yet.</p>
          )}
        </InfoBlock>
        <InfoBlock title="Salary (USD/year)">
          <RangeBar
            label="median"
            low={attrs?.salary?.median?.[0] ?? 0}
            high={attrs?.salary?.median?.[1] ?? 1}
            min={0}
            unit="USD"
            className="mb-2"
          />
          <RangeBar
            label="entry → senior"
            low={attrs?.salary?.entry?.[0] ?? 0}
            high={attrs?.salary?.senior?.[1] ?? attrs?.salary?.median?.[1] ?? 1}
            min={0}
            unit="USD"
          />
        </InfoBlock>
        <InfoBlock title="Physical & environment">
          <p>Activity: {(attrs?.physical?.activity ?? "").replace(/_/g, " ")}</p>
          <p>{(attrs?.environments ?? []).join(", ").replace(/_/g, " ")}</p>
        </InfoBlock>
      </section>

      <section className="grid md:grid-cols-2 gap-4">
        <InfoBlock title="Typical positives">
          <ul className="list-disc ml-4 space-y-1">
            {(attrs?.typical_positives ?? []).map((p, i) => (
              <li key={i} className="text-sm">{p.title}{p.detail && ` — ${p.detail}`}</li>
            ))}
          </ul>
        </InfoBlock>
        <InfoBlock title="Typical negatives">
          <ul className="list-disc ml-4 space-y-1">
            {(attrs?.typical_negatives ?? []).map((n, i) => (
              <li key={i} className="text-sm">{n.title}{n.detail && ` — ${n.detail}`}</li>
            ))}
          </ul>
        </InfoBlock>
      </section>

      <section className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium">Your rating</h3>
          <div className="flex gap-2">
            {(["interested", "considering", "dismissed"] as MatchStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => void saveRating(userScore, s)}
                className={`text-xs px-3 py-1.5 rounded-full border ${
                  status === s ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
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
          <span className="text-xs font-medium text-slate-400 uppercase">Your notes</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => void saveRating(userScore, status)}
            rows={2}
            placeholder="Why this job is (not) for you…"
            className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            data-testid="job-notes"
          />
        </label>
      </section>

      <section>
        <h3 className="font-medium mb-2">Related jobs</h3>
        {relations.length === 0 ? (
          <EmptyState compact title="No relations yet" description="AI-suggested relations will appear here." />
        ) : (
          <div className="flex flex-wrap gap-2">
            {relations.map((r) => {
              const other = r.from_code === job.code ? r.to_code : r.from_code;
              return (
                <Link
                  key={r.id}
                  to={`/jobs/${other}`}
                  className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 hover:border-primary-500"
                >
                  <span className="text-slate-400 text-xs block">{r.relation_type.replace(/_/g, " ")}</span>
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
            className="mt-3 text-sm bg-emerald-600 text-white rounded-lg px-3 py-1.5"
          >
            Publish to catalog
          </button>
        )}
      </section>

      {detail && detail.university_pathways.length > 0 && (
        <section>
          <h3 className="font-medium mb-2">University pathways</h3>
          <div className="space-y-3">
            {detail.university_pathways.map((p, i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <Link to={`/universities/${p.department.university.id}`} className="font-medium hover:text-primary-700">
                      {p.department.university.name}
                    </Link>
                    <p className="text-sm text-slate-500">
                      {p.department.name} · {p.department.degree} · {p.department.duration_years}y
                      {p.department.application_deadline && (
                        <span className="text-amber-700"> · applies by {p.department.application_deadline}</span>
                      )}
                    </p>
                  </div>
                  <span className="text-sm text-slate-400">relevance {p.relevance}/10</span>
                </div>
                {p.admissions.length > 0 && (
                  <Table
                    className="mt-3"
                    headers={["Year", "Baseline", "Units"]}
                    rows={p.admissions.map((a) => [String(a.year), String(a.baseline_score ?? "–"), a.units])}
                  />
                )}
                {p.required_subjects.length > 0 && (
                  <p className="text-sm text-slate-500 mt-2">Subjects: {p.required_subjects.join(", ")}</p>
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
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <h3 className="font-medium mb-2">{title}</h3>
      <div className="text-sm space-y-0.5 text-slate-700">{children}</div>
    </div>
  );
}
