import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { BriefcaseBusiness } from "lucide-react";

import type { ApplicationFunnel } from "@/types/application";

/** Dashboard funnel (plan 116.4): saved → applied → interviewing →
 * offers, replacing the bare saved-posting count. */
export function ApplicationsFunnel({ funnel }: { funnel: ApplicationFunnel | null }) {
  const { t } = useTranslation();
  if (
    funnel === null ||
    funnel.saved + funnel.applied + funnel.interviewing + funnel.offers === 0
  ) {
    return null;
  }
  const rows = [
    ["saved", t("dashboard.funnelSaved"), "text-slate-900"],
    ["applied", t("dashboard.funnelApplied"), "text-slate-900"],
    ["interviewing", t("dashboard.funnelInterviewing"), "text-amber-600"],
    ["offers", t("dashboard.funnelOffers"), "text-emerald-600"],
  ] as const;
  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-4"
      data-testid="applications-widget"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BriefcaseBusiness className="w-4 h-4 text-primary-600" />
          <h2 className="font-semibold text-slate-900">
            {t("dashboard.applicationsTitle")}
          </h2>
        </div>
        <Link to="/applications" className="text-sm text-primary-700">
          {t("dashboard.openTracker")}
        </Link>
      </div>
      <div className="mt-3 flex flex-wrap gap-6 text-sm">
        {rows.map(([key, label, tone]) => (
          <Link
            key={key}
            to="/applications"
            className="text-left"
            data-testid={`funnel-${key}`}
          >
            <p className={`text-2xl font-bold ${tone}`}>{funnel[key]}</p>
            <p className="text-xs text-slate-500">{label}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}
