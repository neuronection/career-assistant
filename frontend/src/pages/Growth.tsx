import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarCheck, Check, Radar, Route } from "lucide-react";
import {
  fetchCheckinStatus,
  fetchGrowthPlans,
  fetchRadar,
  patchGrowthStep,
  skipCheckin,
} from "@/api/growth";
import { EmptyState } from "@/components/ui";
import type {
  CheckinStatus,
  GrowthPlanItem,
  RadarEntry,
} from "@/types";

export function Growth() {
  const [plans, setPlans] = useState<GrowthPlanItem[]>([]);
  const [radar, setRadar] = useState<RadarEntry[]>([]);
  const [checkin, setCheckin] = useState<CheckinStatus | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = () => {
    void fetchGrowthPlans().then(setPlans).catch(() => setPlans([]));
    void fetchRadar().then(setRadar).catch(() => setRadar([]));
    void fetchCheckinStatus().then(setCheckin).catch(() => setCheckin(null));
    setLoaded(true);
  };

  useEffect(load, []);

  const completeStep = (stepId: string, level: number) => {
    void patchGrowthStep(stepId, { status: "done", completed_level: level }).then(load);
  };

  const skipStep = (stepId: string) => {
    void patchGrowthStep(stepId, { status: "skipped" }).then(load);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto" data-testid="growth">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Route className="w-6 h-6 text-primary-600" /> Growth
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Where next, what&apos;s missing, how&apos;s your market — private by design.
        </p>
      </div>

      {checkin?.due && (
        <div
          className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between"
          data-testid="checkin-banner"
        >
          <div className="flex items-center gap-2">
            <CalendarCheck className="w-4 h-4 text-amber-600" />
            <p className="text-sm text-amber-900">
              Quarterly check-in: confirm your stage, refresh a few skill
              levels, review your roadmap.
            </p>
          </div>
          <button
            onClick={() => void skipCheckin().then(load)}
            className="text-xs text-amber-700 border border-amber-300 rounded-lg px-3 py-1.5"
          >
            Remind me in 3 months
          </button>
        </div>
      )}

      <section>
        <h2 className="font-semibold text-slate-900 mb-3">Your roadmaps</h2>
        {loaded && plans.length === 0 ? (
          <EmptyState
            title="No roadmap yet"
            description="Open a job you're aiming for and create a growth plan — gaps become steps."
          />
        ) : (
          <div className="space-y-4">
            {plans.map((plan) => (
              <div key={plan.id} className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="font-medium text-slate-900">
                    → {plan.target_job.title}
                  </p>
                  <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                    {plan.status}
                  </span>
                </div>
                <ol className="space-y-1.5">
                  {plan.steps.map((step) => (
                    <li
                      key={step.id}
                      className="flex items-center justify-between gap-2 text-sm"
                      data-testid="growth-step"
                    >
                      <span className={step.status === "done" ? "text-slate-400 line-through" : ""}>
                        {step.position + 1}. {step.label}
                        {step.status !== "todo" && (
                          <span className="text-xs text-slate-400 ml-1">({step.status})</span>
                        )}
                      </span>
                      {step.status !== "done" && step.status !== "skipped" && (
                        <span className="flex gap-1 shrink-0">
                          <button
                            onClick={() => completeStep(step.id, step.target_level ?? 6)}
                            className="text-xs bg-primary-600 text-white rounded-lg px-2.5 py-1 flex items-center gap-1"
                            data-testid={`step-done-${step.id}`}
                            title="Mark done at the target level"
                          >
                            <Check className="w-3 h-3" /> done
                          </button>
                          <button
                            onClick={() => skipStep(step.id)}
                            className="text-xs border border-slate-200 rounded-lg px-2.5 py-1"
                          >
                            skip
                          </button>
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
                {plan.steps.some((s) => s.resources.length > 0) && (
                  <p className="text-xs text-slate-400 mt-2">
                    Close gaps with:{" "}
                    {plan.steps
                      .flatMap((s) => s.resources)
                      .slice(0, 3)
                      .map((r) => r.title)
                      .join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="font-semibold text-slate-900 mb-3 flex items-center gap-2">
          <Radar className="w-4 h-4 text-primary-600" /> Near-miss radar
        </h2>
        <p className="text-xs text-slate-400 mb-3">
          You&apos;re closer than you think — adjacent roles a few skills away.
        </p>
        {radar.length === 0 ? (
          <p className="text-sm text-slate-400">
            Nothing in range yet — rate a few skills and your radar fills in.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {radar.map((entry) => (
              <Link
                key={entry.job_id}
                to={`/jobs/${entry.code}`}
                className="bg-white border border-slate-200 rounded-xl p-4 hover:border-primary-400"
                data-testid="radar-card"
              >
                <p className="text-xs text-slate-400">
                  fit {entry.fit_score.toFixed(1)} · {entry.family_key.replace(/-/g, " ")}
                </p>
                <p className="font-medium text-slate-900 mt-0.5">{entry.headline}</p>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
