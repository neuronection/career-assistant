import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowDownCircle,
  ArrowLeft,
  ArrowUpCircle,
  GitMerge,
  Pencil,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import {
  fetchMySkills,
  fetchSkill,
  fetchSkillHistory,
  fetchSkillOntology,
  fetchSkillPositions,
  fetchSkillRelations,
  saveMySkills,
} from "@/api/skills";
import { deleteTag, mergeSkill, promoteSkill, updateTag } from "@/api/taxonomy";
import { apiDetail } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { Badge, Button, ConfirmationModal, EmptyState, SegmentedTabs, Spinner } from "@/components/ui";
import { ConceptGraphView, type ConceptGraphNode } from "@/components/ui/conceptGraph";
import { PostingCard } from "@/features/postings/components/PostingCard";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import { NODE_COLORS, REVERSED_RELATIONS, EDGE_COLORS } from "@/features/skills/graphColors";
import { formatAbsolute } from "@/lib/time";
import type {
  PostingOut,
  SkillChange,
  SkillDetail,
  SkillHistoryResponse,
  SkillRelationsResponse,
} from "@/types/wire";

export type SkillTab = "overview" | "positions" | "graph" | "history";

/** Fully-defaulted view shapes over the generated wire types (the
 * contract marks defaulted arrays optional) — normalized once per fetch. */
export interface SkillStatsView {
  demand_count: number;
  level_histogram: { level: number; n: number }[];
  avg_required_level: number | null;
  user_count: number;
  first_seen: string | null;
  last_seen: string | null;
  corroboration: { postings: number } | null;
}

export interface SkillView {
  id: string;
  key: string;
  label: string;
  category: string;
  description: string;
  parent_id: string | null;
  parent_key: string | null;
  level_anchors: { level: number; label: string; description: string }[];
  aliases: string[];
  status: string;
  children_keys: string[];
  jobs: { required_level: number | null; importance: string }[];
  stats: SkillStatsView | null;
  merged_into: string | null;
  origin: string;
}

export interface SkillRelationsView {
  nodes: { id: string; key: string; label: string; status: string }[];
  edges: { id: string; source: string; target: string; relation: string }[];
}

export interface SkillPositionsView {
  items: PostingOut[];
  total: number;
}

function toView(detail: SkillDetail): SkillView {
  const stats = detail.stats;
  return {
    id: detail.id,
    key: detail.key,
    label: detail.label,
    category: detail.category,
    description: detail.description,
    parent_id: detail.parent_id ?? null,
    parent_key: detail.parent_key ?? null,
    level_anchors: (detail.level_anchors ?? []).map((anchor) => ({
      level: Number(anchor.level),
      label: String(anchor.label ?? ""),
      description: String(anchor.description ?? ""),
    })),
    aliases: detail.aliases ?? [],
    status: detail.status,
    children_keys: detail.children_keys ?? [],
    jobs: (detail.jobs ?? []).map((job) => ({
      required_level: job.required_level ?? null,
      importance: job.importance,
    })),
    stats: stats
      ? {
          demand_count: stats.demand_count ?? 0,
          level_histogram: (stats.level_histogram ?? []).map((bucket) => ({
            level: Number(bucket.level),
            n: Number(bucket.n),
          })),
          avg_required_level: stats.avg_required_level ?? null,
          user_count: stats.user_count ?? 0,
          first_seen: stats.first_seen ?? null,
          last_seen: stats.last_seen ?? null,
          corroboration: stats.corroboration
            ? { postings: Number(stats.corroboration.postings) }
            : null,
        }
      : null,
    merged_into: detail.merged_into ?? null,
    origin: detail.origin ?? "bank",
  };
}

function toRelationsView(response: SkillRelationsResponse): SkillRelationsView {
  return {
    nodes: (response.nodes ?? []).map((node) => ({
      id: node.id,
      key: node.key,
      label: node.label,
      status: node.status,
    })),
    edges: (response.edges ?? []).map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      relation: edge.relation,
    })),
  };
}

