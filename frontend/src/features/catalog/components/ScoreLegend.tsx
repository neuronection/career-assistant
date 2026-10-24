import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";

/**
 * "How scores work" popover — shared by every score cluster (job page
 * card, Rankings). One place explains the match/fit/AI/you layers, the
 * 0.6/0.4 blend and the neutral-dimension rule.
 */
export function ScoreLegend({ align = "center" }: { align?: "start" | "center" | "end" }) {
  const { t } = useTranslation();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("scoreInfo.title")}
          data-testid="score-info"
          className="rounded text-slate-400 hover:text-slate-600 focus-visible:outline-2 focus-visible:outline-primary-600"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-72 text-sm" data-testid="score-info-panel">
        <p className="font-medium text-slate-900">{t("scoreInfo.title")}</p>
        <ul className="mt-2 space-y-2 text-slate-600">
          <li>
            <span className="font-medium text-slate-800">{t("scoreInfo.matchLabel")}</span>{" "}
            {t("scoreInfo.matchBody")}
          </li>
          <li>
            <span className="font-medium text-slate-800">{t("scoreInfo.fitLabel")}</span>{" "}
            {t("scoreInfo.fitBody")}
          </li>
          <li>
            <span className="font-medium text-slate-800">{t("scoreInfo.aiLabel")}</span>{" "}
            {t("scoreInfo.aiBody")}
          </li>
          <li>
            <span className="font-medium text-slate-800">{t("scoreInfo.youLabel")}</span>{" "}
            {t("scoreInfo.youBody")}
          </li>
        </ul>
        <p className="mt-2 text-xs text-slate-400">{t("scoreInfo.neutralNote")}</p>
      </PopoverContent>
    </Popover>
  );
}
