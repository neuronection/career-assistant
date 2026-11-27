import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Library } from "lucide-react";

import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";

/** Inline "the catalog is not loaded" hint for catalog-fed surfaces. */
export function CatalogEmptyNotice() {
  const { t } = useTranslation();
  const catalogEmpty = useBootstrapStore(
    (state) => state.bootstrap?.catalog_empty ?? false
  );
  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);
  if (!catalogEmpty) return null;
  return (
    <div
      className="flex flex-wrap items-start gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-3 py-2 text-xs"
      data-testid="catalog-empty-notice"
    >
      <Library className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--as-muted-fg)]" />
      <span className="min-w-0 flex-1 text-[var(--as-fg)]">
        {isAdmin ? t("catalog.empty.adminNotice") : t("catalog.empty.memberBody")}
      </span>
      <Link to="/catalog" className="shrink-0 font-medium text-[var(--as-accent)]">
        {t("catalog.empty.openCatalog")}
      </Link>
    </div>
  );
}
