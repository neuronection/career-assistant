import { useTranslation } from "react-i18next";
import { ShieldAlert } from "lucide-react";

import type { PostingDetailOut } from "@/types/wire";

export function SafetyFlagsCard({
  flags,
}: {
  flags: PostingDetailOut["safety_flags"];
}) {
  const { t } = useTranslation();
  if (!flags || flags.length === 0) return null;
  return (
    <section
      className="rounded-[var(--as-radius-lg)] border border-[color-mix(in_srgb,var(--as-warning)_25%,transparent)] bg-[var(--as-surface)] p-4"
      data-testid="posting-safety"
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
        <ShieldAlert className="size-4 text-[var(--as-warning)]" aria-hidden />
        {t("postingSafety.title")}
      </h2>
      <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
        {t("postingSafety.intro")}
      </p>
      <ul className="mt-2 space-y-2">
        {flags.map((flag) => (
          <li
            key={flag.key}
            className="rounded border border-[var(--as-border)] p-2"
            data-testid={`posting-safety-${flag.key}`}
          >
            <p className="text-xs font-medium text-[var(--as-fg)]">
              {t(`postingSafety.flag.${flag.key}`, { defaultValue: flag.label })}
            </p>
            {flag.evidence ? (
              <blockquote className="mt-1 border-l-2 border-[var(--as-border)] pl-2 text-xs italic text-[var(--as-muted-fg)]">
                “{flag.evidence}”
              </blockquote>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-[var(--as-muted-fg)]">
        {t("postingSafety.caveat")}
      </p>
    </section>
  );
}
