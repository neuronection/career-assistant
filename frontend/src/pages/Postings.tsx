import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bookmark, Plus, X } from "lucide-react";
import {
  fetchPostings,
  searchPostings,
  type PostingSearchParams,
} from "@/api/postings";
import { fetchSkillOntology } from "@/api/skills";
import { PostingCard } from "@/components/PostingCard";
import { PostingDetail } from "@/components/PostingDetail";
import { EmptyState, SearchableDropdown } from "@/components/ui";
import type { PostingsResponse } from "@/types";

interface SkillFilter {
  key: string;
  level: number | null;
}

export function Postings() {
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
      void searchPostings(params)
        .then(setFeed)
        .catch((err) => setError(String(err)));
      return;
    }
    setMatchProfile(false);
    void fetchPostings({ saved: currentView === "saved", sort: currentSort })
      .then(setFeed)
      .catch((err) => setError(String(err)));
  };

  useEffect(() => {
    load(view, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, sort, skillFilters, matchMode, priority, matchProfile]);

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
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Live postings</h1>
          <p className="text-sm text-slate-500 mt-1">
            Real vacancies from your connected sources, mapped onto your catalog
            {feed && feed.unseen > 0 ? ` — ${feed.unseen} new` : ""}.
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            onClick={() => setView("saved")}
            className={`text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg border ${
              view === "saved" ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
            }`}
            data-testid="postings-saved-toggle"
          >
            <Bookmark className="w-3.5 h-3.5" /> Saved
          </button>
          <button
            onClick={() => setView("all")}
            className={`text-sm px-3 py-1.5 rounded-lg border ${
              view === "all" ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
            }`}
          >
            Discover
          </button>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as "fit" | "fresh")}
            className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
            data-testid="postings-sort"
          >
            <option value="fit">Best fit</option>
            <option value="fresh">Freshest</option>
          </select>
        </div>
      </div>

      <div
        className="bg-white border border-slate-200 rounded-xl p-3 flex flex-wrap items-center gap-2"
        data-testid="skill-search-bar"
      >
        <div className="min-w-56 flex-1">
          <SearchableDropdown
            options={skillOptions}
            value={skillKey}
            onChange={(value) => setSkillKey(value)}
            placeholder="Filter by skill…"
            clearable
          />
        </div>
        <select
          value={skillLevel ?? ""}
          onChange={(e) => setSkillLevel(e.target.value ? Number(e.target.value) : null)}
          className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
          data-testid="level-select"
          aria-label="Minimum level"
        >
          <option value="">any level</option>
          {Array.from({ length: 10 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              level ≥ {i + 1}
            </option>
          ))}
        </select>
        <button
          onClick={addSkillFilter}
          disabled={!skillKey}
          className="text-sm flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary-600 text-white disabled:opacity-40"
          data-testid="add-skill-filter"
        >
          <Plus className="w-3.5 h-3.5" /> Add
        </button>
        {skillFilters.length > 0 && (
          <>
            <select
              value={matchMode}
              onChange={(e) => setMatchMode(e.target.value as "all" | "any")}
              className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="match-mode"
              aria-label="Match mode"
            >
              <option value="all">all skills</option>
              <option value="any">any skill</option>
            </select>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="priority-select"
              aria-label="Priority"
            >
              <option value="">any priority</option>
              <option value="must_have">must have</option>
              <option value="nice_to_have">nice to have</option>
              <option value="bonus">bonus</option>
            </select>
            <label className="flex items-center gap-1.5 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={matchProfile}
                onChange={(e) => setMatchProfile(e.target.checked)}
                data-testid="match-profile-toggle"
              />
              match my profile
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
                  aria-label={`Remove ${filter.key}`}
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
          title={view === "saved" ? "Nothing saved yet" : "No live postings yet"}
          description={
            view === "saved"
              ? "Bookmark postings to keep them here."
              : "Ask an admin to connect a posting source (ATS feed, RSS, CSV) to see real vacancies here."
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