const EVENT_ICON: Record<string, LucideIcon> = {
  created: Plus,
  updated: Pencil,
  promoted: ArrowUpCircle,
  auto_promoted: Sparkles,
  deprecated: ArrowDownCircle,
  restored: RotateCcw,
  merged: GitMerge,
  deleted: Trash2,
};

/** `?tab=` → tab, unknown → default (the repo-wide derived-state pattern). */
export function skillTabFromParam(raw: string | null | undefined): SkillTab {
  return raw === "positions" || raw === "graph" || raw === "history" ? raw : "overview";
}

const POSITIONS_PAGE = 20;

export function SkillPage() {
  const { key = "" } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const tab = skillTabFromParam(searchParams.get("tab"));

  const [detail, setDetail] = useState<SkillView | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState("");
  const [relations, setRelations] = useState<SkillRelationsView | null>(null);
  const [positions, setPositions] = useState<SkillPositionsView | null>(null);
  const [positionsLimit, setPositionsLimit] = useState(POSITIONS_PAGE);
  const [history, setHistory] = useState<SkillHistoryResponse | null>(null);
  const [mySkills, setMySkills] = useState<Awaited<ReturnType<typeof fetchMySkills>>>([]);
  const [myLevel, setMyLevel] = useState(5);
  const [savingLevel, setSavingLevel] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [merging, setMerging] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState({ label: "", category: "", description: "" });
  const [activeSkills, setActiveSkills] = useState<{ id: string; key: string }[]>([]);
  const [actionNote, setActionNote] = useState("");

  const setTab = (next: string) => {
    setSearchParams(
      (current) => {
        const params = new URLSearchParams(current);
        if (next === "overview") params.delete("tab");
        else params.set("tab", next);
        return params;
      },
      { replace: true },
    );
  };

  const load = useCallback(() => {
    void fetchSkill(key)
      .then((skill) => {
        const view = toView(skill);
        setDetail(view);
        setEditDraft({
          label: view.label,
          category: view.category,
          description: view.description,
        });
      })
      .catch((err) => {
        const message = apiDetail(err);
        if (message.includes("404") || message.toLowerCase().includes("not found")) {
          setNotFound(true);
        } else {
          setError(message);
        }
      });
    void fetchSkillRelations(key)
      .then((response) => setRelations(toRelationsView(response)))
      .catch(() => setRelations({ nodes: [], edges: [] }));
    void fetchMySkills()
      .then(setMySkills)
      .catch(() => setMySkills([]));
  }, [key]);

  useEffect(() => {
    setDetail(null);
    setNotFound(false);
    setError("");
    setRelations(null);
    setPositions(null);
    setPositionsLimit(POSITIONS_PAGE);
    setHistory(null);
    setActionNote("");
    load();
  }, [load]);

  const loadPositions = useCallback(
    (limit: number) => {
      void fetchSkillPositions(key, { limit })
        .then((response) =>
          setPositions({
            items: response.items ?? [],
            total: response.total ?? 0,
          }),
        )
        .catch(() => setPositions({ items: [], total: 0 }));
    },
    [key],
  );

  const loadHistory = useCallback(() => {
    void fetchSkillHistory(key)
      .then(setHistory)
      .catch(() => setHistory(null));
  }, [key]);

  useEffect(() => {
    if (!detail) return;
    if (tab === "positions" && positions === null) loadPositions(positionsLimit);
    if (tab === "history" && history === null) loadHistory();
  }, [tab, detail, positions, history, loadPositions, loadHistory]);

  const mine = useMemo(
    () => mySkills.find((row) => row.key === key && !row.hidden) ?? null,
    [mySkills, key],
  );

  const graphNodes: ConceptGraphNode[] = useMemo(
    () =>
      (relations?.nodes ?? []).map((node) => ({
        id: node.id,
        name: node.label,
        primary_kind: node.status,
        type: "skill",
      })),
    [relations],
  );

  const histogramMax = Math.max(1, ...(detail?.stats?.level_histogram ?? []).map((b) => b.n));

  const runAction = async (action: () => Promise<unknown>, note: string) => {
    try {
      await action();
      setActionNote(note);
      setDetail(null);
      setRelations(null);
      setHistory(null);
      load();
      if (tab === "history") loadHistory();
    } catch (err) {
      setActionNote(apiDetail(err));
    }
  };

  if (notFound) {
    return (
      <div className="mx-auto max-w-4xl space-y-4" data-testid="skill-page">
        <BackLink />
        <EmptyState title={t("skillPage.notFound")} description={t("skillPage.notFoundBody")} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="mx-auto max-w-4xl space-y-4" data-testid="skill-page">
        <BackLink />
        <p className="text-sm text-[var(--as-danger)]">{error}</p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="mx-auto max-w-4xl space-y-6" data-testid="skill-page">
        <BackLink />
        <div className="cv-shimmer h-16 rounded-[var(--as-radius-lg)]" />
        <div className="cv-shimmer h-24 rounded-[var(--as-radius-lg)]" />
        <div className="cv-shimmer h-40 rounded-[var(--as-radius-lg)]" />
      </div>
    );
  }

  const stats = detail.stats;
  const statTiles: StatTile[] = stats
    ? [
        {
          label: t("skillPage.stats.demand"),
          value: stats.demand_count,
          hint: t("skillPage.stats.demandHint"),
        },
        {
          label: t("skillPage.stats.avgLevel"),
          value: stats.avg_required_level != null ? `${stats.avg_required_level}/10` : "—",
        },
        { label: t("skillPage.stats.users"), value: stats.user_count },
        {
          label: t("skillPage.stats.firstSeen"),
          value: stats.first_seen ? formatAbsolute(stats.first_seen) : "—",
        },
        {
          label: t("skillPage.stats.lastSeen"),
          value: stats.last_seen ? formatAbsolute(stats.last_seen) : "—",
        },
      ]
    : [];

  const demandAvg = stats?.avg_required_level ?? null;

  return (
    <div className="mx-auto max-w-4xl space-y-4" data-testid="skill-page">
      <BackLink />
      {detail.merged_into ? (
        <div
          data-testid="merged-banner"
          className="flex items-center justify-between gap-3 rounded-[var(--as-radius)] border border-[var(--as-warning)] bg-[var(--as-muted)] px-4 py-2 text-sm"
        >
          <span className="text-[var(--as-fg)]">
            {t("skillPage.mergedInto", { key: detail.merged_into })}
          </span>
          <Link
            to={`/skills/${detail.merged_into}`}
            className="text-sm font-medium text-[var(--as-accent)] underline"
            data-testid="merged-target-link"
          >
            {t("skillPage.openSurvivor")}
          </Link>
        </div>
      ) : null}

      <header className="space-y-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-2xl font-semibold text-[var(--as-fg)]">{detail.label}</h1>
          <Badge
            variant={detail.status === "active" ? "success" : detail.status === "deprecated" ? "warning" : "secondary"}
            data-testid="skill-status"
          >
            {t(`taxonomy.${detail.status}`)}
          </Badge>
          {detail.origin !== "bank" ? (
            <Badge variant="outline" data-testid="skill-origin">
              {t(`skillPage.origin.${detail.origin}`, { defaultValue: detail.origin })}
            </Badge>
          ) : null}
          {stats?.corroboration ? (
            <Badge variant="ai" data-testid="skill-corroboration">
              {t("skillPage.corroborated", { count: stats.corroboration.postings })}
            </Badge>
          ) : null}
        </div>
        <p className="font-mono text-xs text-[var(--as-muted-fg)]">{detail.key}</p>
        <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--as-muted-fg)]">
          <span>{detail.category}</span>
          {detail.parent_key ? (
            <>
              <span aria-hidden>·</span>
              <Link to={`/skills/${detail.parent_key}`} className="underline">
                {t("skillPage.parent")}: {detail.parent_key}
              </Link>
            </>
          ) : null}
          {(detail.aliases?.length ?? 0) > 0 ? (
            <>
              <span aria-hidden>·</span>
              <span data-testid="skill-aliases">{detail.aliases?.join(", ")}</span>
            </>
          ) : null}
        </div>
        {detail.description ? (
          <p className="max-w-2xl text-sm text-[var(--as-fg)]">{detail.description}</p>
        ) : null}
        {isAdmin ? (
          <div className="flex flex-wrap items-center gap-2 pt-1" data-testid="skill-admin-actions">
            {detail.status === "proposed" ? (
              <Button
                size="sm"
                variant="outline"
                data-testid="skill-promote"
                onClick={() =>
                  void runAction(() => promoteSkill(detail.id), t("skillPage.note.promoted"))
                }
              >
                {t("taxonomy.promote")}
              </Button>
            ) : null}
            {detail.status === "active" ? (
              <Button
                size="sm"
                variant="outline"
                data-testid="skill-deprecate"
                onClick={() =>
                  void runAction(
                    () => updateTag("skills", detail.id, { status: "deprecated" } as never),
                    t("skillPage.note.deprecated"),
                  )
                }
              >
                {t("taxonomy.deprecate")}
              </Button>
            ) : detail.status === "deprecated" ? (
              <Button
                size="sm"
                variant="outline"
                data-testid="skill-restore"
                onClick={() =>
                  void runAction(
                    () => updateTag("skills", detail.id, { status: "active" } as never),
                    t("skillPage.note.restored"),
                  )
                }
              >
                {t("taxonomy.restore")}
              </Button>
            ) : null}
            {detail.status !== "active" ? (
              <Button
                size="sm"
                variant="outline"
                data-testid="skill-merge"
                onClick={() => {
                  setMerging((open) => !open);
                  if (activeSkills.length === 0) {
                    void fetchSkillOntology()
                      .then((rows) => setActiveSkills(rows.map((r) => ({ id: r.id, key: r.key }))))
                      .catch(() => setActiveSkills([]));
                  }
                }}
              >
                {t("taxonomy.merge")}
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              data-testid="skill-edit"
              onClick={() => setEditing((open) => !open)}
            >
              {t("skillPage.edit")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              data-testid="skill-delete"
              className="text-[var(--as-danger)]"
              onClick={() => setConfirmingDelete(true)}
            >
              {t("common.delete")}
            </Button>
          </div>
        ) : null}
        {actionNote ? (
          <p className="text-sm text-[var(--as-muted-fg)]" data-testid="skill-action-note">
            {actionNote}
          </p>
        ) : null}
        {editing ? (
          <div
            className="space-y-2 rounded-[var(--as-radius)] border border-[var(--as-border)] p-3"
            data-testid="skill-edit-form"
          >
            <input
              className="w-full rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
              value={editDraft.label}
              onChange={(e) => setEditDraft({ ...editDraft, label: e.target.value })}
              aria-label={t("taxonomy.label")}
            />
            <input
              className="w-full rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
              value={editDraft.category}
              onChange={(e) => setEditDraft({ ...editDraft, category: e.target.value })}
              aria-label={t("taxonomy.category")}
            />
            <textarea
              className="w-full rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm"
              value={editDraft.description}
              onChange={(e) => setEditDraft({ ...editDraft, description: e.target.value })}
              aria-label={t("taxonomy.descriptionPlaceholder")}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                data-testid="skill-edit-save"
                onClick={() =>
                  void runAction(async () => {
                    await updateTag("skills", detail.id, {
                      label: editDraft.label,
                      category: editDraft.category,
                      description: editDraft.description,
                    } as never);
                    setEditing(false);
                  }, t("skillPage.note.updated"))
                }
              >
                {t("common.save")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        ) : null}
        {merging ? (
          <div
            className="flex flex-wrap items-center gap-2 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)] p-3"
            data-testid="skill-merge-panel"
          >
            <span className="text-xs text-[var(--as-muted-fg)]">{t("taxonomy.mergeInto", { key: detail.key })}</span>
            <select
              value={mergeTarget}
              onChange={(e) => setMergeTarget(e.target.value)}
              className="rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-xs"
              aria-label={t("taxonomy.chooseActive")}
            >
              <option value="">{t("taxonomy.chooseActive")}</option>
              {activeSkills
                .filter((s) => s.id !== detail.id)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.key}
                  </option>
                ))}
            </select>
            <Button
              size="sm"
              disabled={!mergeTarget}
              data-testid="skill-merge-confirm"
              onClick={() =>
                void runAction(async () => {
                  await mergeSkill(detail.id, mergeTarget);
                  setMerging(false);
                  setMergeTarget("");
                }, t("skillPage.note.merged"))
              }
            >
              {t("taxonomy.mergeConfirm")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setMerging(false)}>
              {t("common.cancel")}
            </Button>
          </div>
        ) : null}
      </header>

      <SegmentedTabs
        ariaLabel={t("skillPage.tabsAria")}
        items={(["overview", "positions", "graph", "history"] as SkillTab[]).map((value) => ({
          value,
          label: t(`skillPage.tab.${value}`),
        }))}
        value={tab}
        onValueChange={setTab}
      />

      {tab === "overview" ? (
        <div className="space-y-4" data-testid="skill-overview">
          {stats ? <StatTiles tiles={statTiles} /> : <Spinner />}
          {stats && stats.level_histogram.length > 0 ? (
            <section data-testid="skill-histogram" className="space-y-2">
              <h2 className="text-sm font-medium text-[var(--as-fg)]">
                {t("skillPage.histogramTitle")}
              </h2>
              <div className="space-y-1">
                {stats.level_histogram.map((bucket) => (
                  <div key={bucket.level} className="flex items-center gap-2 text-xs">
                    <span className="w-14 tabular-nums text-[var(--as-muted-fg)]">
                      {t("skillPage.levelN", { level: bucket.level })}
                    </span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--as-muted)]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.round((bucket.n / histogramMax) * 100)}%`,
                          background: "var(--ca-heat-hot)",
                        }}
                      />
                    </div>
                    <span className="w-6 text-right tabular-nums text-[var(--as-muted-fg)]">
                      {bucket.n}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {(detail.level_anchors?.length ?? 0) > 0 ? (
            <section data-testid="skill-anchors" className="space-y-2">
              <h2 className="text-sm font-medium text-[var(--as-fg)]">
                {t("skillPage.anchorsTitle")}
              </h2>
              <dl className="space-y-1">
                {(detail.level_anchors ?? []).map((anchor) => (
                  <div key={anchor.level} className="flex gap-2 text-sm">
                    <dt className="w-20 shrink-0 font-medium text-[var(--as-fg)]">
                      {t("skillPage.levelN", { level: anchor.level })}
                      <span className="ml-1 font-normal text-[var(--as-muted-fg)]">
                        {anchor.label}
                      </span>
                    </dt>
                    <dd className="text-[var(--as-muted-fg)]">{anchor.description}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          <section data-testid="skill-personal" className="space-y-2">
            <h2 className="text-sm font-medium text-[var(--as-fg)]">
              {t("skillPage.yourSkillTitle")}
            </h2>
            {mine ? (
              <p className="text-sm text-[var(--as-fg)]">
                {t("skillPage.yourLevel", { level: mine.level })}
                {demandAvg != null
                  ? ` · ${t("skillPage.gap", {
                      delta: formatDelta(mine.level - demandAvg),
                    })}`
                  : ""}
              </p>
            ) : (
              <p className="text-sm text-[var(--as-muted-fg)]">
                {t("skillPage.notInProfile")}
                {demandAvg != null
                  ? ` · ${t("skillPage.demandAvg", { avg: demandAvg })}`
                  : ""}
              </p>
            )}
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={10}
                value={myLevel}
                onChange={(e) => setMyLevel(Number(e.target.value))}
                className="w-16 rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-sm tabular-nums"
                aria-label={t("skillPage.setLevelAria")}
                data-testid="skill-personal-level"
              />
              <Button
                size="sm"
                variant="outline"
                disabled={savingLevel || myLevel < 1 || myLevel > 10}
                data-testid="skill-personal-save"
                onClick={() =>
                  void (async () => {
                    setSavingLevel(true);
                    try {
                      const others = mySkills
                        .filter((row) => row.source === "self_report" && row.key !== key)
                        .map((row) => ({ skill_key: row.key, level: row.level }));
                      const updated = await saveMySkills([
                        ...others,
                        { skill_key: key, level: myLevel },
                      ]);
                      setMySkills(updated);
                      setActionNote(t("skillPage.note.levelSaved"));
                    } catch (err) {
                      setActionNote(apiDetail(err));
                    } finally {
                      setSavingLevel(false);
                    }
                  })()
                }
              >
                {mine ? t("skillPage.updateLevel") : t("skillPage.addLevel")}
              </Button>
            </div>
          </section>
          <section data-testid="skill-jobs" className="space-y-2">
            <h2 className="text-sm font-medium text-[var(--as-fg)]">
              {t("skillPage.jobsTitle")}
            </h2>
            {detail.jobs.length === 0 ? (
              <p className="text-sm text-[var(--as-muted-fg)]">{t("skillPage.noJobs")}</p>
            ) : (
              <ul className="space-y-1">
                {detail.jobs.map((job, index) => (
                  <li
                    key={`job-${index}`}
                    className="text-sm text-[var(--as-fg)]"
                    data-testid="skill-job-row"
                  >
                    {t("skillPage.jobLevel", { level: job.required_level })}
                    <Badge variant="outline" className="ml-2 text-[10px]">
                      {t(`skillPage.importance.${job.importance}`, {
                        defaultValue: job.importance,
                      })}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {(relations?.nodes.length ?? 0) > 1 ? (
            <section data-testid="skill-related" className="space-y-2">
              <h2 className="text-sm font-medium text-[var(--as-fg)]">
                {t("skillPage.relatedTitle")}
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {relations!.nodes
                  .filter((node) => node.id !== detail.id)
                  .map((node) => (
                    <Link
                      key={node.id}
                      to={`/skills/${node.key}`}
                      className="rounded-md border border-[var(--as-border)] px-2 py-0.5 text-xs text-[var(--as-fg)] hover:border-[var(--as-accent)]"
                    >
                      {node.label}
                    </Link>
                  ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}

      {tab === "positions" ? (
        <div className="space-y-3" data-testid="skill-positions">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-[var(--as-fg)]" data-testid="positions-count">
              {t("skillPage.positionsCount", { count: positions?.total ?? 0 })}
            </h2>
            <Link
              to={`/postings/search?skills=${encodeURIComponent(key)}`}
              className="text-sm text-[var(--as-accent)] underline"
              data-testid="positions-explore-link"
            >
              {t("skillPage.openInExplore")}
            </Link>
          </div>
          {positions === null ? (
            <div className="flex justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : positions.items.length === 0 ? (
            <EmptyState
              title={t("skillPage.positionsEmpty")}
              description={t("skillPage.positionsEmptyBody")}
            />
          ) : (
            <>
              <div className="space-y-3">
                {positions.items.map((posting) => (
                  <PostingCard
                    key={posting.id}
                    posting={posting}
                    onOpen={() => navigate(`/postings/${posting.ref}`)}
                    onChanged={() => loadPositions(positionsLimit)}
                  />
                ))}
              </div>
              {positions.items.length < positions.total ? (
                <div className="flex justify-center">
                  <Button
                    variant="outline"
                    size="sm"
                    data-testid="positions-load-more"
                    onClick={() => {
                      const next = positionsLimit + POSITIONS_PAGE;
                      setPositionsLimit(next);
                      loadPositions(next);
                    }}
                  >
                    {t("skillPage.loadMore")}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {tab === "graph" ? (
        <div className="space-y-3" data-testid="skill-graph">
          {relations === null ? (
            <div className="flex justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : relations.edges.length === 0 ? (
            <EmptyState title={t("skillPage.graphEmpty")} description={t("skillPage.graphEmptyBody")} />
          ) : (
            <>
              <div className="h-[420px] overflow-hidden rounded-xl border border-[var(--as-border)]">
                <ConceptGraphView
                  nodes={graphNodes}
                  edges={relations.edges.map((edge) => ({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    relation: edge.relation,
                  }))}
                  kindColors={NODE_COLORS}
                  relationColors={EDGE_COLORS}
                  hierarchyReversedRelations={REVERSED_RELATIONS}
                  labels={{
                    empty: t("skillPage.graphEmpty"),
                  }}
                  onSelectNode={(nodeId) => {
                    const node = relations.nodes.find((n) => n.id === nodeId);
                    if (node && node.key !== key) navigate(`/skills/${node.key}`);
                  }}
                />
              </div>
              {isAdmin ? (
                <div className="flex justify-end">
                  <Link
                    to="/settings/taxonomy?tab=relations&section=graph"
                    className="text-sm text-[var(--as-accent)] underline"
                    data-testid="graph-open-taxonomy"
                  >
                    {t("skillPage.openFullGraph")}
                  </Link>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      {tab === "history" ? (
        <div className="space-y-3" data-testid="skill-history">
          {history === null ? (
            <div className="flex justify-center py-12">
              <Spinner size="lg" />
            </div>
          ) : history.items.length === 0 ? (
            <EmptyState title={t("skillPage.historyEmpty")} />
          ) : (
            <>
              <h2 className="text-sm font-medium text-[var(--as-fg)]" data-testid="history-count">
                {t("skillPage.historyCount", { count: history.total })}
              </h2>
              <ol className="space-y-2">
                {history.items.map((entry) => (
                  <HistoryRow key={entry.id} entry={entry} />
                ))}
              </ol>
            </>
          )}
        </div>
      ) : null}

      <ConfirmationModal
        open={confirmingDelete}
        onOpenChange={(open) => setConfirmingDelete(open)}
        title={t("skillPage.deleteTitle", { key: detail.key })}
        description={t("skillPage.deleteBody")}
        confirmLabel={t("common.delete")}
        cancelLabel={t("common.cancel")}
        destructive
        onConfirm={() =>
          void runAction(async () => {
            await deleteTag("skills", detail.id);
            setConfirmingDelete(false);
            navigate("/settings/taxonomy?tab=skills");
          }, "")
        }
      />
    </div>
  );
}

function HistoryRow({ entry }: { entry: SkillChange }) {
  const { t } = useTranslation();
  const Icon = EVENT_ICON[entry.event] ?? Pencil;
  return (
    <li
      data-testid="history-row"
      data-event={entry.event}
      className="flex items-start gap-3 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2"
    >
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-[var(--as-muted-fg)]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-[var(--as-fg)]">
          {t(`skillPage.event.${entry.event}`, { defaultValue: entry.event })}
          <span className="ml-2 text-xs text-[var(--as-muted-fg)]">
            {formatAbsolute(entry.occurred_at)}
          </span>
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t(`skillPage.actor.${entry.actor_kind}`, { defaultValue: entry.actor_kind })}
          {entry.detail && Object.keys(entry.detail).length > 0 ? (
            <span className="ml-2 font-mono">{detailSummary(entry.detail)}</span>
          ) : null}
        </p>
      </div>
    </li>
  );
}

function detailSummary(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .slice(0, 4)
    .map(([field, change]) => {
      if (
        change &&
        typeof change === "object" &&
        "to" in (change as Record<string, unknown>)
      ) {
        return `${field} → ${String((change as Record<string, unknown>).to)}`;
      }
      if (typeof change === "string" || typeof change === "number") {
        return `${field}: ${String(change)}`;
      }
      return field;
    })
    .join(" · ");
}

function formatDelta(delta: number): string {
  if (delta >= 0) return `+${Number(delta.toFixed(1))}`;
  return String(Number(delta.toFixed(1)));
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link
      to="/settings/taxonomy?tab=skills"
      className="inline-flex items-center gap-1 text-sm text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
      data-testid="skill-back"
    >
      <ArrowLeft className="h-4 w-4" /> {t("skillPage.back")}
    </Link>
  );
}
