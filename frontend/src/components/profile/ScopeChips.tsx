import { useTranslation } from "react-i18next";

import { SegmentedTabs } from "@/components/ui";
import {
  PROFILE_SCOPES,
  PROFILE_SCOPE_KEYS,
  isProfileScopeKey,
  scopesFor,
  type ProfileScopeKey,
} from "@/config/profileScopes";

export function ScopeChips({ sectionId }: { sectionId: string }) {
  const { t } = useTranslation();
  const scopes = scopesFor(sectionId);
  if (scopes.length === 0) {
    return null;
  }
  return (
    <div
      className="mt-1 flex flex-wrap items-center gap-1"
      data-testid={`scope-chips-${sectionId}`}
    >
      {scopes.map((key) => {
        const scope = PROFILE_SCOPES[key];
        const Icon = scope.icon;
        return (
          <span
            key={key}
            title={t(scope.hintKey)}
            data-testid={`scope-chip-${key}`}
            className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${scope.chipClass}`}
          >
            <Icon className="size-2.5" aria-hidden />
            {t(scope.labelKey)}
          </span>
        );
      })}
    </div>
  );
}

export function ScopeDots({ sectionId }: { sectionId: string }) {
  const { t } = useTranslation();
  const scopes = scopesFor(sectionId);
  if (scopes.length === 0) {
    return null;
  }
  const label = `${t("profileScopes.usedFor")}: ${scopes
    .map((key) => t(PROFILE_SCOPES[key].labelKey))
    .join(" · ")}`;
  return (
    <span
      className="flex items-center gap-0.5"
      data-testid={`scope-dots-${sectionId}`}
      title={label}
      aria-hidden
    >
      {scopes.map((key) => (
        <span
          key={key}
          aria-hidden
          className={`inline-block size-1.5 rounded-full ${PROFILE_SCOPES[key].dotClass}`}
        />
      ))}
    </span>
  );
}

export function ScopeFocusTabs({
  focus,
  onFocus,
}: {
  focus: ProfileScopeKey | null;
  onFocus: (scope: ProfileScopeKey | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="scope-focus">
      <span className="text-xs font-medium text-[var(--as-muted-fg)]">
        {t("profileScopes.filterLabel")}
      </span>
      <SegmentedTabs
        ariaLabel={t("profileScopes.filterAria")}
        className="max-w-xl"
        items={[
          { value: "all", label: t("profileScopes.all") },
          ...PROFILE_SCOPE_KEYS.map((key) => ({
            value: key,
            label: t(PROFILE_SCOPES[key].labelKey),
            icon: PROFILE_SCOPES[key].icon,
          })),
        ]}
        value={focus ?? "all"}
        onValueChange={(next) =>
          onFocus(next === "all" || !isProfileScopeKey(next) ? null : next)
        }
      />
    </div>
  );
}
