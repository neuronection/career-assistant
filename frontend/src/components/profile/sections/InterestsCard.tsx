import { forwardRef, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { useProfileStore } from "@/stores/profileStore";
import type { Profile, TaxonomyTag } from "@/types";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface InterestsCardProps
  extends SectionCardBaseProps<Profile["interests"]> {}

function groupByCategory(tags: TaxonomyTag[]) {
  const groups = new Map<string, TaxonomyTag[]>();
  for (const tag of tags) {
    const list = groups.get(tag.category) ?? [];
    list.push(tag);
    groups.set(tag.category, list);
  }
  return [...groups.entries()];
}

export const InterestsCard = forwardRef<SectionCardHandle, InterestsCardProps>(
  function InterestsCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const interests = useProfileStore((s) => s.interests);
    const loadTaxonomy = useProfileStore((s) => s.loadTaxonomy);
    const [query, setQuery] = useState("");
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({ interests: d }),
    });

    useEffect(() => {
      void loadTaxonomy();
    }, [loadTaxonomy]);

    const filtered = useMemo(
      () =>
        interests.filter(
          (t) =>
            !query ||
            t.label.toLowerCase().includes(query.toLowerCase()) ||
            t.key.includes(query.toLowerCase())
        ),
      [interests, query]
    );
    const grouped = useMemo(
      () => groupByCategory(filtered),
      [filtered]
    );

    const toggle = (tag: TaxonomyTag) => {
      const found = draft.find((i) => i.tag_key === tag.key);
      const next = found
        ? draft.filter((i) => i.tag_key !== tag.key)
        : [...draft, { tag_key: tag.key, weight: 3, source: "self" }];
      setDraft(next);
    };

    return (
      <ProfileSectionCard
        name="interests"
        title={t("onboarding.step.interests")}
        description={
          variant === "page"
            ? t("profileSection.interestsBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="flex min-h-0 flex-col gap-3">
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--as-muted-fg)]"
              aria-hidden
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("profileSection.searchInterests")}
              aria-label={t("profileSection.searchInterests")}
              className="h-9 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] pl-8 pr-3 text-sm text-[var(--as-fg)] outline-none transition-colors placeholder:text-[var(--as-muted-fg)] focus-visible:border-[var(--as-accent)]"
              data-testid="interests-search"
            />
          </div>
          <div
            className={`grid content-start gap-1.5 sm:gap-2 sm:grid-cols-2 md:grid-cols-3 ${
              variant === "onboarding"
                ? "min-h-0 flex-1 overflow-y-auto pr-1"
                : ""
            }`}
          >
            {grouped.map(([category, tags]) => (
              <div
                key={category}
                className="contents"
                data-testid={`interest-group-${category}`}
              >
                <p className="col-span-full mt-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)] first:mt-0">
                  {category}
                </p>
                {tags.map((tag) => {
                  const active = draft.some((i) => i.tag_key === tag.key);
                  return (
                    <button
                      key={tag.key}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggle(tag)}
                      title={tag.description}
                      className={`cursor-pointer rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors duration-150 sm:text-sm ${
                        active
                          ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] font-medium text-[var(--as-accent)]"
                          : "border-[var(--as-border)] text-[var(--as-fg)] hover:border-[var(--as-accent)]"
                      }`}
                      data-testid={`interest-chip-${tag.key}`}
                    >
                      {tag.label}
                    </button>
                  );
                })}
              </div>
            ))}
            {filtered.length === 0 && (
              <p className="col-span-full py-4 text-center text-xs text-[var(--as-muted-fg)]">
                No interests match “{query}”.
              </p>
            )}
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="interests-count">
            {draft.length} selected
          </p>
        </div>
      </ProfileSectionCard>
    );
  }
);
