import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
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

  return (
    <div className="grid lg:grid-cols-[320px_1fr] gap-6">
      <aside className="bg-white border border-slate-200 rounded-xl p-3 space-y-1 max-h-[70vh] overflow-y-auto">
        {families.map((f) => (
          <FamilyNode
            key={f.key}
            family={f}
            openKey={openFamily}
            onToggle={(key) => {
              setOpenFamily(key === openFamily ? null : key);
              void loadJobs({ family_key: key });
            }}
          />
        ))}
      </aside>
      <section>
        <input
          placeholder={t("catalog.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full mb-4 border border-slate-200 rounded-lg px-3 py-2 text-sm"
        />
        <div className="mb-4">
          <RecentSearches scope="catalog" onApply={applySearch} refreshKey={historyKey} />
        </div>
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filteredJobs.map((job) => (
            <JobCard key={job.id} job={job} onSelect={(j) => navigate(`/jobs/${j.code}`)} />
          ))}
        </div>
      </section>
    </div>
  );
}

function FamilyNode({
  family,
  openKey,
  onToggle,
  depth = 0,
}: {
  family: JobFamilyNode;
  openKey: string | null;
  onToggle: (key: string) => void;
  depth?: number;
}) {
  const isOpen = openKey === family.key;
  return (
    <div style={{ paddingLeft: depth * 12 }}>
      <button
        onClick={() => onToggle(family.key)}
        className={`w-full text-left text-sm px-3 py-2 rounded-lg flex items-center justify-between ${
          isOpen ? "bg-primary-50 text-primary-700 font-medium" : "hover:bg-slate-100"
        }`}
      >
        <span>{family.label}</span>
        <span className="text-xs text-slate-400">{family.job_count}</span>
      </button>
      {(isOpen || familyHasOpenChild(family, openKey)) &&
        family.children.map((c) => (
          <FamilyNode key={c.key} family={c} openKey={openKey} onToggle={onToggle} depth={depth + 1} />
        ))}
    </div>
  );
}

function familyHasOpenChild(family: JobFamilyNode, openKey: string | null): boolean {
  return family.children.some((c) => c.key === openKey || familyHasOpenChild(c, openKey));
}
