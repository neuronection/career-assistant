import { useTranslation } from "react-i18next";
import { useBootstrapStore } from "@/stores/bootstrapStore";

export function FitStaleBadge() {
  const { t } = useTranslation();
  const fitStale = useBootstrapStore((s) => s.bootstrap?.fit_stale);
  if (!fitStale) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700"
      data-testid="fit-stale-badge"
      title={t("shared.fitsUpdatingTitle")}
    >
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
      {t("shared.fitsUpdating")}
    </span>
  );
}
