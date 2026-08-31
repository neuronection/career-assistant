import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { fetchJobs, generateJobs, publishJob } from "@/api/jobs";
import { bulkJobAction, fetchModerationQueue } from "@/api/admin";
import type { BackgroundJob } from "@/api/backgroundJobs";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { useAuthStore } from "@/stores/authStore";
import { JobCard } from "@/components/JobCard";
import { apiDetail } from "@/api/client";
import type { Job } from "@/types";

export function Generate() {
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const [mode, setMode] = useState<"general" | "prompt">("general");
  const [prompt, setPrompt] = useState("");
  const [count, setCount] = useState(5);
  const [drafts, setDrafts] = useState<Job[]>([]);
  const [queue, setQueue] = useState<Job[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const onDone = async (finished: BackgroundJob) => {
    setBusy(false);
    if (finished.status === "succeeded") {
      const fresh = await fetchJobs({ status: "draft", source: "ai" });
      setDrafts(fresh);
      const noteText = finished.result?.note;
      setNote(typeof noteText === "string" ? noteText : "");
    } else if (finished.status === "failed") {
      setError(finished.error ?? "Generation failed");
    } else {
      setError("Generation cancelled");
    }
  };
  const { job, track } = useBackgroundJob(onDone);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const { job_id } = await generateJobs({
        mode,
        prompt: mode === "prompt" ? prompt : undefined,
        count,
      });
      track(job_id);
    } catch (err) {
      setError(apiDetail(err));
      setBusy(false);
    }
  };

  const loadQueue = async () => {
    if (!isAdmin) return;
    try {
      setQueue(await fetchModerationQueue("draft"));
    } catch {
      setQueue([]);
    }
  };

  useEffect(() => {
    void loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const bulk = async (action: "publish" | "reject") => {
    setError("");
    try {
      await bulkJobAction(queue.map((q) => q.id), action);
      await loadQueue();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto" data-testid="generate">
      <h1 className="text-2xl font-bold text-slate-900">Generate jobs with AI</h1>
      <p className="text-slate-500">Can&rsquo;t find it in the catalog? Invent it. The AI creates structured entries like the seeded ones.</p>

      <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-4">
        <div className="flex gap-2">
          {(["general", "prompt"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`text-sm px-4 py-2 rounded-lg border ${mode === m ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"}`}
            >
              {m === "general" ? "Explore broadly (based on my profile)" : "From a prompt"}
            </button>
          ))}
        </div>
        {mode === "prompt" && (
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="e.g. jobs that mix biology and scuba diving, or careers around renewable energy in coastal towns"
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
        )}
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-500">How many?</label>
          <input
            type="number"
            min={1}
            max={15}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className="w-20 border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={() => void run()}
            disabled={busy || (mode === "prompt" && !prompt.trim())}
            className="ml-auto bg-primary-600 hover:bg-primary-700 text-white rounded-lg px-4 py-2 text-sm font-medium flex items-center gap-1 disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" /> {busy ? "Generating…" : "Generate"}
          </button>
        </div>
        {busy && job && (
          <div className="space-y-1">
            <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-500 transition-all duration-500"
                style={{ width: `${job.progress}%` }}
                data-testid="job-progress"
              />
            </div>
            <p className="text-xs text-slate-400">{job.stage ?? "queued…"}</p>
          </div>
        )}
        {error && <p className="text-sm text-rose-600">{error}</p>}
      </div>

      {isAdmin && queue.length > 0 && (
        <section className="space-y-3" data-testid="review-queue">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">
              Review queue — {queue.length} draft{queue.length === 1 ? "" : "s"} from
              everyone
            </h2>
            <div className="flex gap-2">
              <button
                onClick={() => void bulk("publish")}
                className="text-sm bg-emerald-600 text-white rounded-lg px-4 py-2"
              >
                Publish all
              </button>
              <button
                onClick={() => void bulk("reject")}
                className="text-sm border border-rose-300 text-rose-600 rounded-lg px-4 py-2"
              >
                Reject all
              </button>
            </div>
          </div>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {queue.map((d) => (
              <div key={d.id} className="space-y-1">
                <JobCard job={d} />
                <Link to={`/jobs/${d.code}`} className="text-xs text-primary-700">
                  Review details →
                </Link>
              </div>
            ))}
          </div>
        </section>
      )}

      {drafts.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">{drafts.length} drafts created</h2>
            <button
              onClick={async () => {
                await Promise.all(drafts.filter((d) => d.status === "draft").map((d) => publishJob(d.code)));
                setDrafts(await Promise.all(drafts.map(async (d) => ({ ...d, status: "published" as const }))));
              }}
              className="text-sm bg-emerald-600 text-white rounded-lg px-4 py-2"
            >
              Publish all
            </button>
          </div>
          {note && <p className="text-xs text-slate-400">{note}</p>}
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {drafts.map((d) => (
              <div key={d.id} className="space-y-1">
                <JobCard job={d} />
                <Link to={`/jobs/${d.code}`} className="text-xs text-primary-700">Open details →</Link>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
