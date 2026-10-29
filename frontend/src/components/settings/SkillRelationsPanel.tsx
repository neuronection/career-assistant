/**
 * The skill-relations review surface (plan 138, step 6) — a Relations
 * segment inside the admin Taxonomy settings page. Queue grain is one row
 * per (pair, relation); proposed rows group by pair for adjudication
 * context. Every write goes through the admin API's single seam.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiDetail } from "@/api/client";
import {
  acceptSkillRelation,
  bulkSkillRelationAction,
  createSkillRelation,
  dismissSkillRelation,
  fetchSkillRelationRuns,
  fetchSkillRelationThresholds,
  fetchSkillRelations,
  removeSkillRelation,
  saveSkillRelationAlias,
  saveSkillRelationThresholds,
  type SkillRelationRow,
  type SkillRelationRun,
  type SkillRelationThresholds,
} from "@/api/skillRelations";
import { fetchSkillRows, type SkillRow } from "@/api/taxonomy";
import {
  Button,
  EmptyState,
  MultiSelectPicker,
  SegmentedTabs,
  Spinner,
  type PickerOption,
  type PickerSelection,
} from "@/components/ui";
import { ConceptGraphView } from "@/components/ui";
import {
  FormRow,
  NumberField,
  SelectField,
} from "@/features/cv/components/cv/formPrimitives";
import { BulkBar, SelectionToggle } from "@/features/profile/components/profile/BulkTools";

type Tab = "queue" | "editor" | "graph" | "thresholds" | "runs";
type RelationKind = SkillRelationRow["relation"];

const RELATIONS: RelationKind[] = ["is_a", "synonym", "part_of", "related_to"];

const NODE_COLORS: Record<string, string> = {
  active: "#059669",
  deprecated: "#d97706",
};

const EDGE_COLORS: Record<string, string> = {
  is_a: "#2563eb",
  synonym: "#059669",
  part_of: "#7c3aed",
  related_to: "#64748b",
};

/** Container-style relations: the parent/container ranks above in the
 * hierarchy layout (an is_a child sits under its parent). */
const REVERSED_RELATIONS = ["is_a", "part_of"];
const LEDGER_KEYS: (keyof SkillRelationRun["ledger"])[] = [
  "candidates",
  "batches",
  "judged_batches",
  "failed_batches",
  "uncovered",
  "derived",
  "edges_proposed",
  "negatives",
  "dropped",
  "below_bar",
  "materialized",
  "backfilled",
  "capped",
  "watermark",
];

function pairKey(row: SkillRelationRow): string {
  return [row.from_skill.id, row.to_skill.id].sort().join(":");
}

const normalizeLabel = (label: string) =>
  label
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .replace(/[^a-z0-9+ ]/g, " ")
    .trim();

/** Could the proposed label plausibly be a raw-label duplicate of the other
 *  skill (alias-shaped)? Equal, prefix, initialism, or token subset —
 *  precision over recall: the queue noise was the problem, not missed
 *  hints. ("frontier models" vs "AI agents" → distinct concepts.) */
