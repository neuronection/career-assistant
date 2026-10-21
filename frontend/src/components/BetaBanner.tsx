import { useTranslation } from "react-i18next";
import { FlaskConical } from "lucide-react";

import { featureFor } from "@/config/features";

/**
 * The beta affordance: rendered by the app shell for every route whose
 * registry state is `beta`, so the chip and the expectation line come
 * from one place and cannot drift per page.
 */
export function BetaBanner({ pathname }: { pathname: string }) {
  const { t } = useTranslation();
  const feature = featureFor(pathname);
  if (!feature || feature.state !== "beta") return null;
  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
      data-testid="beta-banner"
      data-feature={feature.key}
    >
      <span
        className="inline-flex items-center gap-1 rounded-full bg-amber-200 px-2 py-0.5 font-semibold uppercase tracking-wide"
        data-testid="beta-chip"
      >
        <FlaskConical className="size-3" aria-hidden />
        {t("featureState.betaChip")}
      </span>
      <span>{t("featureState.betaNote")}</span>
    </div>
  );
}
