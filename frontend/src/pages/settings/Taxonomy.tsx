import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import { Languages, Network, Route, Sparkles, Tags, Wrench } from "lucide-react";
import { SettingsPage } from "@/components/settings/SettingsPage";
import {
  bulkEnrichmentAction,
  bulkInterestAction,
  bulkJobProposalDismiss,
  bulkPathAction,
  bulkSkillAction,
  createTag,
  deleteTag,
  fetchEnrichmentQueue,
  fetchInterests,
  fetchJobProposals,
  fetchSkillRows,
  fetchTaxonomyStats,
  mergeSkill,
  promoteSkill,
  updateTag,
  type BulkActionResult,
  type EnrichmentBulkAction,
  type EnrichmentRow,
  type InterestBulkAction,
  type JobProposalRow,
  type PathBulkAction,
  type SkillBulkAction,
  type SkillRow,
  type Tag,
  type TaxonomyStats,
} from "@/api/taxonomy";
import { api } from "@/api/client";
import { apiDetail } from "@/api/client";
import { fetchFamilyTree } from "@/api/jobs";
import { useInfiniteScroll } from "@/hooks/useInfiniteScroll";
import { usePagedQueue } from "@/hooks/usePagedQueue";
import {
  Button,
  ConfirmationModal,
  EmptyState,
  SegmentedTabs,
  Spinner,
} from "@/components/ui";
import {
  InterestDetailsDrawer,
  SkillDetailsDrawer,
} from "@/components/settings/EntityDetailsDrawer";
import {
  TaxonomyList,
  filterTaxonomyRows,
  type TaxonomyGroup,
  type TaxonomyRowView,
} from "@/components/settings/TaxonomyList";
import {
  TaxonomyPathCards,
  type PathRow,
} from "@/components/settings/TaxonomyPathCards";
import {
  TaxonomyEnrichmentCards,
} from "@/components/settings/TaxonomyEnrichmentCards";
import {
  TaxonomyJobProposalCards,
} from "@/components/settings/TaxonomyJobProposalCards";
import { TaxonomyCatalogHygieneCard } from "@/components/settings/TaxonomyCatalogHygieneCard";
import { regenerateJobProposals } from "@/api/taxonomy";
import { categoryIcon, STATUS_GROUP_ICONS } from "@/components/settings/taxonomyIcons";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import {
  parseRelationSection,
  SkillRelationsPanel,
  type RelationSection,
} from "@/components/settings/SkillRelationsPanel";
import { TranslationsBoard } from "@/components/settings/TranslationsBoard";
import {
  SelectionEntry,
  SelectionToolbar,
  useListSelection,
  type BulkFailure,
} from "@/features/selection";

export type TaxonomyTab =
  | "interests"
  | "skills"
  | "paths"
  | "enrichment"
  | "translations"
  | "relations";

// Exported for the taxonomy-tabs conformance tests.
export const TAXONOMY_TABS: readonly TaxonomyTab[] = [
  "interests",
  "skills",
  "paths",
  "enrichment",
  "translations",
  "relations",
];

export function parseTaxonomyTab(raw: string | null): TaxonomyTab {
  return (TAXONOMY_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as TaxonomyTab)
    : "interests";
}

/** Tab strip icons (plan 150 phase 5) — every segment carries one. */
const TAB_ICONS: Record<TaxonomyTab, LucideIcon> = {
  interests: Tags,
  skills: Wrench,
  paths: Route,
  enrichment: Sparkles,
  translations: Languages,
  relations: Network,
};

/** Interest category groups (plan 150) — seed order, unknown categories
 * fall into the catch-all group at the end. */
const INTEREST_GROUPS: TaxonomyGroup[] = [
  "arts",
  "business",
  "hands-on",
  "people",
  "science",
  "society",
  "sports",
  "technology",
].map((key) => ({
  key,
  labelKey: `taxonomy.group.${key}`,
  icon: categoryIcon(key),
}));
INTEREST_GROUPS.push({ key: "other", labelKey: "taxonomy.group.other", icon: categoryIcon("") });

/** Skills group by STATUS (triage: proposed first — 605 proposed vs 32
 * curated; the rows keep their category icons). */
const SKILL_GROUPS: TaxonomyGroup[] = (["proposed", "active", "deprecated"] as const).map(
  (key) => ({
    key,
    labelKey: `taxonomy.filter.${key}`,
    icon: STATUS_GROUP_ICONS[key],
  }),
);

const INTEREST_FILTERS = [
  { value: "all", labelKey: "taxonomy.filter.all" },
  { value: "active", labelKey: "taxonomy.filter.active" },
  { value: "deprecated", labelKey: "taxonomy.filter.deprecated" },
];

