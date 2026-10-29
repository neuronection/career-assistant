import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { EmptyState, SegmentedTabs, Spinner, ConfirmationModal } from "@/components/ui";
import { SkillRelationsPanel } from "@/components/settings/SkillRelationsPanel";
import { TranslationsPanel } from "@/components/settings/TranslationsPanel";
import { BulkBar, SelectionToggle } from "@/features/profile/components/profile/BulkTools";

interface PathRow {
  id: string;
  title: string;
  description: string;
  source: string;
  status: string;
  job_code: string | null;
  job_title: string | null;
  steps: { position: number; label: string; kind: string }[];
}

interface EnrichmentRow {
  id: string;
  code: string;
  title: string;
  proposal: Record<string, unknown> | null;
  proposed_at: string | null;
}

/** Admin taxonomy management: create, edit, promote/deprecate, merge, delete. */
export function Taxonomy() {
  const { t } = useTranslation();
  const [kind, setKind] = useState<"interests" | "skills" | "paths" | "enrichment" | "relations">(
    "interests",
  );
  const [tags, setTags] = useState<Tag[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [paths, setPaths] = useState<PathRow[]>([]);
  const [enrichment, setEnrichment] = useState<EnrichmentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ key: "", label: "", category: "", description: "" });
  const [merging, setMerging] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkTarget, setBulkTarget] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [bulkFailures, setBulkFailures] = useState<SkillBulkFailure[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

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

  const promote = async (skill: SkillRow) => {
    setError("");
    try {
      await promoteSkill(skill.id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const setStatus = async (tag: Tag | SkillRow, status: string) => {
    setError("");
    try {
      await updateTag(kind === "skills" ? "skills" : "interests", tag.id, { status } as never);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const doMerge = async (skill: SkillRow) => {
    setError("");
    try {
      await mergeSkill(skill.id, mergeTarget);
      setMerging(null);
      setMergeTarget("");
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const remove = async (tag: Tag | SkillRow) => {
    setError("");
    setNote("");
    try {
      await deleteTag(kind === "skills" ? "skills" : "interests", tag.id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
      setNote(t("taxonomy.referencedNote"));
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

  return (
    <div className="space-y-4" data-testid="settings-taxonomy">
      <TranslationsPanel />
      <div className="flex items-center justify-between">
        <SegmentedTabs
          ariaLabel={t("taxonomy.tabsAria")}
          className="max-w-lg"
          items={(["interests", "skills", "paths", "enrichment", "relations"] as const).map(
            (k) => ({
              value: k,
              label: t(`taxonomy.kind.${k}`),
            }),
          )}
          value={kind}
          onValueChange={(next) => {
            setKind(next as typeof kind);
            exitSelect();
            setBulkNote("");
            setBulkFailures([]);
          }}
        />
        {kind !== "paths" && kind !== "enrichment" && kind !== "relations" && (
          <div className="flex items-center gap-2">
            {kind === "skills" && selectMode && proposed.length > 0 && (
              <button
                onClick={() =>
                  setSelected(new Set(skills.filter((s) => s.status === "proposed").map((s) => s.id)))
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
            <button
              onClick={() => setCreating((v) => !v)}
              className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5"
            >
              {creating ? t("common.cancel") : t("taxonomy.newTag")}
            </button>
          </div>
        )}
      </div>

      {creating && kind !== "paths" && kind !== "enrichment" && kind !== "relations" && (
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
        <SkillRelationsPanel />
      ) : loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">{t("common.loading")}</p>
        </div>
      ) : kind === "enrichment" ? (
        enrichment.length === 0 ? (
          <EmptyState
            title={t("taxonomy.noEnrichment", { defaultValue: "No enrichment proposals" })}
            description={t("taxonomy.noEnrichmentBody", { defaultValue: "AI-generated job enrichment proposals appear here for review." })}
          />
        ) : (
          <div className="space-y-3" data-testid="enrichment-queue">
            {enrichment.map((row) => (
              <div
                key={row.id}
                className="bg-white border border-slate-200 rounded-xl p-4"
                data-testid={`enrichment-row-${row.id}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900">
                      {row.title} <span className="text-xs text-slate-400">({row.code})</span>
                    </p>
                    <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-[11px] text-slate-700">
                      {JSON.stringify(row.proposal, null, 2)}
                    </pre>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => void moderateEnrichment(row.id, "apply")}
                      className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs text-white"
                      data-testid={`enrichment-apply-${row.id}`}
                    >
                      {t("taxonomy.enrichmentApply", { defaultValue: "Apply" })}
                    </button>
                    <button
                      onClick={() => void moderateEnrichment(row.id, "reject")}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-600"
                      data-testid={`enrichment-reject-${row.id}`}
                    >
                      {t("taxonomy.enrichmentReject", { defaultValue: "Discard" })}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      ) : kind === "paths" ? (
        paths.length === 0 ? (
          <EmptyState
            title={t("taxonomy.noDraftPaths")}
            description={t("taxonomy.noDraftPathsBody")}
          />
        ) : (
          <div className="space-y-3">
            {paths.map((path) => (
              <div key={path.id} className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-sm">
                      {path.title}{" "}
                      <span className="text-slate-400">→ {path.job_title ?? path.job_code}</span>
                    </p>
                    <p className="text-xs text-slate-500">
                      {t("taxonomy.stepsCount", {
                        count: path.steps.length,
                        source: path.source,
                      })}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => void moderatePath(path.id, "publish")}
                      className="text-xs bg-emerald-600 text-white rounded-lg px-3 py-1.5"
                    >
                      {t("taxonomy.publish")}
                    </button>
                    <button
                      onClick={() => void moderatePath(path.id, "reject")}
                      className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 hover:text-rose-600"
                    >
                      {t("taxonomy.reject")}
                    </button>
                  </div>
                </div>
                <ol className="mt-2 space-y-0.5">
                  {path.steps.map((step) => (
                    <li key={step.position} className="text-xs text-slate-500">
                      {step.position + 1}. {step.label || step.kind}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
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
          {skills.length === 0 ? (
            <EmptyState title={t("taxonomy.noSkills")} />
          ) : (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  {selectMode && <th className="px-4 py-2 w-10"></th>}
                  <th className="px-4 py-2">{t("taxonomy.key")}</th>
                  <th className="px-4 py-2">{t("taxonomy.label")}</th>
                  <th className="px-4 py-2">{t("taxonomy.category")}</th>
                  <th className="px-4 py-2">{t("taxonomy.status")}</th>
                  {!selectMode && <th className="px-4 py-2"></th>}
                </tr>
              </thead>
              <tbody>
                {[...proposed, ...skills.filter((s) => s.status !== "proposed")].map((skill) => (
                  <tr key={skill.id} className="border-t border-slate-100">
                    {selectMode && (
                      <td className="px-4 py-2">
                        <SelectionToggle
                          selected={selected.has(skill.id)}
                          label={t("taxonomy.bulk.selectOne", { label: skill.label })}
                          onToggle={() => toggleSelected(skill.id)}
                        />
                      </td>
                    )}
                    <td className="px-4 py-2 font-mono text-xs">{skill.key}</td>
                    <td className="px-4 py-2">
                      {skill.label}
                      {skill.aliases.length > 0 && (
                        <span className="text-xs text-slate-400"> · {skill.aliases.join(", ")}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{skill.category}</td>
                    <td className="px-4 py-2">
                      {skill.status === "proposed" ? (
                        <span className="text-sky-600">{t("taxonomy.proposed")}</span>
                      ) : skill.status === "deprecated" ? (
                        <span className="text-amber-600">{t("taxonomy.deprecated")}</span>
                      ) : (
                        <span className="text-emerald-600">{t("taxonomy.active")}</span>
                      )}
                    </td>
                    {!selectMode && (
                      <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                        {skill.status === "proposed" && (
                          <button
                            onClick={() => void promote(skill)}
                            className="text-xs text-emerald-700 hover:text-emerald-600"
                          >
                            {t("taxonomy.promote")}
                          </button>
                        )}
                      {skill.status === "active" ? (
                        <button
                          onClick={() => void setStatus(skill, "deprecated")}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          {t("taxonomy.deprecate")}
                        </button>
                      ) : (
                        <button
                          onClick={() => void setStatus(skill, "active")}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          {t("taxonomy.restore")}
                        </button>
                      )}
                      {skill.status !== "active" && activeSkills.length > 0 && (
                        <button
                          onClick={() => setMerging(merging === skill.id ? null : skill.id)}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          {t("taxonomy.merge")}
                        </button>
                      )}
                      <button
                        onClick={() => void remove(skill)}
                        className="text-xs text-slate-400 hover:text-rose-600"
                      >
                        {t("taxonomy.delete")}
                      </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {merging && (
              <div className="border-t border-slate-100 bg-slate-50 p-3 flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  {t("taxonomy.mergeInto", {
                    key: skills.find((s) => s.id === merging)?.key ?? "",
                  })}
                </span>
                <select
                  value={mergeTarget}
                  onChange={(e) => setMergeTarget(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-2 py-1"
                >
                  <option value="">{t("taxonomy.chooseActive")}</option>
                  {activeSkills.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.key}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => {
                    const skill = skills.find((s) => s.id === merging);
                    if (skill && mergeTarget) void doMerge(skill);
                  }}
                  disabled={!mergeTarget}
                  className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1 disabled:opacity-50"
                >
                  {t("taxonomy.mergeConfirm")}
                </button>
                <button
                  onClick={() => setMerging(null)}
                  className="text-xs text-slate-400"
                >
                  {t("common.cancel")}
                </button>
              </div>
            )}
            </div>
          )}
        </>
      ) : tags.length === 0 ? (
        <EmptyState title={t("taxonomy.noTags")} />
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-2">{t("taxonomy.key")}</th>
                <th className="px-4 py-2">{t("taxonomy.label")}</th>
                <th className="px-4 py-2">{t("taxonomy.category")}</th>
                <th className="px-4 py-2">{t("taxonomy.status")}</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {tags.map((tag) => (
                <tr key={tag.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-mono text-xs">{tag.key}</td>
                  <td className="px-4 py-2">{tag.label}</td>
                  <td className="px-4 py-2 text-slate-500">{tag.category}</td>
                  <td className="px-4 py-2">
                    {tag.deprecated ? (
                      <span className="text-amber-600">{t("taxonomy.deprecated")}</span>
                    ) : (
                      <span className="text-emerald-600">{t("taxonomy.active")}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                    <button
                      onClick={() => {
                        void updateTag("interests", tag.id, {
                          deprecated: !tag.deprecated,
                        }).then(load);
                      }}
                      className="text-xs text-slate-500 hover:text-primary-700"
                    >
                      {tag.deprecated ? t("taxonomy.restore") : t("taxonomy.deprecate")}
                    </button>
                    <button
                      onClick={() => void remove(tag)}
                      className="text-xs text-slate-400 hover:text-rose-600"
                    >
                      {t("taxonomy.delete")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
    </div>
  );
}
