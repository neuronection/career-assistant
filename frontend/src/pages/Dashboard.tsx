import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Building2,
  Bookmark,
  BriefcaseBusiness,
  Sparkles,
  Target,
  Trophy,
  X,
} from "lucide-react";
import { useProfileStore } from "@/stores/profileStore";
import { useCatalogStore } from "@/stores/catalogStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { fetchRankings, fetchCandidates } from "@/api/matching";
import { fetchFeed, markSeen } from "@/api/engagement";
import { fetchPostings } from "@/api/postings";
import {
  dismissNudge,
  fetchTargetDashboard,
} from "@/api/onboarding";
import { JobCard } from "@/components/JobCard";
import { ScoreRing } from "@/components/ScoreRing";
import type {
  Candidate,
  FeedResponse,
  JobPostingItem,
  PostingsResponse,
  RankedJob,
  TargetDashboard,
} from "@/types";
import { useState } from "react";

const STAGE_TAGLINE: Record<string, string> = {
  student: "Explore, score and compare — most people know fewer than 30 job titles.",
  early_career:
    "Your first roles set the trajectory — see where your skills already carry you.",
  experienced:
    "Your experience is the signal — find the roles that actually match it.",
  switching:
    "What transfers matters more than what's familiar — start from your strengths.",
  returning:
    "Re-entry is a path, not a restart — pick up from the evidence you already have.",
};

