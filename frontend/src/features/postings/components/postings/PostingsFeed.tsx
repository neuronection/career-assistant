import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bookmark, X } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import {
  filterPostings,
  reextractPostings,
  emptyFilterSpec,
  type FilterSpec,
} from "@/api/postings";
import { FilterRail } from "@/features/postings/components/postings/FilterRail";
import { PresetBar } from "@/features/postings/components/postings/PresetBar";
import {
  buildSummaryChips,
  countActiveFilters,
  decodeFilterSpec,
  encodeFilterSpec,
  removeChip,
} from "@/features/postings/components/postings/filterState";
import { fetchPostings } from "@/api/postings";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { EmptyState } from "@/components/ui";
import type { PostingsResponse } from "@/types/wire";

export function PostingsFeed() {
  const { t } = useTranslation();
  const [feed, setFeed] = useState<PostingsResponse | null>(null);
  const [view, setView] = useState<"all" | "saved">("all");
  const [sort, setSort] = useState<"fit" | "fresh">("fit");
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [company, setCompany] = useState(searchParams.get("company") ?? "");
  const [noCompany, setNoCompany] = useState(searchParams.get("no_company") ?? "");

  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionNote, setActionNote] = useState("");
  const [filterSpec, setFilterSpec] = useState<FilterSpec>(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      return decodeFilterSpec(params.get("f")) ?? emptyFilterSpec();
    } catch {
      return emptyFilterSpec();
    }
  });
  const [railOpen, setRailOpen] = useState(false);
  const summaryChips = buildSummaryChips(filterSpec);
  const activeFilterCount = countActiveFilters(filterSpec);
  const feedParams = {
    ...(company ? { company } : {}),
    ...(noCompany ? { no_company: noCompany } : {}),
  };

  const runReextract = async () => {
    if (selected.length === 0) return;
    setActionBusy(true);
    setActionNote("");
    try {
      const result = await reextractPostings(selected);
      setActionNote(t("postings.reextractDone", { count: result.queued }));
      setSelected([]);
      load(view, sort);
    } catch (err) {
      setActionNote(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(false);
    }
  };

  const load = (currentView: "all" | "saved", currentSort: "fit" | "fresh") => {
    void fetchPostings({ saved: currentView === "saved", sort: currentSort, ...feedParams })
      .then(setFeed)
      .catch((err) => setError(String(err)));
  };

  const loadFiltered = (spec: FilterSpec) => {
    const params = new URLSearchParams(window.location.search);
    if (countActiveFilters(spec) > 0) {
      params.set("f", encodeFilterSpec(spec));
    } else {
      params.delete("f");
    }
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
    if (countActiveFilters(spec) === 0) {
      load(view, sort);
      return;
    }
    void filterPostings(spec, feedParams)
      .then((items) => setFeed({ items, total: items.length, unseen: 0 } as PostingsResponse))
      .catch((err) => setError(String(err)));
  };

  useEffect(() => {
    load(view, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, sort, company, noCompany]);

  // Auto-apply: every filter change triggers a debounced search.
  useEffect(() => {
    const timer = setTimeout(() => {
      loadFiltered(filterSpec);
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSpec]);

  return (
    <div className="space-y-6" data-testid="postings">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {t("postings.intro")}
          {feed && feed.unseen > 0 ? ` — ${feed.unseen} new` : ""}.
        </p>
        <div className="flex gap-2 items-center">
          <button
            onClick={() => setView("saved")}
            className={`text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border ${
              view === "saved" ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
            }`}
            data-testid="postings-saved-toggle"
          >
            <Bookmark className="w-3.5 h-3.5" /> {t("jobDetail.saved")}
          </button>
          <button
            onClick={() => setView("all")}
            className={`text-sm px-3 py-1.5 rounded-lg border ${
              view === "all" ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
            }`}
          >
            {t("postings.discover")}
          </button>
          <select
            value={noCompany}
            onChange={(e) => {
              setNoCompany(e.target.value);
              const next = new URLSearchParams(searchParams);
              if (e.target.value) next.set("no_company", e.target.value);
              else next.delete("no_company");
              setSearchParams(next, { replace: true });
            }}
            className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
            data-testid="unlinked-filter"
            aria-label={t("postings.companyFilter")}
          >
            <option value="">{t("postings.allCompanies")}</option>
            <option value="rejected">{t("postings.noCompanyRejected")}</option>
            <option value="pending">{t("postings.noCompanyPending")}</option>
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as "fit" | "fresh")}
            className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
            data-testid="postings-sort"
          >
            <option value="fit">{t("postings.sortBestFit")}</option>
            <option value="fresh">{t("postings.sortFreshest")}</option>
          </select>
          {isAdmin ? (
            <button
              onClick={() => {
                setSelecting((prev) => !prev);
                setSelected([]);
              }}
              className={`text-sm px-3 py-1.5 rounded-lg border ${
                selecting
                  ? "bg-primary-600 text-white border-primary-600"
                  : "border-slate-200"
              }`}
              data-testid="postings-select-toggle"
            >
              {t("postings.select")}
            </button>
          ) : null}
        </div>
      </div>

      {(activeFilterCount > 0 || company) && (
        <div className="flex flex-wrap gap-2" data-testid="filter-summary">
          {company ? (
            <span
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-primary-200 bg-primary-50 text-primary-700"
              data-testid="company-chip"
            >
              {t("postings.companyChip")}: {company}
              <button
                type="button"
                onClick={() => {
                  setCompany("");
                  const next = new URLSearchParams(searchParams);
                  next.delete("company");
                  setSearchParams(next, { replace: true });
                }}
                aria-label={t("postings.clearCompanyFilter")}
                data-testid="company-chip-clear"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ) : null}
          {summaryChips.map((chip, i) => (
            <button
              key={`${chip.axis}-${chip.value}-${i}`}
              type="button"
              className={`inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                chip.kind === "exclude"
                  ? "border-rose-200 bg-rose-50 text-rose-700"
                  : "border-primary-200 bg-primary-50 text-primary-700"
              }`}
              onClick={() => setFilterSpec((prev) => removeChip(prev, chip))}
              title={t("postings.filtersRemoveChip")}
            >
              {chip.label}
              <span className="text-xs opacity-50">×</span>
            </button>
          ))}
        </div>
      )}

      <PresetBar
        spec={filterSpec}
        onApplyPreset={(filters) => {
          setFilterSpec(filters);
          loadFiltered(filters);
        }}
      />

      <details
        open={railOpen}
        className="group"
        data-testid="filter-rail-wrapper"
      >
        <summary
          className="cursor-pointer text-sm text-slate-600 select-none py-1"
          onClick={(e) => {
            e.preventDefault();
            setRailOpen((v) => !v);
          }}
        >
          <span className="font-medium">{t("postings.filtersTitle")}</span>
          {activeFilterCount > 0 ? (
            <span className="ml-2 text-xs text-primary-600">
              {t("postings.filtersActive", { count: activeFilterCount })}
            </span>
          ) : null}
          <span className="ml-2 text-xs text-slate-400">
            {railOpen ? t("postings.filtersHide") : t("postings.filtersShow")}
          </span>
        </summary>
        {railOpen ? (
          <FilterRail
            spec={filterSpec}
            onChange={setFilterSpec}
            onClear={() => {
              const empty = emptyFilterSpec();
              setFilterSpec(empty);
              loadFiltered(empty);
            }}
          />
        ) : null}
      </details>


      {error && <p className="text-sm text-rose-600">{error}</p>}

      {selecting ? (
        <div
          className="bg-white border border-slate-200 rounded-xl p-3 flex flex-wrap items-center gap-2"
          data-testid="selection-bar"
        >
          <span className="text-sm text-slate-600" data-testid="selection-count">
            {t("postings.selectedCount", { count: selected.length })}
          </span>
          <details className="relative">
            <summary className="text-sm px-3 py-1.5 rounded-lg border border-slate-200 cursor-pointer select-none">
              {t("postings.actions")}
            </summary>
            <div className="absolute z-10 mt-1 w-60 rounded-lg border border-slate-200 bg-white shadow-lg">
              <button
                type="button"
                disabled={actionBusy || selected.length === 0}
                className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40"
                onClick={() => void runReextract()}
                data-testid="action-reextract"
              >
                {t("postings.reextract")}
              </button>
            </div>
          </details>
          <button
            type="button"
            className="text-sm text-slate-500 hover:text-slate-700"
            onClick={() => setSelected([])}
          >
            {t("postings.clearSelection")}
          </button>
          {actionNote ? (
            <span className="text-sm text-emerald-600" role="status">
              {actionNote}
            </span>
          ) : null}
        </div>
      ) : null}

      {feed && feed.items.length === 0 && (
        <EmptyState
          title={view === "saved" ? t("postings.nothingSavedYet") : t("postings.noLivePostings")}
          description={
            view === "saved"
              ? t("postings.bookmarkHint")
              : t("postings.connectSourceHint")
          }
        />
      )}

      <div className="space-y-3">
        {(feed?.items ?? []).map((posting) => (
          <div key={posting.id} className="flex items-start gap-2">
            {selecting ? (
              <input
                type="checkbox"
                className="mt-4 h-4 w-4"
                aria-label={posting.title}
                checked={selected.includes(posting.id)}
                onChange={() =>
                  setSelected((prev) =>
                    prev.includes(posting.id)
                      ? prev.filter((id) => id !== posting.id)
                      : [...prev, posting.id],
                  )
                }
              />
            ) : null}
            <div className="min-w-0 flex-1">
              <PostingCard
                posting={posting}
                onOpen={(item) => navigate(`/postings/${item.ref}`)}
                onChanged={() => load(view, sort)}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
