import { useTranslation } from "react-i18next";

import type { PostingDetailOut } from "@/types/wire";

const GATE_LABEL_KEYS: Record<string, string> = {
  travel: "postingDetail.gate.travel",
  shift: "postingDetail.gate.shift",
  hours: "postingDetail.gate.hours",
  salary_min: "postingDetail.gate.salaryMin",
};

type Match = NonNullable<PostingDetailOut["match"]>;

export function MatchCard({ match }: { match: Match }) {
  const { t } = useTranslation();
  return (
    <section className="bg-white border border-slate-200 rounded-xl p-3" data-testid="match-card">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-slate-400 uppercase">
          {t("postingDetail.matchScore")}
        </h3>
        <span className="text-lg font-bold text-primary-700" data-testid="match-score">
          {match.score.toFixed(1)}
          <span className="text-xs text-slate-400 font-normal">/10</span>
        </span>
      </div>
      {match.estimate && (
        <p className="text-[11px] text-amber-600 mt-1" data-testid="match-estimate-note">
          {t("postingDetail.estimateNote")}
        </p>
      )}
      {match.gates && match.gates.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5" data-testid="posting-gates">
          {match.gates.map((gate) => (
            <span
              key={gate}
              className="rounded bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700"
              title={t("postingDetail.gateTitle")}
            >
              {GATE_LABEL_KEYS[gate] ? t(GATE_LABEL_KEYS[gate]) : gate}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 space-y-1.5">
        {Object.entries(match.breakdown ?? {}).map(([dim, entry]) => (
          <div key={dim} className="flex items-center gap-2 text-xs">
            <span className="w-28 shrink-0 text-slate-500">
              {t(`dimensions.${dim}`, { defaultValue: dim.replace(/_/g, " ") })}
            </span>
            <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${entry.neutral ? "bg-slate-300" : "bg-primary-500"}`}
                style={{ width: `${Math.min(100, entry.score * 10)}%` }}
              />
            </div>
            <span className="w-8 text-right text-slate-600">{entry.score.toFixed(1)}</span>
            <span className="w-10 text-right text-slate-300">×{entry.weight}</span>
          </div>
        ))}
        <div className="pt-1 space-y-0.5" data-testid="match-detail-lines">
          {Object.entries(match.breakdown ?? {})
            .filter(([, entry]) => entry.detail)
            .map(([dim, entry]) => (
              <p key={dim} className="text-[11px] text-slate-400">
                <span className="font-medium text-slate-500">
                  {t(`dimensions.${dim}`, { defaultValue: dim.replace(/_/g, " ") })}
                  {": "}
                </span>
                {entry.detail}
              </p>
            ))}
        </div>
      </div>
    </section>
  );
}