function isAliasishLabel(a: string, b: string): boolean {
  const na = normalizeLabel(a);
  const nb = normalizeLabel(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  const [short, long] = na.length <= nb.length ? [na, nb] : [nb, na];
  if (short.length >= 2 && long.startsWith(short)) return true;
  const shortTokens = short.split(/\s+/);
  const longTokens = long.split(/\s+/);
  if (shortTokens.length > 1 && shortTokens.every((token) => longTokens.includes(token))) {
    return true;
  }
  const initials = longTokens.map((token) => token[0]).join("");
  return shortTokens.length === 1 && short === initials && initials.length >= 2;
}

function RelationRowCard({
  row,
  note,
  busy,
  selectSlot,
  onAccept,
  onDismiss,
  onAlias,
  onRemove,
}: {
  row: SkillRelationRow;
  note?: string;
  busy: boolean;
  selectSlot?: React.ReactNode;
  onAccept: () => void;
  onDismiss: () => void;
  onAlias: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const rationale =
    row.evidence && typeof row.evidence.rationale === "string"
      ? (row.evidence.rationale as string)
      : null;
  return (
    <div
      className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid={`relation-row-${row.id}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm text-[var(--as-fg)]">
          {selectSlot}
          <span className="font-medium">{row.from_skill.label}</span>{" "}
          <span className="text-[var(--as-muted-fg)]">
            {t(`taxonomy.relations.relation.${row.relation}`)}
          </span>{" "}
          <span className="font-medium">{row.to_skill.label}</span>
        </p>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--as-muted-fg)]">
          <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5">
            {t(`taxonomy.relations.source.${row.source}`)}
          </span>
          <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5">
            {t(`taxonomy.relations.status.${row.status}`)}
          </span>
          {row.confidence !== null && (
            <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5">{row.confidence}</span>
          )}
        </div>
      </div>
      {rationale && (
        <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
          {t("taxonomy.relations.evidence")}: {rationale}
        </p>
      )}
      {row.alias_candidate && isAliasishLabel(row.from_skill.label, row.to_skill.label) && (
        <p className="mt-1 text-xs text-amber-700">{t("taxonomy.relations.aliasHint")}</p>
      )}
      {(row.from_skill.status === "proposed" || row.to_skill.status === "proposed") &&
        !isAliasishLabel(row.from_skill.label, row.to_skill.label) && (
          <p className="mt-1 text-xs text-amber-700">
            {t("taxonomy.relations.promotionHint")}
          </p>
        )}
      <div className="mt-2 flex flex-wrap gap-2">
        {row.status === "proposed" && (
          <Button
            size="sm"
            onClick={onAccept}
            disabled={busy}
            data-testid={`relation-accept-${row.id}`}
          >
            {t("taxonomy.relations.accept")}
          </Button>
        )}
        {row.status !== "rejected" && (
          <Button
            size="sm"
            variant="outline"
            onClick={onDismiss}
            disabled={busy}
            data-testid={`relation-dismiss-${row.id}`}
          >
            {t("taxonomy.relations.dismiss")}
          </Button>
        )}
        {row.alias_candidate && row.status !== "approved" && (
          <Button
            size="sm"
            variant="secondary"
            onClick={onAlias}
            disabled={busy}
            data-testid={`relation-alias-${row.id}`}
          >
            {t("taxonomy.relations.saveAlias")}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={onRemove}
          disabled={busy}
          data-testid={`relation-remove-${row.id}`}
        >
          {t("taxonomy.relations.remove")}
        </Button>
      </div>
      {note && <p className="mt-1 text-xs text-[var(--as-muted-fg)]">{note}</p>}
    </div>
  );
}

export function SkillRelationsPanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("queue");
  const [rows, setRows] = useState<SkillRelationRow[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<{
    from: PickerSelection[];
    to: PickerSelection[];
    relation: RelationKind;
    confidence: number | null;
  }>({ from: [], to: [], relation: "is_a", confidence: null });
  const [thresholds, setThresholds] = useState<SkillRelationThresholds | null>(null);
  const [thresholdNote, setThresholdNote] = useState("");
  const [globalNote, setGlobalNote] = useState("");
  const [runs, setRuns] = useState<SkillRelationRun[]>([]);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkFailures, setBulkFailures] = useState<
    { id: string; key: string; reason: string }[]
  >([]);

  const options = useMemo<PickerOption[]>(
    () =>
      skills.map((skill) => ({
        value: skill.key,
        label: skill.label,
        category: skill.category,
      })),
    [skills],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [listed, skillRows] = await Promise.all([
        fetchSkillRelations(),
        fetchSkillRows(),
      ]);
      setRows(listed);
      setSkills(skillRows);
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runAction = useCallback(
    async (row: SkillRelationRow, action: () => Promise<unknown>, note: string) => {
      setBusyId(row.id);
      setError("");
      try {
        await action();
        if (note) {
          setNotes((prev) => ({ ...prev, [row.id]: note }));
        }
        await load();
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  const aliasAction = useCallback(
    async (row: SkillRelationRow) => {
      setBusyId(row.id);
      setError("");
      try {
        const saved = await saveSkillRelationAlias(row.id);
        setGlobalNote(t("taxonomy.relations.aliasSaved", { target: saved.target.label }));
        await load();
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setBusyId(null);
      }
    },
    [load, t],
  );

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

  const applyBulk = useCallback(
    async (action: "accept" | "dismiss") => {
      const ids = Array.from(selected);
      if (ids.length === 0) return;
      setError("");
      setGlobalNote("");
      setBulkFailures([]);
      try {
        const result = await bulkSkillRelationAction(ids, action);
        setSelected(new Set());
        if (result.affected.length > 0) {
          setGlobalNote(t("taxonomy.relations.bulk.done", { count: result.affected.length }));
        }
        setBulkFailures(result.failed);
        await load();
      } catch (err) {
        setError(apiDetail(err));
      }
    },
    [selected, load, t],
  );

  const onAdd = async () => {
    const from = draft.from[0]?.value;
    const to = draft.to[0]?.value;
    if (!from || !to) return;
    setError("");
    try {
      await createSkillRelation({
        from_skill: from,
        to_skill: to,
        relation: draft.relation,
        confidence: draft.confidence,
      });
      setDraft({ from: [], to: [], relation: "is_a", confidence: null });
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const loadThresholds = useCallback(async () => {
    try {
      setThresholds(await fetchSkillRelationThresholds());
    } catch (err) {
      setError(apiDetail(err));
    }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      setRuns(await fetchSkillRelationRuns());
    } catch (err) {
      setError(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    if (tab === "thresholds" && thresholds === null) void loadThresholds();
    if (tab === "runs") void loadRuns();
  }, [tab, thresholds, loadThresholds, loadRuns]);

  const onThresholdsSave = async () => {
    if (!thresholds) return;
    setThresholdNote("");
    try {
      setThresholds(await saveSkillRelationThresholds(thresholds));
      setThresholdNote(t("taxonomy.relations.thresholds.saved"));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const proposed = rows.filter((row) => row.status === "proposed");
  const groups = useMemo(() => {
    const map = new Map<string, SkillRelationRow[]>();
    for (const row of proposed) {
      const key = pairKey(row);
      map.set(key, [...(map.get(key) ?? []), row]);
    }
    return [...map.entries()];
  }, [proposed]);

  const [graphNodeId, setGraphNodeId] = useState<string | undefined>();

  const graph = useMemo(() => {
    // The reviewed taxonomy only: proposed skills (extraction labels awaiting
    // review) would flood the canvas — one real run had 605 of them against
    // 57 active skills, spreading the force layout over ~24k px.
    const reviewed = skills.filter((skill) => skill.status !== "proposed");
    const reviewedIds = new Set(reviewed.map((skill) => skill.id));
    const approved = rows.filter((row) => row.status === "approved");
    const pair = (a: string, b: string) => [a, b].sort().join(":");
    const isAPairs = new Set(
      approved
        .filter((row) => row.relation === "is_a")
        .map((row) => pair(row.from_skill.id, row.to_skill.id)),
    );
    const parentEdges = reviewed
      .filter((skill) => skill.parent_id && reviewedIds.has(skill.parent_id))
      .filter((skill) => !isAPairs.has(pair(skill.id, skill.parent_id as string)))
      .map((skill) => ({
        id: `parent:${skill.id}`,
        source: skill.id,
        target: skill.parent_id as string,
        relation: "is_a",
      }));
    return {
      nodes: reviewed.map((skill) => ({
        id: skill.id,
        name: skill.label,
        primary_kind: skill.status,
        type: "skill",
      })),
      edges: [
        ...approved
          .filter((row) => reviewedIds.has(row.from_skill.id) && reviewedIds.has(row.to_skill.id))
          .map((row) => ({
            id: row.id,
            source: row.from_skill.id,
            target: row.to_skill.id,
            relation: row.relation,
          })),
        ...parentEdges,
      ],
    };
  }, [rows, skills]);

  return (
    <div className="space-y-4" data-testid="skill-relations-panel">
      <p className="text-sm text-[var(--as-muted-fg)]">{t("taxonomy.relations.intro")}</p>
      <SegmentedTabs
        ariaLabel={t("taxonomy.relations.tabsAria")}
        className="max-w-xl"
        items={(["queue", "editor", "graph", "thresholds", "runs"] as const).map((k) => ({
          value: k,
          label: t(`taxonomy.relations.tab.${k}`),
        }))}
        value={tab}
        onValueChange={(next) => setTab(next as Tab)}
      />
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {globalNote && <p className="text-sm text-emerald-700">{globalNote}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-16">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        </div>
      ) : tab === "queue" ? (
        <>
          {groups.length > 0 && (
            <div className="flex items-center justify-end">
              <button
                onClick={() => {
                  if (selectMode) setSelected(new Set());
                  setSelectMode((v) => !v);
                }}
                className="rounded-lg border border-[var(--as-border)] px-3 py-1.5 text-sm text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                data-testid="relation-select-toggle"
              >
                {selectMode ? t("taxonomy.bulk.exit") : t("taxonomy.relations.bulk.select")}
              </button>
            </div>
          )}
          {selectMode && (
            <BulkBar
              count={selected.size}
              total={proposed.length}
              onClear={() => setSelected(new Set())}
              onSelectAll={() => setSelected(new Set(proposed.map((row) => row.id)))}
              testid="relation-bulk-bar"
            >
              <Button
                variant="outline"
                size="sm"
                disabled={selected.size === 0}
                onClick={() => void applyBulk("accept")}
                data-testid="relation-bulk-accept"
              >
                {t("taxonomy.relations.accept")} ({selected.size})
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={selected.size === 0}
                onClick={() => void applyBulk("dismiss")}
                data-testid="relation-bulk-dismiss"
              >
                {t("taxonomy.relations.dismiss")} ({selected.size})
              </Button>
            </BulkBar>
          )}
          {bulkFailures.length > 0 && (
            <ul
              className="list-disc pl-4 text-xs text-amber-600"
              data-testid="relation-bulk-failures"
            >
              {bulkFailures.map((failure) => (
                <li key={failure.id}>
                  {failure.key ? `${failure.key} — ` : ""}
                  {failure.reason}
                </li>
              ))}
            </ul>
          )}
          {groups.length === 0 ? (
            <EmptyState
              title={t("taxonomy.relations.queue.empty")}
              description={t("taxonomy.relations.queue.emptyBody")}
            />
          ) : (
            <div className="space-y-3" data-testid="skill-relations-queue">
              {groups.map(([key, group]) => (
                <div key={key} className="space-y-2" data-testid={`relation-pair-${key}`}>
                  {group.length > 1 && (
                    <p className="text-xs font-medium text-[var(--as-muted-fg)]">
                      {group[0].from_skill.label} · {group[0].to_skill.label}
                    </p>
                  )}
                  {group.map((row) => (
                    <RelationRowCard
                      key={row.id}
                      row={row}
                      note={notes[row.id]}
                      busy={busyId === row.id || selectMode}
                      selectSlot={
                        selectMode ? (
                          <SelectionToggle
                            selected={selected.has(row.id)}
                            label={t("taxonomy.relations.bulk.selectOne", {
                              label: `${row.from_skill.label} → ${row.to_skill.label}`,
                            })}
                            onToggle={() => toggleSelected(row.id)}
                          />
                        ) : undefined
                      }
                      onAccept={() =>
                        void runAction(
                          row,
                          () => acceptSkillRelation(row.id),
                          t("taxonomy.relations.accepted"),
                        )
                      }
                      onDismiss={() =>
                        void runAction(
                          row,
                          () => dismissSkillRelation(row.id),
                          t("taxonomy.relations.dismissed"),
                        )
                      }
                      onAlias={() => void aliasAction(row)}
                      onRemove={() =>
                        void runAction(row, () => removeSkillRelation(row.id), "")
                      }
                    />
                  ))}
                </div>
              ))}
            </div>
          )}
        </>
      ) : tab === "editor" ? (
        <div className="space-y-4" data-testid="skill-relations-editor">
          <div
            className="space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
            data-testid="relation-add-form"
          >
            <p className="text-sm font-medium text-[var(--as-fg)]">
              {t("taxonomy.relations.addHeading")}
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              <FormRow label={t("taxonomy.relations.fromLabel")}>
                <MultiSelectPicker
                  mode="single"
                  options={options}
                  value={draft.from}
                  onChange={(next) => setDraft({ ...draft, from: next.slice(-1) })}
                  placeholder={t("filters.skillsPlaceholder")}
                  labels={{
                    browseLabel: t("filters.browseCatalog"),
                    browseTitle: t("filters.browseCatalog"),
                    searchPlaceholder: t("filters.searchSkills"),
                    categoryLabel: t("filters.category"),
                    allCategoriesLabel: t("filters.allCategories"),
                    emptyLabel: t("filters.noSkillsFound"),
                    addLabel: t("filters.add"),
                    addedLabel: t("filters.added"),
                    loadMoreLabel: t("filters.loadMore"),
                    doneLabel: t("filters.done"),
                    removeLabel: t("common.remove"),
                  }}
                />
              </FormRow>
              <FormRow label={t("taxonomy.relations.toLabel")}>
                <MultiSelectPicker
                  mode="single"
                  options={options}
                  value={draft.to}
                  onChange={(next) => setDraft({ ...draft, to: next.slice(-1) })}
                  placeholder={t("filters.skillsPlaceholder")}
                  labels={{
                    browseLabel: t("filters.browseCatalog"),
                    browseTitle: t("filters.browseCatalog"),
                    searchPlaceholder: t("filters.searchSkills"),
                    categoryLabel: t("filters.category"),
                    allCategoriesLabel: t("filters.allCategories"),
                    emptyLabel: t("filters.noSkillsFound"),
                    addLabel: t("filters.add"),
                    addedLabel: t("filters.added"),
                    loadMoreLabel: t("filters.loadMore"),
                    doneLabel: t("filters.done"),
                    removeLabel: t("common.remove"),
                  }}
                />
              </FormRow>
              <SelectField
                label={t("taxonomy.relations.relationLabel")}
                value={draft.relation}
                onChange={(next) => setDraft({ ...draft, relation: next as RelationKind })}
                options={RELATIONS.map((kind) => ({
                  value: kind,
                  label: t(`taxonomy.relations.relation.${kind}`),
                }))}
                testId="relation-kind-select"
              />
              <NumberField
                label={t("taxonomy.relations.confidenceLabel")}
                value={draft.confidence}
                onChange={(value) => setDraft({ ...draft, confidence: value })}
                min={0}
                max={1}
                testId="relation-confidence-input"
              />
            </div>
            <Button
              size="sm"
              onClick={() => void onAdd()}
              disabled={draft.from.length === 0 || draft.to.length === 0}
              data-testid="relation-add-submit"
            >
              {t("taxonomy.relations.add")}
            </Button>
          </div>
          {rows.length === 0 ? (
            <EmptyState
              title={t("taxonomy.relations.editor.empty")}
              description={t("taxonomy.relations.editor.emptyBody")}
            />
          ) : (
            <div className="space-y-2">
              {rows.map((row) => (
                <RelationRowCard
                  key={row.id}
                  row={row}
                  note={notes[row.id]}
                  busy={busyId === row.id}
                  onAccept={() =>
                    void runAction(
                      row,
                      () => acceptSkillRelation(row.id),
                      t("taxonomy.relations.accepted"),
                    )
                  }
                  onDismiss={() =>
                    void runAction(
                      row,
                      () => dismissSkillRelation(row.id),
                      t("taxonomy.relations.dismissed"),
                    )
                  }
                  onAlias={() => void aliasAction(row)}
                  onRemove={() => void runAction(row, () => removeSkillRelation(row.id), "")}
                />
              ))}
            </div>
          )}
        </div>
      ) : tab === "graph" ? (
        <div
          data-testid="skill-relations-graph"
          className="h-[480px] overflow-hidden rounded-xl border border-[var(--as-border)]"
        >
          <ConceptGraphView
            nodes={graph.nodes}
            edges={graph.edges}
            kindColors={NODE_COLORS}
            relationColors={EDGE_COLORS}
            hierarchyReversedRelations={REVERSED_RELATIONS}
            selectedNodeId={graphNodeId}
            onSelectNode={setGraphNodeId}
            onClearSelection={() => setGraphNodeId(undefined)}
            labels={{
              empty: t("taxonomy.relations.graph.empty"),
              findPlaceholder: t("taxonomy.relations.graph.find"),
            }}
            renderNodeDetail={({ node, degree, onClose, onFocus }) => {
              const skill = skills.find((entry) => entry.id === node.id);
              return (
                <div className="w-52 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-left shadow-md">
                  <p className="text-sm font-medium text-[var(--as-fg)]">{node.name}</p>
                  <p className="font-mono text-[11px] text-[var(--as-muted-fg)]">{skill?.key}</p>
                  {skill && (
                    <p className="mt-1 text-xs capitalize text-[var(--as-muted-fg)]">
                      {skill.category} · {t(`taxonomy.${skill.status}`)}
                    </p>
                  )}
                  <p className="text-xs text-[var(--as-muted-fg)]">
                    {t("taxonomy.relations.graph.degree", { count: degree })}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="outline" onClick={onFocus}>
                      {t("taxonomy.relations.graph.focus")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={onClose}>
                      {t("common.close")}
                    </Button>
                  </div>
                </div>
              );
            }}
          />
        </div>
      ) : tab === "thresholds" ? (
        thresholds === null ? (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : (
          <div
            className="max-w-xl space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
            data-testid="skill-relations-thresholds"
          >
            <NumberField
              label={t("taxonomy.relations.thresholds.minSupport")}
              value={thresholds.min_support}
              min={1}
              onChange={(value) =>
                setThresholds({ ...thresholds, min_support: value ?? 1 })
              }
              testId="threshold-min_support"
            />
            <NumberField
              label={t("taxonomy.relations.thresholds.batchSize")}
              value={thresholds.batch_size}
              min={1}
              max={40}
              onChange={(value) =>
                setThresholds({ ...thresholds, batch_size: value ?? 1 })
              }
              testId="threshold-batch_size"
            />
            <NumberField
              label={t("taxonomy.relations.thresholds.maxPairs")}
              value={thresholds.max_pairs_per_run}
              min={1}
              onChange={(value) =>
                setThresholds({ ...thresholds, max_pairs_per_run: value ?? 1 })
              }
              testId="threshold-max_pairs_per_run"
            />
            <NumberField
              label={t("taxonomy.relations.thresholds.minNegative")}
              value={thresholds.min_negative_confidence}
              min={0}
              max={1}
              onChange={(value) =>
                setThresholds({ ...thresholds, min_negative_confidence: value ?? 0 })
              }
              testId="threshold-min_negative_confidence"
            />
            <div className="flex items-center gap-3">
              <Button
                size="sm"
                onClick={() => void onThresholdsSave()}
                data-testid="thresholds-save"
              >
                {t("taxonomy.relations.thresholds.save")}
              </Button>
              {thresholdNote && <p className="text-xs text-emerald-700">{thresholdNote}</p>}
            </div>
          </div>
        )
      ) : runs.length === 0 ? (
        <EmptyState
          title={t("taxonomy.relations.runs.empty")}
          description={t("taxonomy.relations.runs.emptyBody")}
        />
      ) : (
        <div className="space-y-2" data-testid="skill-relations-runs">
          {runs.map((run) => (
            <div
              key={run.id}
              className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid={`run-row-${run.id}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-[var(--as-muted-fg)]">
                  {new Date(run.created_at).toLocaleString()}
                </p>
                <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5 text-[11px] text-[var(--as-muted-fg)]">
                  {run.status}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-[var(--as-muted-fg)]">
                {LEDGER_KEYS.map((key) => (
                  <span
                    key={key}
                    className="rounded bg-[var(--as-muted)] px-1.5 py-0.5"
                    data-testid={`run-ledger-${key}`}
                  >
                    {t(`taxonomy.relations.ledger.${key}`)}:{" "}
                    {key === "watermark" ? (
                      <span data-testid={`run-watermark-${run.id}`}>
                        {run.ledger.watermark === null
                          ? t("taxonomy.relations.runs.heldWatermark")
                          : run.ledger.watermark}
                      </span>
                    ) : (
                      String(run.ledger[key])
                    )}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
