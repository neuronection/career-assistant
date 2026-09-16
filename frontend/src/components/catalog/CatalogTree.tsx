import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LayoutGrid } from "lucide-react";
import { SettingsShell, type SettingsNavItem } from "@neuronection/assistant-ui";
import { useCatalogStore } from "@/stores/catalogStore";
import { JobCard } from "@/components/JobCard";
import { RecentSearches } from "@/components/RecentSearches";
import { useSearchHistory } from "@/hooks/useSearchHistory";
import type { JobFamilyNode, SearchRecord } from "@/types";

export function CatalogTree() {
  const { t } = useTranslation();
  const { families, jobs, loadFamilies, loadJobs } = useCatalogStore();
  const [searchParams] = useSearchParams();
  const familyParam = searchParams.get("family");
  const [openFamily, setOpenFamily] = useState<string | null>(familyParam);
  const [query, setQuery] = useState("");
  const [historyKey, setHistoryKey] = useState(0);
  const recordSearch = useSearchHistory("catalog");
  const recordRef = useRef(recordSearch);
  recordRef.current = recordSearch;
  const navigate = useNavigate();

  useEffect(() => {
    void loadFamilies();
    void loadJobs(familyParam ? { family_key: familyParam } : {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadFamilies, loadJobs]);

  const filteredJobs = useMemo(
    () => jobs.filter((j) => !query || j.title.toLowerCase().includes(query.toLowerCase())),
    [jobs, query]
  );

  useEffect(() => {
    if (query.trim().length < 2 && !openFamily) return;
    recordRef.current(
      query,
      { family_key: openFamily ?? null },
      filteredJobs.length
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, openFamily, filteredJobs.length]);

  const applySearch = (record: SearchRecord) => {
    const familyKey = (record.filters.family_key as string) || null;
    setQuery(record.query);
    setOpenFamily(familyKey);
    void loadJobs(familyKey ? { family_key: familyKey } : {});
    setHistoryKey((k) => k + 1);
  };

  const selectFamily = (key: string | null) => {
    setOpenFamily(key);
    void loadJobs(key ? { family_key: key } : {});
  };

  const nav: SettingsNavItem[] = useMemo(
    () =>
      families.map((f) => ({
        id: f.key,
        label: f.label,
        trailing: (
          <span
            className="text-xs tabular-nums text-[var(--as-muted-fg)]"
            data-testid={`family-count-${f.key}`}
          >
            {f.job_count}
          </span>
        ),
      })),
    [families]
  );
  const activeTopLevel = useMemo(
    () => topLevelAncestorKey(families, openFamily),
    [families, openFamily]
  );
  const activeNode = useMemo(() => findNode(families, openFamily), [families, openFamily]);

  return (
    <SettingsShell
      nav={nav}
      active={activeTopLevel ?? ""}
      onNavigate={(key) => selectFamily(key)}
      header={{ icon: LayoutGrid, title: t("catalog.families") }}
      navTestId="catalog-families"
    >
      <div className="space-y-4" data-testid="catalog-tree">
        <input
          placeholder={t("catalog.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t("catalog.searchPlaceholder")}
          className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] outline-none transition-colors focus:border-[var(--as-primary)]"
        />
        <RecentSearches scope="catalog" onApply={applySearch} refreshKey={historyKey} />
        {activeNode && activeNode.children.length > 0 && (
          <div className="flex flex-wrap gap-2" data-testid="catalog-subfamilies">
            {activeNode.children.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => selectFamily(c.key)}
                data-testid={`subfamily-${c.key}`}
                className="flex cursor-pointer items-center gap-1.5 rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-1.5 text-xs font-medium text-[var(--as-fg)] transition-colors hover:bg-[var(--as-muted)]"
              >
                {c.label}
                <span className="tabular-nums text-[var(--as-muted-fg)]">{c.job_count}</span>
              </button>
            ))}
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filteredJobs.map((job) => (
            <JobCard key={job.id} job={job} onSelect={(j) => navigate(`/jobs/${j.code}`)} />
          ))}
        </div>
      </div>
    </SettingsShell>
  );
}

function findNode(
  families: JobFamilyNode[],
  key: string | null
): JobFamilyNode | null {
  if (!key) return null;
  for (const family of families) {
    if (family.key === key) return family;
    const hit = findNode(family.children, key);
    if (hit) return hit;
  }
  return null;
}

function topLevelAncestorKey(
  families: JobFamilyNode[],
  key: string | null
): string | null {
  if (!key) return null;
  for (const family of families) {
    if (family.key === key || familyHasDescendant(family, key)) return family.key;
  }
  return null;
}

function familyHasDescendant(family: JobFamilyNode, key: string): boolean {
  return family.children.some(
    (c) => c.key === key || familyHasDescendant(c, key)
  );
}
