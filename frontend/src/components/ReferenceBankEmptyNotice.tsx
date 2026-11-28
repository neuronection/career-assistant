import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Library } from "lucide-react";

import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";

export type ReferenceBank = "assessment" | "cv_templates" | "metrics" | "skill_packs";

/** Inline "this reference bank is not loaded" hint for bank-fed surfaces. */
export function ReferenceBankEmptyNotice({ bank }: { bank: ReferenceBank }) {
  const { t } = useTranslation();
  const empty = useBootstrapStore(
    (state) => state.bootstrap?.reference_banks?.[bank] ?? false
  );
  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);
  if (!empty) return null;
  const label = t(`referenceBanks.label.${bank}`);
  return (
    <div
      className="flex flex-wrap items-start gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-3 py-2 text-xs"
      data-testid={`reference-bank-empty-${bank}`}
    >
      <Library className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--as-muted-fg)]" />
      <span className="min-w-0 flex-1 text-[var(--as-fg)]">
        {isAdmin
          ? t("referenceBanks.adminNotice", { bank: label })
          : t("referenceBanks.memberBody", { bank: label })}
      </span>
      {isAdmin && (
        <Link to="/settings/tools?section=sources" className="shrink-0 font-medium text-[var(--as-accent)]">
          {t("referenceBanks.openProviders")}
        </Link>
      )}
    </div>
  );
}
