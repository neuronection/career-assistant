import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import { Languages, Network, Route, Sparkles, Tags, Wrench } from "lucide-react";
import {
  bulkSkillAction,
  createTag,
  deleteTag,
  fetchInterests,
  fetchSkillRows,
  mergeSkill,
  promoteSkill,
  updateTag,
  type SkillBulkAction,
  type SkillBulkFailure,
  type SkillRow,
  type Tag,
} from "@/api/taxonomy";
import { api } from "@/api/client";
import { apiDetail } from "@/api/client";
import {
  ConfirmationModal,
  EmptyState,
  SegmentedTabs,
  Spinner,
} from "@/components/ui";
import {
  InterestDetailsDrawer,
  SkillDetailsDrawer,
} from "@/components/settings/EntityDetailsDrawer";
import { TaxonomyList, type TaxonomyGroup } from "@/components/settings/TaxonomyList";
import {
  TaxonomyPathCards,
  type PathRow,
} from "@/components/settings/TaxonomyPathCards";
import {
  TaxonomyEnrichmentCards,
  type EnrichmentRow,
} from "@/components/settings/TaxonomyEnrichmentCards";
import { categoryIcon, STATUS_GROUP_ICONS } from "@/components/settings/taxonomyIcons";
import {
  parseRelationSection,
  SkillRelationsPanel,
  type RelationSection,
} from "@/components/settings/SkillRelationsPanel";
import { TranslationsBoard } from "@/components/settings/TranslationsBoard";
import { BulkBar } from "@/features/profile/components/profile/BulkTools";

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

