import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bookmark, Plus, X } from "lucide-react";
import {
  fetchPostings,
  searchPostings,
  type PostingSearchParams,
} from "@/api/postings";
import { fetchSkillOntology } from "@/api/skills";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { PostingDetail } from "@/features/postings/components/PostingDetail";
import { EmptyState, SearchableDropdown } from "@/components/ui";
import type { PostingsResponse } from "@/types/wire";

interface SkillFilter {
  key: string;
  level: number | null;
}

export function PostingsFeed() {
  const { t } = useTranslation();
  const [feed, setFeed] = useState<PostingsResponse | null>(null);
  const [view, setView] = useState<"all" | "saved">("all");
  const [sort, setSort] = useState<"fit" | "fresh">("fit");
  const [error, setError] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const [detailId, setDetailId] = useState<string | null>(
    searchParams.get("posting")
  );
  const [skillOptions, setSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [skillKey, setSkillKey] = useState("");
  const [skillLevel, setSkillLevel] = useState<number | null>(null);
  const [skillFilters, setSkillFilters] = useState<SkillFilter[]>([]);
  const [matchMode, setMatchMode] = useState<"all" | "any">("all");
  const [priority, setPriority] = useState("");
  const [matchProfile, setMatchProfile] = useState(false);
  const [company, setCompany] = useState(searchParams.get("company") ?? "");
  const [unlinked, setUnlinked] = useState(searchParams.get("no_company") ?? "");

  useEffect(() => {
    void fetchSkillOntology()
      .then((skills) =>
        setSkillOptions(
          skills
            .filter((s) => s.status === "active")
            .map((s) => ({ value: s.key, label: s.label }))
        )
      )
      .catch(() => setSkillOptions([]));
  }, []);

  const load = (currentView: "all" | "saved", currentSort: "fit" | "fresh") => {
    if (skillFilters.length > 0) {
      const params: PostingSearchParams = {
        skills: skillFilters
          .map((f) => (f.level ? `${f.key}:${f.level}` : f.key))
          .join(","),
        mode: matchMode,
        saved: currentView === "saved",
        sort: currentSort,
        match_profile: matchProfile,
      };
      if (priority) params.priority = priority;
      if (company) params.company = company;
      if (unlinked) params.no_company = unlinked;
      void searchPostings(params)
        .then(setFeed)
        .catch((err) => setError(String(err)));
      return;
    }
    setMatchProfile(false);
    void fetchPostings({
      saved: currentView === "saved",
      sort: currentSort,
      ...(company ? { company } : {}),
      ...(unlinked ? { no_company: unlinked } : {}),
    })
      .then(setFeed)
      .catch((err) => setError(String(err)));
  };

  useEffect(() => {
    load(view, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, sort, skillFilters, matchMode, priority, matchProfile, company, unlinked]);

  const addSkillFilter = () => {
    const key = skillKey.trim();
    if (!key) return;
    setSkillFilters((prev) =>
      prev.some((f) => f.key === key)
        ? prev
        : [...prev, { key, level: skillLevel }]
    );
    setSkillKey("");
    setSkillLevel(null);
  };

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
            value={unlinked}
            onChange={(e) => {
              setUnlinked(e.target.value);
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
        </div>
      </div>

      {company && (
        <div className="flex items-center gap-2">
          <span
            className="text-xs bg-primary-50 text-primary-700 px-2 py-1 rounded-lg flex items-center gap-1"
            data-testid="company-chip"
          >
            {t("postings.companyChip")}: {company}
            <button
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
        </div>
      )
      }

      <div
        className="bg-white border border-slate-200 rounded-xl p-3 flex flex-wrap items-center gap-2"
        data-testid="skill-search-bar"
      >
        <div className="min-w-56 flex-1">
          <SearchableDropdown
            options={skillOptions}
            value={skillKey}
            onChange={(value) => setSkillKey(value)}
            placeholder={t("postings.filterBySkill")}
            clearable
          />
        </div>
        <select
          value={skillLevel ?? ""}
          onChange={(e) => setSkillLevel(e.target.value ? Number(e.target.value) : null)}
          className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
          data-testid="level-select"
          aria-label={t("postings.minLevel")}
        >
          <option value="">{t("postings.anyLevel")}</option>
          {Array.from({ length: 10 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {t("postings.levelAtLeast")} {i + 1}
            </option>
          ))}
        </select>
        <button
          onClick={addSkillFilter}
          disabled={!skillKey}
          className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary-600 text-white disabled:opacity-40"
          data-testid="add-skill-filter"
        >
          <Plus className="w-3.5 h-3.5" /> {t("common.add")}
        </button>
        {skillFilters.length > 0 && (
          <>
            <select
              value={matchMode}
              onChange={(e) => setMatchMode(e.target.value as "all" | "any")}
              className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="match-mode"
              aria-label={t("postings.matchMode")}
            >
              <option value="all">{t("postings.allSkills")}</option>
              <option value="any">{t("postings.anySkill")}</option>
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="priority-select"
              aria-label={t("postings.priority")}
            >
              <option value="">{t("postings.anyPriority")}</option>
              <option value="must_have">{t("postings.mustHave")}</option>
              <option value="nice_to_have">{t("postings.niceToHave")}</option>
              <option value="bonus">{t("postings.bonus")}</option>
            </select>
            <label className="flex items-center gap-1.5 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={matchProfile}
                onChange={(e) => setMatchProfile(e.target.checked)}
                data-testid="match-profile-toggle"
              />
              {t("postings.matchProfile")}
            </label>
            {skillFilters.map((filter) => (
              <span
                key={filter.key}
                className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-lg flex items-center gap-1"
                data-testid={`skill-chip-${filter.key}`}
              >
                {filter.key}
                {filter.level ? ` ≥ ${filter.level}` : ""}
                <button
                  onClick={() =>
                    setSkillFilters((prev) => prev.filter((f) => f.key !== filter.key))
                  }
                  aria-label={t("postings.removeFilter", { name: filter.key })}
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </>
        )}
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

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
          <PostingCard
            key={posting.id}
            posting={posting}
            onOpenDetail={() => setDetailId(posting.id)}
            onChanged={() => load(view, sort)}
          />
        ))}
      </div>
      {detailId && (
        <PostingDetail
          postingId={detailId}
          onClose={() => {
            setDetailId(null);
            if (searchParams.get("posting")) {
              searchParams.delete("posting");
              setSearchParams(searchParams, { replace: true });
            }
          }}
        />
      )}
    </div>
  );
}
