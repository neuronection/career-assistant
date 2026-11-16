import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { GraduationCap } from "lucide-react";

import { Button } from "@/components/ui";
import { fetchDegreeRoles, type DegreeRoleMatch, type DegreeRoles } from "@/api/discipline";
import type { Filters } from "@/features/catalog/exploreParams";

type ApplyMode = "apply" | "clear";

function reasonText(
  match: DegreeRoleMatch,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  if (match.reason === "matched") {
    return t("degreeRoles.reason.matched", { terms: match.matched_terms.join(", ") });
  }
  if (match.reason === "parent") return t("degreeRoles.reason.parent");
  return t("degreeRoles.reason.family_expansion");
}

export function DegreeRolesBanner({
  filters,
  onApply,
}: {
  filters: Filters;
  onApply: (keys: string[], mode: ApplyMode) => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<DegreeRoles | null>(null);

  useEffect(() => {
    void fetchDegreeRoles()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (data === null || data.matches.length === 0) return null;
  const keys = data.matches.map((match) => match.family_key);
  const active = keys.length > 0 && keys.every((key) => filters.mappedFamily.includes(key));

  return (
    <section
      className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="degree-roles"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <GraduationCap className="size-4 text-[var(--as-accent)]" aria-hidden />
            {t("degreeRoles.title")}
          </h2>
          <p className="mt-1 text-xs text-[var(--as-muted-fg)]">{t("degreeRoles.note")}</p>
        </div>
        <Button
          size="sm"
          variant={active ? "ghost" : "outline"}
          onClick={() => onApply(keys, active ? "clear" : "apply")}
          data-testid="degree-roles-apply"
        >
          {active ? t("degreeRoles.clear") : t("degreeRoles.apply")}
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {data.matches.map((match) => (
          <span
            key={match.family_key}
            title={reasonText(match, t)}
            className="rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[10px] text-[var(--as-fg)]"
          >
            {match.family_title}
            {match.reason === "parent" ? ` · ${t("degreeRoles.parent")}` : ""}
            {match.reason === "family_expansion" ? ` · ${t("degreeRoles.related")}` : ""}
          </span>
        ))}
      </div>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[10px] text-[var(--as-muted-fg)]">
        {data.matches.slice(0, 2).map((match) => (
          <li key={`why-${match.family_key}`}>{reasonText(match, t)}</li>
        ))}
      </ul>
    </section>
  );
}