/** Admin taxonomy management: create, edit, promote/deprecate, merge, delete. */
export function Taxonomy() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const kind = parseTaxonomyTab(searchParams.get("tab"));
  const section = parseRelationSection(searchParams.get("section"));
  const [tags, setTags] = useState<Tag[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [paths, setPaths] = useState<PathRow[]>([]);
  const [enrichment, setEnrichment] = useState<EnrichmentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ key: "", label: "", category: "", description: "" });
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkTarget, setBulkTarget] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkFailures, setBulkFailures] = useState<SkillBulkFailure[]>([]);
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

  useEffect(() => {
    setSelectMode(false);
    setSelected(new Set());
    setBulkTarget("");
    setBulkNote("");
    setBulkFailures([]);
  }, [kind]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (kind === "interests") {
        setTags(await fetchInterests());
      } else if (kind === "skills") {
        setSkills(await fetchSkillRows());
      } else if (kind === "enrichment") {
        const { data } = await api.get<EnrichmentRow[]>("/admin/jobs/enrichment");
        setEnrichment(data);
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
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const exitSelect = () => {
    setSelectMode(false);
    setSelected(new Set());
    setBulkTarget("");
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
    try {
      const result = await bulkSkillAction(
        ids,
        action,
        action === "merge" ? bulkTarget : undefined,
      );
      setSelected(new Set());
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

  const moderateEnrichment = async (id: string, action: "apply" | "reject") => {
    setError("");
    try {
      await api.post(`/admin/jobs/${id}/enrichment/${action}`);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const activeSkills = skills.filter((s) => s.status === "active");
  const proposed = skills.filter((s) => s.status === "proposed");
  const selectedSkills = skills.filter((s) => selected.has(s.id));
  const promotableIds = selectedSkills.filter((s) => s.status === "proposed").map((s) => s.id);
  const deprecatableIds = selectedSkills.filter((s) => s.status === "active").map((s) => s.id);
  const restorableIds = selectedSkills.filter((s) => s.status === "deprecated").map((s) => s.id);
  const mergeableIds = selectedSkills.filter((s) => s.status !== "active").map((s) => s.id);
  const mergeTargets = activeSkills.filter((s) => !selected.has(s.id));

  const newTagButton = (
    <button
      onClick={() => setCreating((v) => !v)}
      className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5"
    >
      {creating ? t("common.cancel") : t("taxonomy.newTag")}
    </button>
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
              label: t(`taxonomy.kind.${k}`),
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
        {kind !== "paths" &&
          kind !== "enrichment" &&
          kind !== "translations" &&
          kind !== "relations" && (
            <div className="flex items-center gap-2">
              {kind === "skills" && selectMode && proposed.length > 0 && (
                <button
                  onClick={() =>
                    setSelected(
                      new Set(skills.filter((s) => s.status === "proposed").map((s) => s.id)),
                    )
                  }
                  className="text-sm text-primary-700 rounded-lg px-3 py-1.5 border border-primary-200"
                  data-testid="taxonomy-select-proposed"
                >
                  {t("taxonomy.bulk.selectProposed", { count: proposed.length })}
                </button>
              )}
              {kind === "skills" && (
                <button
                  onClick={() => (selectMode ? exitSelect() : setSelectMode(true))}
                  className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 text-slate-600"
                  data-testid="taxonomy-select-toggle"
                >
                  {selectMode ? t("taxonomy.bulk.exit") : t("taxonomy.bulk.select")}
                </button>
              )}
            </div>
          )}
      </div>

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
      {bulkNote && (
        <div data-testid="taxonomy-bulk-note">
          <p className="text-xs text-emerald-700">{bulkNote}</p>
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
      ) : loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">{t("common.loading")}</p>
        </div>
      ) : kind === "enrichment" ? (
        enrichment.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title={t("taxonomy.noEnrichment", { defaultValue: "No enrichment proposals" })}
            description={t("taxonomy.noEnrichmentBody", { defaultValue: "AI-generated job enrichment proposals appear here for review." })}
          />
        ) : (
          <TaxonomyEnrichmentCards
            rows={enrichment}
            onModerate={moderateEnrichment}
          />
        )
      ) : kind === "paths" ? (
        paths.length === 0 ? (
          <EmptyState
            icon={Route}
            title={t("taxonomy.noDraftPaths")}
            description={t("taxonomy.noDraftPathsBody")}
          />
        ) : (
          <TaxonomyPathCards paths={paths} onModerate={moderatePath} />
        )
      ) : kind === "skills" ? (
        <>
          {selectMode && (
            <BulkBar
              count={selected.size}
              total={skills.length}
              onClear={() => setSelected(new Set())}
              onSelectAll={() => setSelected(new Set(skills.map((s) => s.id)))}
              testid="taxonomy-bulk-bar"
            >
              <button
                onClick={() => void applyBulk("promote", promotableIds)}
                disabled={promotableIds.length === 0}
                className="text-xs text-emerald-700 hover:text-emerald-600 disabled:opacity-40"
                data-testid="taxonomy-bulk-promote"
              >
                {t("taxonomy.promote")} ({promotableIds.length})
              </button>
              <button
                onClick={() => void applyBulk("deprecate", deprecatableIds)}
                disabled={deprecatableIds.length === 0}
                className="text-xs text-slate-500 hover:text-primary-700 disabled:opacity-40"
                data-testid="taxonomy-bulk-deprecate"
              >
                {t("taxonomy.deprecate")} ({deprecatableIds.length})
              </button>
              <button
                onClick={() => void applyBulk("restore", restorableIds)}
                disabled={restorableIds.length === 0}
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
                  disabled={!bulkTarget || mergeableIds.length === 0}
                  className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1 disabled:opacity-50"
                  data-testid="taxonomy-bulk-merge"
                >
                  {t("taxonomy.mergeConfirm")}
                </button>
              </span>
              <button
                onClick={() => setConfirmingDelete(true)}
                disabled={selected.size === 0}
                className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
                data-testid="taxonomy-bulk-delete"
              >
                {t("taxonomy.delete")} ({selected.size})
              </button>
            </BulkBar>
          )}
          <TaxonomyList
            key="skills"
            rows={skills}
            toView={(skill) => ({
              id: skill.id,
              key: skill.key,
              label: skill.label,
              category: skill.category,
              hint:
                skill.aliases.length > 0
                  ? skill.aliases.join(", ")
                  : skill.description || undefined,
              status: skill.status,
            })}
            groups={SKILL_GROUPS}
            groupOf={(skill) => skill.status}
            iconOf={(skill) => categoryIcon(skill.category)}
            filters={SKILL_FILTERS}
            filter={skillFilter}
            onFilterChange={setSkillFilter}
            selectMode={selectMode}
            selected={selected}
            onToggleSelect={toggleSelected}
            onOpen={(skill) => setDetails({ kind: "skills", id: skill.id })}
            searchPlaceholder={t("taxonomy.searchPlaceholder")}
            toolbarSlot={newTagButton}
            emptyIcon={Wrench}
            emptyTitle={t("taxonomy.noSkills")}
          />
        </>
      ) : (
        <TaxonomyList
          key="interests"
          rows={tags}
          toView={(tag) => ({
            id: tag.id,
            key: tag.key,
            label: tag.label,
            category: tag.category,
            hint: tag.description || undefined,
            status: tag.deprecated ? "deprecated" : "active",
          })}
          groups={INTEREST_GROUPS}
          groupOf={(tag) =>
            INTEREST_GROUPS.some((group) => group.key === tag.category)
              ? tag.category
              : "other"
          }
          iconOf={(tag) => categoryIcon(tag.category)}
          filters={INTEREST_FILTERS}
          filter={interestFilter}
          onFilterChange={setInterestFilter}
          onOpen={(tag) => setDetails({ kind: "interests", id: tag.id })}
          searchPlaceholder={t("taxonomy.searchPlaceholder")}
          toolbarSlot={newTagButton}
          emptyIcon={Tags}
          emptyTitle={t("taxonomy.noTags")}
        />
      )}

      <ConfirmationModal
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        onConfirm={() => {
          setConfirmingDelete(false);
          void applyBulk("delete", Array.from(selected));
        }}
        title={t("taxonomy.bulk.deleteTitle", { count: selected.size })}
        description={t("taxonomy.bulk.deleteBody")}
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
  );
}