export function Dashboard() {
  const { profile, load } = useProfileStore();
  const { loadFamilies, families } = useCatalogStore();
  const { bootstrap } = useBootstrapStore();
  const [top, setTop] = useState<RankedJob[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [feedView, setFeedView] = useState<"all" | "saved">("all");
  const [applications, setApplications] = useState<PostingsResponse | null>(null);
  const [target, setTarget] = useState<TargetDashboard | null>(null);
  const [targetJobs, setTargetJobs] = useState<JobPostingItem[]>([]);
  const navigate = useNavigate();

  const loadFeed = (view: "all" | "saved") => {
    void fetchFeed({ view, page_size: 6 })
      .then(setFeed)
      .catch(() => setFeed(null));
  };

  useEffect(() => {
    void load();
    void loadFamilies();
    if (!bootstrap) void useBootstrapStore.getState().load();
    void fetchRankings({ page_size: 4 }).then((r) => setTop(r.items)).catch(() => setTop([]));
    void fetchCandidates({ limit: 4 }).then(setCandidates).catch(() => setCandidates([]));
    loadFeed("all");
    void fetchPostings({ saved: true })
      .then(setApplications)
      .catch(() => setApplications(null));
    void fetchTargetDashboard()
      .then((t) => {
        setTarget(t);
        if (t.families.length > 0) {
          void fetchPostings({ sort: "fit" })
            .then((r) => setTargetJobs(r.items.slice(0, 4)))
            .catch(() => setTargetJobs([]));
        }
      })
      .catch(() => setTarget(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, loadFamilies]);

  const openFeedJob = (jobId: string, code: string) => {
    void markSeen([jobId]).catch(() => undefined);
    navigate(`/jobs/${code}`);
  };

  const completeness = profile?.completeness;
  const jobCount = countJobs(families);

  return (
    <div className="space-y-8" data-testid="dashboard">
      <section>
        <h1 className="text-2xl font-bold text-slate-900">Discover the work you&rsquo;ll love</h1>
        <p className="text-slate-500 mt-1" data-testid="dashboard-tagline">
          {bootstrap
            ? STAGE_TAGLINE[bootstrap.career_stage] ?? STAGE_TAGLINE.student
            : `${jobCount}+ jobs in the catalog. Most people know fewer than 30 job titles — explore, score and compare.`}
        </p>
      </section>

      {completeness && completeness.percent < 100 && (
        <section className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="font-medium text-amber-900">Profile is {completeness.percent}% complete</p>
            <p className="text-sm text-amber-700">The better your profile, the sharper your matches.</p>
          </div>
          <Link
            to="/onboarding"
            className="text-sm bg-amber-600 hover:bg-amber-700 text-white rounded-lg px-4 py-2 flex items-center gap-1"
          >
            Continue <ArrowRight className="w-4 h-4" />
          </Link>
        </section>
      )}

      <section className="grid md:grid-cols-3 gap-4">
        <QuickLink to="/generate" icon={Sparkles} title="Generate jobs with AI" text="Describe any idea or curiosity and get structured career options." />
        <QuickLink to="/rankings" icon={Trophy} title="See your rankings" text="AI score + your score + demand, fully filterable." />
        {(!bootstrap || bootstrap.features.universities) && (
          <QuickLink to="/universities" icon={Building2} title="Add your universities" text="Upload admissions PDFs to connect study paths with jobs." />
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-slate-900">Your top matches</h2>
          <Link to="/rankings" className="text-sm text-primary-700">See all →</Link>
        </div>
        {top.length === 0 ? (
          <div className="bg-white border border-dashed border-slate-300 rounded-xl p-6 text-center text-sm text-slate-500">
            <p>No AI scores yet. Score candidates to unlock your rankings.</p>
            <Link to="/rankings" className="text-primary-700 font-medium">Score my first jobs →</Link>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {top.map((r) => (
              <Link key={r.job.id} to={`/jobs/${r.job.code}`} className="flex items-center gap-4 bg-white border border-slate-200 rounded-xl p-4">
                <ScoreRing score={r.score} />
                <div className="flex-1">
                  <p className="font-medium text-slate-900">{r.job.title}</p>
                  <p className="text-sm text-slate-500">{r.job.family_key.replace(/-/g, " ")}</p>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section data-testid="feed-section">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-slate-900 flex items-center gap-2">
            {feedView === "saved" ? "Saved jobs" : "New for you"}
            {feedView === "all" && feed && feed.unseen > 0 && (
              <span
                className="text-xs bg-primary-600 text-white rounded-full px-2 py-0.5"
                data-testid="feed-unseen-badge"
              >
                {feed.unseen} new
              </span>
            )}
          </h2>
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setFeedView("saved");
                loadFeed("saved");
              }}
              className={`text-sm flex items-center gap-1 ${feedView === "saved" ? "text-primary-700 font-medium" : "text-slate-500"}`}
              data-testid="feed-saved-toggle"
            >
              <Bookmark className="w-3.5 h-3.5" /> Saved
            </button>
            <button
              onClick={() => {
                setFeedView("all");
                loadFeed("all");
              }}
              className={`text-sm ${feedView === "all" ? "text-primary-700 font-medium" : "text-slate-500"}`}
            >
              Discover
            </button>
          </div>
        </div>
        {feed && feed.items.length > 0 ? (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {feed.items.map((item) => (
              <JobCard
                key={item.job.id}
                job={item.job}
                seen={item.seen}
                saved={item.saved}
                notes={item.user_notes || undefined}
                exploration={item.exploration}
                onSelect={(j) => openFeedJob(j.id, j.code)}
              />
            ))}
          </div>
        ) : (
          <div className="bg-white border border-dashed border-slate-300 rounded-xl p-6 text-center text-sm text-slate-500">
            {feedView === "saved" ? (
              <p>Nothing saved yet — bookmark jobs to compare them later.</p>
            ) : (
              <p>Your feed is all caught up. Nice.</p>
            )}
          </div>
        )}
      </section>

      {target && target.families.length > 0 && (
        <section className="bg-primary-50 border border-primary-100 rounded-xl p-4" data-testid="target-mode">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-slate-900 flex items-center gap-2">
              <Target className="w-4 h-4 text-primary-600" /> Target mode
              <span className="text-xs font-normal text-slate-500">
                {target.families.map((f) => f.replace(/-/g, " ")).join(" · ")}
              </span>
            </h2>
            <Link to="/postings" className="text-sm text-primary-700">Live tab →</Link>
          </div>

          {target.nudges.length > 0 && (
            <div className="mt-3 bg-white border border-slate-200 rounded-lg p-3 flex items-center justify-between gap-2" data-testid="nudge-banner">
              <p className="text-sm text-slate-600">{target.nudges[0].message}</p>
              <div className="flex items-center gap-2 shrink-0">
                <Link to="/assessment" className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1.5">
                  5-min micro-run
                </Link>
                <button
                  aria-label="Dismiss nudge"
                  onClick={() => {
                    void dismissNudge(target.nudges[0].type);
                    setTarget({ ...target, nudges: target.nudges.slice(1) });
                  }}
                  className="p-1 text-slate-400 hover:text-slate-600"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {targetJobs.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-slate-400 uppercase mb-2">Open jobs for your targets</p>
              <div className="grid md:grid-cols-2 gap-2">
                {targetJobs.map((p) => (
                  <a
                    key={p.id}
                    href={p.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => void markSeen([p.id]).catch(() => undefined)}
                    className="bg-white border border-slate-200 rounded-lg p-3 text-sm hover:border-primary-400"
                  >
                    <span className="font-medium text-slate-900">{p.title}</span>
                    <span className="text-slate-400"> · {p.org}</span>
                    <span className="block text-xs text-slate-400 mt-0.5">
                      {p.source_key}
                      {p.fit != null && p.fit > 0 ? ` · fit ${p.fit.toFixed(1)}` : ""}
                    </span>
                  </a>
                ))}
              </div>
            </div>
          )}

          <div className="grid md:grid-cols-3 gap-3 mt-3">
            <div className="bg-white border border-slate-200 rounded-lg p-3">
              <p className="text-xs text-slate-400 uppercase">Open postings</p>
              <p className="text-xl font-bold text-slate-900">
                {target.open_postings.total}
                {target.open_postings.unseen > 0 && (
                  <span className="text-xs text-primary-600 ml-2">{target.open_postings.unseen} new</span>
                )}
              </p>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-3">
              <p className="text-xs text-slate-400 uppercase">Salary band</p>
              <p className="text-sm font-medium text-slate-900">
                {target.open_postings.salary_band.min != null
                  ? `${target.open_postings.salary_band.min.toLocaleString()}–${(target.open_postings.salary_band.max ?? 0).toLocaleString()}`
                  : "—"}
              </p>
            </div>
            <div className="bg-white border border-slate-200 rounded-lg p-3">
              <p className="text-xs text-slate-400 uppercase">Top employers</p>
              <p className="text-sm text-slate-700 truncate">
                {target.open_postings.top_employers.map((e) => e.org).join(", ") || "—"}
              </p>
            </div>
          </div>

          {target.adjacent_targets.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-slate-400 uppercase mb-1">Expand your career</p>
              <div className="flex flex-wrap gap-1.5">
                {target.adjacent_targets.map((adjacent) => (
                  <Link
                    key={adjacent.family_key}
                    to={`/catalog?family=${adjacent.family_key}`}
                    className="text-xs bg-white border border-slate-200 rounded-full px-3 py-1 hover:border-primary-400"
                  >
                    {adjacent.label} · {adjacent.sample}
                  </Link>
                ))}
              </div>
            </div>
          )}

          <div className="mt-3 flex items-center gap-3">
            <div className="flex-1 h-2 bg-white rounded-full overflow-hidden border border-slate-200">
              <div
                className="h-2 bg-primary-500 rounded-full"
                style={{ width: `${target.completeness.percent}%` }}
              />
            </div>
            <span className="text-xs text-slate-500">
              profile {target.completeness.percent}%
            </span>
          </div>
          {target.completeness.segments
            .filter((segment) => !segment.filled)
            .slice(0, 1)
            .map((segment) => (
              <p key={segment.key} className="text-xs text-slate-500 mt-1">
                <Link to={segment.href} className="text-primary-700">{segment.hint} →</Link>
              </p>
            ))}
        </section>
      )}

      {applications && applications.total > 0 && (
        <section className="bg-white border border-slate-200 rounded-xl p-4" data-testid="applications-widget">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BriefcaseBusiness className="w-4 h-4 text-primary-600" />
              <h2 className="font-semibold text-slate-900">Your applications</h2>
            </div>
            <Link to="/postings" className="text-sm text-primary-700">Live tab →</Link>
          </div>
          <div className="flex gap-6 mt-3 text-sm">
            <div>
              <p className="text-2xl font-bold text-slate-900">{applications.total}</p>
              <p className="text-xs text-slate-500">saved postings</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-emerald-600">
                {applications.items.filter((p) => p.applied_at).length}
              </p>
              <p className="text-xs text-slate-500">applied</p>
            </div>
          </div>
        </section>
      )}

      {candidates.length > 0 && (
        <section>
          <h2 className="font-semibold text-slate-900 mb-3">Suggested to score next</h2>
          <div className="grid md:grid-cols-2 gap-3">
            {candidates.map((c) => (
              <JobCard key={c.job.id} job={c.job} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function QuickLink({ to, icon: Icon, title, text }: { to: string; icon: typeof Sparkles; title: string; text: string }) {
  return (
    <Link to={to} className="bg-white border border-slate-200 rounded-xl p-4 hover:border-primary-500">
      <Icon className="w-5 h-5 text-primary-600" />
      <p className="font-medium mt-2">{title}</p>
      <p className="text-sm text-slate-500 mt-1">{text}</p>
    </Link>
  );
}

function countJobs(families: { job_count: number; children: { job_count: number }[] }[]): number {
  return families.reduce((sum, f) => sum + f.job_count + f.children.reduce((s, c) => s + c.job_count, 0), 0);
}