const SKILL_FILTERS = [
  { value: "all", labelKey: "taxonomy.filter.all" },
  { value: "proposed", labelKey: "taxonomy.filter.proposed" },
  { value: "active", labelKey: "taxonomy.filter.active" },
  { value: "deprecated", labelKey: "taxonomy.filter.deprecated" },
];

/** Queue windows (plan 206): enrichment cards are tall (a chip row per
 * proposal field), job proposals are lighter and stay on the endpoint's
 * 50-row default. Both endpoints cap at 200. */
const ENRICHMENT_PAGE_SIZE = 25;
const PROPOSAL_PAGE_SIZE = 50;

/** Row mappers live at module scope so the page and the list share ONE
 * identity — `filterTaxonomyRows` is the selection scope's source of truth. */
const interestView = (tag: Tag): TaxonomyRowView => ({
  id: tag.id,
  key: tag.key,
  label: tag.label,
  category: tag.category,
  hint: tag.description || undefined,
  status: tag.deprecated ? "deprecated" : "active",
});

const skillView = (skill: SkillRow): TaxonomyRowView => ({
  id: skill.id,
  key: skill.key,
  label: skill.label,
  category: skill.category,
  hint:
    skill.aliases.length > 0
      ? skill.aliases.join(", ")
      : skill.description || undefined,
  status: skill.status,
});

const interestGroupOf = (tag: Tag) =>
  INTEREST_GROUPS.some((group) => group.key === tag.category)
    ? tag.category
    : "other";

const skillGroupOf = (skill: SkillRow) => skill.status;

