import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BadgeCheck, CircleHelp } from "lucide-react";

import { fetchCompetencies, type Competencies } from "@/api/competencies";

export function CompetencyEvidenceCard() {
  const { t } = useTranslation();
  const [data, setData] = useState<Competencies | null>(null);

  useEffect(() => {
    void fetchCompetencies()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (data === null) return null;

  return (
    <section
      className="bg-white border border-slate-200 rounded-xl p-4"
      data-testid="competency-evidence"
    >
      <h2 className="font-semibold text-slate-900 flex items-center gap-2">
        <BadgeCheck className="w-4 h-4 text-primary-600" aria-hidden />
        {t("growth.competencies.title")}
      </h2>
      <p className="text-xs text-slate-500 mt-1">{t("growth.competencies.subtitle")}</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {data.competencies.map((competency) => (
          <div
            key={competency.key}
            className="rounded-lg border border-slate-100 bg-slate-50 p-3"
            data-testid={`competency-${competency.key}`}
          >
            <p className="text-sm font-medium text-slate-800">
              {t(`growth.competencies.items.${competency.key}`)}
            </p>
            {competency.evidence.length === 0 ? (
              <p className="mt-1 flex items-start gap-1.5 text-xs text-slate-500">
                <CircleHelp className="mt-0.5 w-3 h-3 shrink-0" aria-hidden />
                {t("growth.competencies.noEvidence")}
              </p>
            ) : (
              <ul className="mt-1.5 space-y-1.5">
                {competency.evidence.map((evidence) => (
                  <li key={evidence.id} className="text-xs text-slate-600">
                    <span className="font-medium text-slate-800">{evidence.label}</span>
                    <span className="ml-1 text-[10px] uppercase tracking-wide text-slate-400">
                      {t(`growth.competencies.kinds.${evidence.kind}`)}
                    </span>
                    {evidence.quote && evidence.quote !== evidence.label && (
                      <span className="mt-0.5 block text-slate-500">
                        “{evidence.quote}”
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