/** Admin taxonomy management: create, edit, promote/deprecate, merge, delete. */
export function Taxonomy() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const kind = parseTaxonomyTab(searchParams.get("tab"));
  const section = parseRelationSection(searchParams.get("section"));
  const [tags, setTags] = useState<Tag[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [stats, setStats] = useState<TaxonomyStats | null>(null);
  const [paths, setPaths] = useState<PathRow[]>([]);
  const [legacyProposals, setLegacyProposals] = useState(0);
  const [familyOptions, setFamilyOptions] = useState<
    Array<{ key: string; label: string; depth: number }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ key: "", label: "", category: "", description: "" });
  const [query, setQuery] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkTarget, setBulkTarget] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkFailures, setBulkFailures] = useState<BulkFailure[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [details, setDetails] = useState<{
    kind: "interests" | "skills";
    id: string;
  } | null>(null);
  const [interestFilter, setInterestFilter] = useState("all");
  const [skillFilter, setSkillFilter] = useState("all");

  useEffect(() => {
    const expectedTab = kind === "interests" ? null : kind;
    const expectedSection = kind === "relations" && section !== "queue" ? section : null;
    if (
      searchParams.get("tab") === expectedTab &&
      searchParams.get("section") === expectedSection
    ) {
      return;
    }
    const next = new URLSearchParams(searchParams);
    if (expectedTab) next.set("tab", expectedTab);
    else next.delete("tab");
    if (expectedSection) next.set("section", expectedSection);
    else next.delete("section");
    setSearchParams(next, { replace: true });
  }, [kind, section, searchParams, setSearchParams]);

  const refreshStats = useCallback(async () => {
    try {
      const loaded = await fetchTaxonomyStats();
      setStats(loaded?.skills && loaded?.queue ? loaded : null);
    } catch {
      setStats(null);
    }
  }, []);

  const fetchEnrichmentPage = useCallback(
    (cursor: string | null) => fetchEnrichmentQueue(cursor, ENRICHMENT_PAGE_SIZE),
    [],
  );
  const fetchProposalPage = useCallback(async (cursor: string | null) => {
    const page = await fetchJobProposals(cursor, PROPOSAL_PAGE_SIZE);
    if (cursor === null) setLegacyProposals(page.legacy_count);
    return page;
  }, []);
  const enrichment = usePagedQueue<EnrichmentRow>({
    fetchPage: fetchEnrichmentPage,
    keyOf: (row) => row.id,
    pageSize: ENRICHMENT_PAGE_SIZE,
    onError: setError,
  });
  const proposals = usePagedQueue<JobProposalRow>({
    fetchPage: fetchProposalPage,
    keyOf: (row) => row.id,
    pageSize: PROPOSAL_PAGE_SIZE,
    onError: setError,
  });
  const { refresh: refreshEnrichmentQueue, loadMore: loadMoreEnrichment } = enrichment;
  const { refresh: refreshProposalQueue, remove: removeProposals } = proposals;

  const loadFamilyOptions = useCallback(async () => {
    try {
      const tree = await fetchFamilyTree();
      // The picker offers the WHOLE family tree: catalog jobs live in
      // child families (IT jobs sit under "Technology & IT › IT
      // Operations & Security"), and the affinity suggestion names the
      // exact family — a top-level-only list would silently fall back
      // to the first option.
      const flatten: Array<{ key: string; label: string; depth: number }> = [];
      const walk = (nodes: typeof tree, parentLabel: string, depth: number) => {
        for (const node of nodes) {
          const label = parentLabel ? `${parentLabel} › ${node.label}` : node.label;
          flatten.push({ key: node.key, label, depth });
          if (node.children?.length) {
            walk(node.children, label, depth + 1);
          }
        }
      };
      walk(tree, "", 0);
      setFamilyOptions(flatten);
    } catch {
      setFamilyOptions([]);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (kind === "interests") {
        setTags(await fetchInterests());
      } else if (kind === "skills") {
        setSkills(await fetchSkillRows());
      } else if (kind === "paths") {
        const { data } = await api.get<PathRow[]>("/admin/paths", {
          params: { status: "draft" },
        });
        setPaths(data);
      }
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
    await refreshStats();
  }, [kind, refreshStats]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (kind !== "enrichment") return;
    void refreshEnrichmentQueue();
    void refreshProposalQueue();
    void loadFamilyOptions();
  }, [kind, refreshEnrichmentQueue, refreshProposalQueue, loadFamilyOptions]);

  const enrichmentSentinelRef = useInfiniteScroll(
    loadMoreEnrichment,
    kind === "enrichment" && !!enrichment.cursor,
  );
  const proposalsSentinelRef = useInfiniteScroll(
    proposals.loadMore,
    kind === "enrichment" && !!proposals.cursor,
  );

  const interestIds = useMemo(() => tags.map((tag) => tag.id), [tags]);
  const skillIds = useMemo(() => skills.map((skill) => skill.id), [skills]);
  const interestMatching = useMemo(
    () => filterTaxonomyRows(tags, interestView, interestFilter, query),
    [tags, interestFilter, query],
  );
  const skillMatching = useMemo(
    () => filterTaxonomyRows(skills, skillView, skillFilter, query),
    [skills, skillFilter, query],
  );
  const interestMatchingIds = useMemo(
    () => interestMatching.map((tag) => tag.id),
    [interestMatching],
  );
  const skillMatchingIds = useMemo(
    () => skillMatching.map((skill) => skill.id),
    [skillMatching],
  );

  const listingIds = kind === "skills" ? skillIds : interestIds;
  const matchingIds = kind === "skills" ? skillMatchingIds : interestMatchingIds;
  const selection = useListSelection({ allIds: listingIds, matchingIds });
  const exitSelection = selection.exit;

  useEffect(() => {
    exitSelection();
    setQuery("");
    setBulkTarget("");
    setBulkNote("");
    setBulkFailures([]);
  }, [kind, exitSelection]);

  const onCreate = async () => {
    setError("");
    try {
      await createTag(kind === "skills" ? "skills" : (kind === "interests" ? "interests" : "skills"), draft);
      setDraft({ key: "", label: "", category: "", description: "" });
      setCreating(false);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  /** Drawer-action plumbing: every mutation reports success so the
   * drawer can react (close on delete, close its edit/merge form). */
  const runAction = async (action: () => Promise<unknown>): Promise<boolean> => {
    setError("");
    try {
      await action();
      await load();
      return true;
    } catch (err) {
      setError(apiDetail(err));
      return false;
    }
  };

  /** Interests toggle the `deprecated` flag (the old row buttons' exact
   * payload); skills go through the status field. */
  const toggleInterestDeprecated = (tag: Tag) =>
    runAction(() => updateTag("interests", tag.id, { deprecated: !tag.deprecated }));

  const editInterest = (
    tag: Tag,
    patch: { label: string; category: string; description: string },
  ) => runAction(() => updateTag("interests", tag.id, patch));

  const setSkillStatus = (skill: SkillRow, status: "active" | "deprecated") =>
    runAction(() => updateTag("skills", skill.id, { status }));

  const promoteById = (id: string) => runAction(() => promoteSkill(id));

  const mergeById = (id: string, targetId: string) =>
    runAction(() => mergeSkill(id, targetId));

  const removeById = async (
    taxonomyKind: "interests" | "skills",
    id: string,
  ): Promise<boolean> => {
    setError("");
    setNote("");
    try {
      await deleteTag(taxonomyKind, id);
      await load();
      return true;
    } catch (err) {
      setError(apiDetail(err));
      setNote(t("taxonomy.referencedNote"));
      return false;
    }
  };

  const setSection = (next: RelationSection) => {
    const nextParams = new URLSearchParams(searchParams);
    if (next === "queue") nextParams.delete("section");
    else nextParams.set("section", next);
    setSearchParams(nextParams, { replace: true });
  };

  const applyBulk = async (action: SkillBulkAction, ids: string[]) => {
    if (ids.length === 0) return;
    setError("");
    setNote("");
    setBulkNote("");
    setBulkFailures([]);
    setBulkBusy(true);
    try {
      const result = await bulkSkillAction(
        ids,
        action,
        action === "merge" ? bulkTarget : undefined,
      );
      selection.clear();
      setBulkTarget("");
      if (result.affected.length > 0) {
        setBulkNote(
          action === "delete"
            ? t("taxonomy.bulk.deleted", { count: result.affected.length })
            : t("taxonomy.bulk.done", { count: result.affected.length }),
        );
      }
      setBulkFailures(result.failed);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const applyInterestBulk = async (action: InterestBulkAction, ids: string[]) => {
    if (ids.length === 0) return;
    setError("");
    setNote("");
    setBulkNote("");
    setBulkFailures([]);
    setBulkBusy(true);
    try {
      const result = await bulkInterestAction(ids, action);
      selection.clear();
      if (result.affected.length > 0) {
        setBulkNote(
          t(
            action === "delete"
              ? "taxonomy.bulk.interestsDeleted"
              : "taxonomy.bulk.interestsDone",
            { count: result.affected.length },
          ),
        );
      }
      reportBulkFailures(result, (id) => tags.find((tag) => tag.id === id)?.key);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const moderatePath = async (id: string, action: "publish" | "reject") => {
    setError("");
    try {
      await api.post(`/admin/paths/${id}/${action}`);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const reportBulkFailures = (
    result: BulkActionResult,
    keyOf: (id: string) => string | undefined,
  ) => {
    setBulkFailures(
      result.failed.map((failure) => ({
        ...failure,
        key: keyOf(failure.id) ?? failure.id,
      })),
    );
    if (result.warning) setNote(result.warning);
  };

  const bulkModerateEnrichment = async (ids: string[], action: EnrichmentBulkAction) => {
    setError("");
    setNote("");
    setBulkNote("");
    setBulkFailures([]);
    try {
      const result = await bulkEnrichmentAction(ids, action);
      if (result.affected.length > 0) {
        setBulkNote(
          t(
            action === "apply"
              ? "taxonomy.enrich.bulkApplied"
              : "taxonomy.enrich.bulkRejected",
            { count: result.affected.length },
          ),
        );
      }
      reportBulkFailures(result, (id) => enrichment.items.find((row) => row.id === id)?.code);
      enrichment.remove(result.affected);
      await refreshStats();
      return true;
    } catch (err) {
      setError(apiDetail(err));
      return false;
    }
  };

  const bulkModeratePaths = async (ids: string[], action: PathBulkAction) => {
    setError("");
    setNote("");
    setBulkNote("");
    setBulkFailures([]);
    try {
      const result = await bulkPathAction(ids, action);
      if (result.affected.length > 0) {
        setBulkNote(
          t(
            action === "publish"
              ? "taxonomy.bulkPaths.published"
              : "taxonomy.bulkPaths.rejected",
            { count: result.affected.length },
          ),
        );
      }
      reportBulkFailures(result, (id) => paths.find((row) => row.id === id)?.title);
      await load();
      return true;
    } catch (err) {
      setError(apiDetail(err));
      return false;
    }
  };

  const bulkDismissProposals = async (ids: string[]) => {
    setError("");
    setNote("");
    setBulkNote("");
    setBulkFailures([]);
    try {
      const result = await bulkJobProposalDismiss(ids);
      if (result.affected.length > 0) {
        setBulkNote(
          t("taxonomy.jobProposals.bulkDismissed", {
            count: result.affected.length,
          }),
        );
      }
      reportBulkFailures(
        result,
        (id) => proposals.items.find((row) => row.id === id)?.ref,
      );
      removeProposals(result.affected);
      await refreshStats();
      return true;
    } catch (err) {
      setError(apiDetail(err));
      return false;
    }
  };

  const regenerateProposals = async () => {
    setError("");
    try {
      const result = await regenerateJobProposals({});
      setNote(
        t("taxonomy.jobProposals.legacyQueued", {
          count: legacyProposals,
          jobId: result.job_id,
        }),
      );
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const moderateEnrichment = async (id: string, action: "apply" | "reject") => {
    setError("");
    try {
      await api.post(`/admin/jobs/${id}/enrichment/${action}`);
      enrichment.remove([id]);
      await refreshStats();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const noteAfterModeration = async (noteText: string) => {
    setNote(noteText);
    await refreshStats();
  };

  const activeSkills = skills.filter((s) => s.status === "active");
  const proposed = skills.filter((s) => s.status === "proposed");
  const selectedSkills = skills.filter((s) => selection.isSelected(s.id));
  const promotableIds = selectedSkills.filter((s) => s.status === "proposed").map((s) => s.id);
  const deprecatableIds = selectedSkills.filter((s) => s.status === "active").map((s) => s.id);
  const restorableIds = selectedSkills.filter((s) => s.status === "deprecated").map((s) => s.id);
  const mergeableIds = selectedSkills.filter((s) => s.status !== "active").map((s) => s.id);
  const mergeTargets = activeSkills.filter((s) => !selection.isSelected(s.id));

  const selectedInterests = tags.filter((tag) => selection.isSelected(tag.id));
  const deprecatableInterestIds = selectedInterests
    .filter((tag) => !tag.deprecated)
    .map((tag) => tag.id);
  const restorableInterestIds = selectedInterests
    .filter((tag) => tag.deprecated)
    .map((tag) => tag.id);

  /** Queue backlog per tab — server counts only (plan 161), so a tab
   * label and the stats bar can never disagree. The enrichment tab holds
   * two queues; both counts come from the stats payload, never from the
   * loaded rows (plan 206). */
  const queueCount = (tab: TaxonomyTab): number => {
    if (!stats) return 0;
    if (tab === "relations") return stats.queue.relations;
    if (tab === "enrichment") return stats.queue.enrichment + stats.queue.job_proposals;
    if (tab === "paths") return stats.queue.paths;
    if (tab === "translations") return stats.queue.translations;
    return 0;
  };

  const skillTiles: StatTile[] = stats
    ? [
        {
          label: t("taxonomy.stats.active"),
          value: stats.skills.active,
          hint: t("taxonomy.stats.hint.active"),
        },
        {
          label: t("taxonomy.stats.proposed"),
          value: stats.skills.proposed,
          hint:
            stats.skills.promoted_7d > 0
              ? t("taxonomy.stats.hint.promoted", { count: stats.skills.promoted_7d })
              : t("taxonomy.stats.hint.awaiting"),
        },
        {
          label: t("taxonomy.stats.deprecated"),
          value: stats.skills.deprecated,
          hint: t("taxonomy.stats.hint.deprecated"),
        },
        {
          label: t("taxonomy.stats.autoPromoted"),
          value: stats.skills.auto_promoted,
          hint: t("taxonomy.stats.hint.allTime"),
        },
      ]
    : [];

  const queueTiles: StatTile[] = stats
    ? [
        { label: t("taxonomy.stats.relations"), value: stats.queue.relations },
        { label: t("taxonomy.stats.enrichment"), value: stats.queue.enrichment },
        { label: t("taxonomy.stats.jobProposals"), value: stats.queue.job_proposals },
        { label: t("taxonomy.stats.paths"), value: stats.queue.paths },
        { label: t("taxonomy.stats.translations"), value: stats.queue.translations },
      ]
    : [];

  const newTagButton = (
    <button
      onClick={() => setCreating((v) => !v)}
      className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5"
    >
      {creating ? t("common.cancel") : t("taxonomy.newTag")}
    </button>
  );

  const toolbarSlot = (
    <div className="flex items-center gap-2">
      {newTagButton}
      <SelectionEntry
        prefix="taxonomy"
        selection={selection}
        disabled={(kind === "skills" ? skills.length : tags.length) === 0}
      />
    </div>
  );

  const deleteHiddenNote =
    selection.hiddenCount > 0
      ? ` ${t("selection.hiddenConfirm", { count: selection.hiddenCount })}`
      : "";

  const skillActions = (
    <>
      <button
        onClick={() => void applyBulk("promote", promotableIds)}
        disabled={bulkBusy || promotableIds.length === 0}
        className="text-xs text-emerald-700 hover:text-emerald-600 disabled:opacity-40"
        data-testid="taxonomy-bulk-promote"
      >
        {t("taxonomy.promote")} ({promotableIds.length})
      </button>
      <button
        onClick={() => void applyBulk("deprecate", deprecatableIds)}
        disabled={bulkBusy || deprecatableIds.length === 0}
        className="text-xs text-slate-500 hover:text-primary-700 disabled:opacity-40"
        data-testid="taxonomy-bulk-deprecate"
      >
        {t("taxonomy.deprecate")} ({deprecatableIds.length})
      </button>
      <button
        onClick={() => void applyBulk("restore", restorableIds)}
        disabled={bulkBusy || restorableIds.length === 0}
        className="text-xs text-slate-500 hover:text-primary-700 disabled:opacity-40"
        data-testid="taxonomy-bulk-restore"
      >
        {t("taxonomy.restore")} ({restorableIds.length})
      </button>
      <span className="flex items-center gap-1">
        <span className="text-xs text-slate-500">
          {t("taxonomy.bulk.mergeLabel", { count: mergeableIds.length })}
        </span>
        <select
          value={bulkTarget}
          onChange={(e) => setBulkTarget(e.target.value)}
          className="text-xs border border-slate-200 rounded-lg px-2 py-1"
          data-testid="taxonomy-bulk-merge-target"
        >
          <option value="">{t("taxonomy.chooseActive")}</option>
          {mergeTargets.map((s) => (
            <option key={s.id} value={s.id}>
              {s.key}
            </option>
          ))}
        </select>
        <button
          onClick={() => void applyBulk("merge", mergeableIds)}
          disabled={bulkBusy || !bulkTarget || mergeableIds.length === 0}
          className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1 disabled:opacity-50"
          data-testid="taxonomy-bulk-merge"
        >
          {t("taxonomy.mergeConfirm")}
        </button>
      </span>
      <button
        onClick={() => setConfirmingDelete(true)}
        disabled={bulkBusy || selection.count === 0}
        className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
        data-testid="taxonomy-bulk-delete"
      >
        {t("taxonomy.delete")} ({selection.count})
      </button>
    </>
  );

  const interestActions = (
    <>
      <button
        onClick={() => void applyInterestBulk("deprecate", deprecatableInterestIds)}
        disabled={bulkBusy || deprecatableInterestIds.length === 0}
        className="text-xs text-slate-500 hover:text-primary-700 disabled:opacity-40"
        data-testid="taxonomy-bulk-deprecate"
      >
        {t("taxonomy.deprecate")} ({deprecatableInterestIds.length})
      </button>
      <button
        onClick={() => void applyInterestBulk("restore", restorableInterestIds)}
        disabled={bulkBusy || restorableInterestIds.length === 0}
        className="text-xs text-slate-500 hover:text-primary-700 disabled:opacity-40"
        data-testid="taxonomy-bulk-restore"
      >
        {t("taxonomy.restore")} ({restorableInterestIds.length})
      </button>
      <button
        onClick={() => setConfirmingDelete(true)}
        disabled={bulkBusy || selection.count === 0}
        className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
        data-testid="taxonomy-bulk-delete"
      >
        {t("taxonomy.delete")} ({selection.count})
      </button>
    </>
  );

  const detailsTag =
    details?.kind === "interests"
      ? (tags.find((item) => item.id === details.id) ?? null)
      : null;
  const detailsSkill =
    details?.kind === "skills"
      ? (skills.find((item) => item.id === details.id) ?? null)
      : null;

  return (
    <SettingsPage
      icon={Tags}
      title={t("settingsNav.taxonomy.label")}
      description={t("settingsNav.taxonomy.description")}
    >
      <div className="space-y-4" data-testid="settings-taxonomy">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Six labels don't fit a phone column: the strip keeps a
            phone-floor width and the wrapper scrolls it horizontally
            (the thumb math stays exact because the tablist keeps its
            width). */}
        <div className="min-w-0 overflow-x-auto">
          <SegmentedTabs
            ariaLabel={t("taxonomy.tabsAria")}
            className="min-w-[36rem] max-w-xl"
            items={TAXONOMY_TABS.map((k) => ({
              value: k,
              label: `${t(`taxonomy.kind.${k}`)}${queueCount(k) ? ` · ${queueCount(k)}` : ""}`,
              icon: TAB_ICONS[k],
            }))}
            value={kind}
            onValueChange={(next) => {
              const nextParams = new URLSearchParams(searchParams);
              if (next === "interests") nextParams.delete("tab");
              else nextParams.set("tab", next);
              nextParams.delete("section");
              setSearchParams(nextParams, { replace: true });
            }}
          />
        </div>
      </div>

      {stats && (
        <section className="space-y-2" data-testid="taxonomy-stats">
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {t("taxonomy.stats.skillsGroup", { total: stats.skills.total })}
            </p>
            <StatTiles tiles={skillTiles} layout="auto" testId="taxonomy-stats-skills" />
          </div>
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {t("taxonomy.stats.queueGroup", { total: stats.queue.total })}
            </p>
            <StatTiles tiles={queueTiles} layout="auto" testId="taxonomy-stats-queue" />
          </div>
        </section>
      )}

      {creating &&
        kind !== "paths" &&
        kind !== "enrichment" &&
        kind !== "translations" &&
        kind !== "relations" && (
          <div className="bg-white border border-slate-200 rounded-xl p-4 grid md:grid-cols-2 gap-2">
            <input
              placeholder={t("taxonomy.keyPlaceholder")}
              value={draft.key}
              onChange={(e) => setDraft({ ...draft, key: e.target.value })}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder={t("taxonomy.labelPlaceholder")}
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder={t("taxonomy.categoryPlaceholder")}
              value={draft.category}
              onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
            <input
              placeholder={t("taxonomy.descriptionPlaceholder")}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
            <button
              onClick={() => void onCreate()}
              disabled={!draft.key || !draft.label || !draft.category}
              className="md:col-span-2 bg-emerald-600 text-white rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("taxonomy.createTag")}
            </button>
          </div>
        )}

      {error && <p className="text-sm text-rose-600">{error}</p>}
      {note && <p className="text-xs text-amber-600">{note}</p>}
      {(bulkNote || bulkFailures.length > 0) && (
        <div data-testid="taxonomy-bulk-note">
          {bulkNote && <p className="text-xs text-emerald-700">{bulkNote}</p>}
          {bulkFailures.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-xs text-amber-600">
              {bulkFailures.map((failure) => (
                <li key={failure.id} data-testid={`taxonomy-bulk-failure-${failure.id}`}>
                  {failure.key ? `${failure.key} — ` : ""}
                  {failure.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {kind === "relations" ? (
        <SkillRelationsPanel
          section={section}
          onSectionChange={setSection}
          onOpenSkillPage={(key) => navigate(`/skills/${key}`)}
        />
      ) : kind === "translations" ? (
        <TranslationsBoard />
      ) : loading ||
        (kind === "enrichment" && enrichment.loading && enrichment.items.length === 0) ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">{t("common.loading")}</p>
        </div>
      ) : kind === "enrichment" ? (
        <div className="space-y-6">
          {enrichment.items.length === 0 && !enrichment.loadingMore ? (
            <EmptyState
              icon={Sparkles}
              title={t("taxonomy.noEnrichment", { defaultValue: "No enrichment proposals" })}
              description={t("taxonomy.noEnrichmentBody", { defaultValue: "AI-generated job enrichment proposals appear here for review." })}
            />
          ) : (
            <TaxonomyEnrichmentCards
              rows={enrichment.items}
              onModerate={moderateEnrichment}
              onBulkModerate={bulkModerateEnrichment}
            />
          )}
          {enrichment.cursor && (
            <div
              ref={enrichmentSentinelRef}
              className="h-px"
              data-testid="enrichment-load-more-sentinel"
            />
          )}
          {enrichment.loadingMore && (
            <div className="flex justify-center py-4" data-testid="enrichment-loading-more">
              <Spinner size="lg" label={t("taxonomy.enrich.loadingMore")} />
            </div>
          )}
          <section className="space-y-2" data-testid="job-proposals-section">
            <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {t("taxonomy.jobProposals.sectionTitle")}
            </h2>
            {legacyProposals > 0 ? (
              <div
                className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-muted)] p-2.5"
                data-testid="job-proposals-legacy-banner"
              >
                <p className="min-w-0 flex-1 text-xs text-[var(--as-fg)]">
                  {t("taxonomy.jobProposals.legacyBanner", { count: legacyProposals })}
                </p>
                <Button
                  size="sm"
                  onClick={() => void regenerateProposals()}
                  data-testid="job-proposals-regenerate"
                >
                  {t("taxonomy.jobProposals.legacyRegenerate")}
                </Button>
              </div>
            ) : null}
            {proposals.items.length === 0 ? (
              <p className="text-sm text-slate-400">{t("taxonomy.jobProposals.empty")}</p>
            ) : (
              <TaxonomyJobProposalCards
                rows={proposals.items}
                families={familyOptions}
                onDone={noteAfterModeration}
                onDecided={(id) => removeProposals([id])}
                onRefresh={refreshProposalQueue}
                onBulkDismiss={bulkDismissProposals}
              />
            )}
            {proposals.cursor && (
              <div
                ref={proposalsSentinelRef}
                className="h-px"
                data-testid="job-proposals-load-more-sentinel"
              />
            )}
            {proposals.loadingMore && (
              <div className="flex justify-center py-4" data-testid="job-proposals-loading-more">
                <Spinner size="lg" label={t("taxonomy.jobProposals.loadingMore")} />
              </div>
            )}
            {proposals.cursor && !proposals.loadingMore && (
              <button
                type="button"
                onClick={() => void proposals.loadMore()}
                className="w-full cursor-pointer rounded-xl border border-dashed border-[var(--as-border)] py-2 text-xs text-[var(--as-accent)] hover:bg-[var(--as-muted)] disabled:opacity-50"
                data-testid="job-proposals-load-more"
              >
                {t("taxonomy.jobProposals.loadMore", {
                  count:
                    proposals.total != null
                      ? Math.max(0, proposals.total - proposals.items.length)
                      : PROPOSAL_PAGE_SIZE,
                })}
              </button>
            )}
          </section>
          <TaxonomyCatalogHygieneCard onDone={noteAfterModeration} />
        </div>
      ) : kind === "paths" ? (
        paths.length === 0 ? (
          <EmptyState
            icon={Route}
            title={t("taxonomy.noDraftPaths")}
            description={t("taxonomy.noDraftPathsBody")}
          />
        ) : (
          <TaxonomyPathCards
            paths={paths}
            onModerate={moderatePath}
            onBulkModerate={bulkModeratePaths}
          />
        )
      ) : kind === "skills" ? (
        <TaxonomyList
          key="skills"
          rows={skills}
          toView={skillView}
          groups={SKILL_GROUPS}
          groupOf={skillGroupOf}
          iconOf={(skill) => categoryIcon(skill.category)}
          filters={SKILL_FILTERS}
          filter={skillFilter}
          onFilterChange={setSkillFilter}
          query={query}
          onQueryChange={setQuery}
          selectMode={selection.active}
          selected={selection.ids}
          onToggleSelect={(id, options) => selection.toggle(id, { range: options?.shift })}
          onSetGroupSelected={(ids, selected) => selection.setSelection(ids, selected)}
          onOpen={(skill) => setDetails({ kind: "skills", id: skill.id })}
          searchPlaceholder={t("taxonomy.searchPlaceholder")}
          toolbarSlot={toolbarSlot}
          selectionBar={
            <SelectionToolbar
              prefix="taxonomy"
              selection={selection}
              allIds={skillIds}
              matchingIds={skillMatchingIds}
              scopes={[
                {
                  key: "proposed",
                  label: t("selection.scopeNamed", {
                    count: proposed.length,
                    label: t("taxonomy.filter.proposed"),
                  }),
                  ids: proposed.map((s) => s.id),
                },
              ]}
              actions={skillActions}
              busy={bulkBusy}
              onShowHidden={() => {
                setQuery("");
                setSkillFilter("all");
              }}
            />
          }
          emptyIcon={Wrench}
          emptyTitle={t("taxonomy.noSkills")}
        />
      ) : (
        <TaxonomyList
          key="interests"
          rows={tags}
          toView={interestView}
          groups={INTEREST_GROUPS}
          groupOf={interestGroupOf}
          iconOf={(tag) => categoryIcon(tag.category)}
          filters={INTEREST_FILTERS}
          filter={interestFilter}
          onFilterChange={setInterestFilter}
          query={query}
          onQueryChange={setQuery}
          selectMode={selection.active}
          selected={selection.ids}
          onToggleSelect={(id, options) => selection.toggle(id, { range: options?.shift })}
          onSetGroupSelected={(ids, selected) => selection.setSelection(ids, selected)}
          onOpen={(tag) => setDetails({ kind: "interests", id: tag.id })}
          searchPlaceholder={t("taxonomy.searchPlaceholder")}
          toolbarSlot={toolbarSlot}
          selectionBar={
            <SelectionToolbar
              prefix="taxonomy"
              selection={selection}
              allIds={interestIds}
              matchingIds={interestMatchingIds}
              actions={interestActions}
              busy={bulkBusy}
              onShowHidden={() => {
                setQuery("");
                setInterestFilter("all");
              }}
            />
          }
          emptyIcon={Tags}
          emptyTitle={t("taxonomy.noTags")}
        />
      )}

      <ConfirmationModal
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        onConfirm={() => {
          setConfirmingDelete(false);
          if (kind === "skills") void applyBulk("delete", Array.from(selection.ids));
          else void applyInterestBulk("delete", Array.from(selection.ids));
        }}
        title={
          kind === "skills"
            ? t("taxonomy.bulk.deleteTitle", { count: selection.count })
            : t("taxonomy.bulk.deleteTitleInterests", { count: selection.count })
        }
        description={`${
          kind === "skills"
            ? t("taxonomy.bulk.deleteBody")
            : t("taxonomy.bulk.deleteBodyInterests")
        }${deleteHiddenNote}`}
        confirmLabel={t("taxonomy.delete")}
        destructive
      />

      {detailsTag ? (
        <InterestDetailsDrawer
          tag={detailsTag}
          onClose={() => setDetails(null)}
          onToggleDeprecated={(tag) => toggleInterestDeprecated(tag)}
          onDelete={(tag) => removeById("interests", tag.id)}
          onEdit={(tag, patch) => editInterest(tag, patch)}
        />
      ) : detailsSkill ? (
        <SkillDetailsDrawer
          skillKey={detailsSkill.key}
          mergeTargets={activeSkills}
          onClose={() => setDetails(null)}
          onPromote={() => promoteById(detailsSkill.id)}
          onSetStatus={(status) => setSkillStatus(detailsSkill, status)}
          onDelete={() => removeById("skills", detailsSkill.id)}
          onMerge={(targetId) => mergeById(detailsSkill.id, targetId)}
        />
      ) : null}
      </div>
    </SettingsPage>
  );
}
