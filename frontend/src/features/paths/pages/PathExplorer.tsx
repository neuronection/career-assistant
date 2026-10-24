import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Compass, Map as MapIcon, Route as RouteIcon, Sparkles } from "lucide-react";

import { Badge } from "@neuronection/assistant-ui";
import { Button, EmptyState } from "@/components/ui";
import { fetchFamilyTree } from "@/api/jobs";
import {
  fetchJobPathGraph,
  fetchPathDetail,
  fetchPaths,
  setPathFlag,
} from "@/api/paths";
import { createGrowthPlan } from "@/api/growth";
import { PathRenderer } from "@/features/paths/PathRenderer";
import { buildPathView, defaultViewMode } from "@/features/paths/viewModel";
import type { JobFamilyNode } from "@/types";
import type { CareerPath, PathDetail } from "@/types/wire";
import type { PathMark } from "@/types";

const MARKS: PathMark[] = ["interested", "pinned", "dismissed"];

const EDUCATION_NOTE: Record<string, { key: string; years: string }> = {
  vocational: { key: "paths.education.vocational", years: "1–3" },
  bachelor: { key: "paths.education.bachelor", years: "3–4" },
  master: { key: "paths.education.master", years: "1–2" },
  phd: { key: "paths.education.phd", years: "3–5" },
};

const STATUS_TONES: Record<string, "secondary" | "ai" | "success"> = {
  draft: "secondary",
  active: "ai",
  published: "success",
};

const MARK_TONES: Record<string, "secondary" | "ai" | "success" | "danger"> = {
  interested: "ai",
  pinned: "success",
  dismissed: "danger",
};

export function PathExplorer() {
  const { t } = useTranslation();
  const [paths, setPaths] = useState<CareerPath[]>([]);
  const [detail, setDetail] = useState<PathDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [families, setFamilies] = useState<JobFamilyNode[]>([]);
  const [jobQuery, setJobQuery] = useState("");
  const [familyKey, setFamilyKey] = useState("");
  const [stage, setStage] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [growthAdded, setGrowthAdded] = useState(false);
  const [activePane, setActivePane] = useState<"rail" | "detail">("rail");
  const initialView = useMemo(defaultViewMode, []);
  const [viewMode, setViewMode] = useState(initialView);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await fetchPaths({
        job: jobQuery.trim() || undefined,
        family: familyKey || undefined,
        stage: stage || undefined,
      });
      setPaths(rows);
      setError("");
    } catch {
      setError(t("paths.loadError"));
      setPaths([]);
    } finally {
      setLoading(false);
    }
  }, [jobQuery, familyKey, stage, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void fetchFamilyTree().then(setFamilies).catch(() => setFamilies([]));
  }, []);

  const openDetail = useCallback(async (pathId: string) => {
    setSelectedId(pathId);
    setSelectedStepId(null);
    setGrowthAdded(false);
    setActivePane("detail");
    try {
      setDetail(await fetchPathDetail(pathId));
    } catch {
      setDetail(null);
    }
  }, []);

  const mark = async (
    target: { step_id: string | null },
    flag: PathMark | null,
    note = "",
  ) => {
    if (!detail) return;
    setBusy(true);
    try {
      const fresh = await setPathFlag(detail.id, {
        step_id: target.step_id,
        flag,
        note,
      });
      setDetail(fresh);
    } catch {
      setError(t("paths.markError"));
    } finally {
      setBusy(false);
    }
  };

  const currentDetailStep = detail?.steps?.find((step) => step.id === selectedStepId);
  const [noteDraft, setNoteDraft] = useState("");
  useEffect(() => {
    setNoteDraft(currentDetailStep?.my_note ?? "");
  }, [currentDetailStep?.id, currentDetailStep?.my_note]);
  const curated = paths.filter((path) => path.source !== "user");
  const mine = paths.filter((path) => path.source === "user");

  const railCard = (path: CareerPath) => (
    <article
      key={path.id}
      className={`group cursor-pointer rounded-xl border p-3 transition-colors duration-150 ${
        path.id === selectedId
          ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)]"
          : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
      }`}
      data-testid={`path-item-${path.id}`}
      onClick={() => void openDetail(path.id)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-[var(--as-fg)]">{path.title}</span>
        <Badge variant={STATUS_TONES[path.status] ?? "secondary"}>
          {t(`paths.status.${path.status}`, { defaultValue: path.status })}
        </Badge>
      </div>
      <p className="mt-0.5 truncate text-xs text-[var(--as-muted-fg)]">
        {t("paths.toJob", { job: path.job_title ?? path.job_code ?? "" })}
        {path.my_flag ? (
          <>
            {" · "}
            {t(`paths.marks.${path.my_flag}`)}
          </>
        ) : null}
      </p>
    </article>
  );

  const markButton = (
    id: string,
    active: boolean,
    target: { step_id: string | null },
    flag: PathMark,
  ) => (
    <Button
      key={flag}
      size="sm"
      variant={active ? "default" : "outline"}
      disabled={busy}
      data-testid={`${id}-${flag}`}
      aria-pressed={active}
      onClick={() => void mark(target, active ? null : flag)}
    >
      {t(`paths.marks.${flag}`)}
    </Button>
  );

  const saveNote = async () => {
    if (!currentDetailStep) return;
    const flag = (currentDetailStep.my_flag ?? "interested") as PathMark;
    await mark({ step_id: currentDetailStep.id }, flag, noteDraft);
  };

  return (
    <div className="ca-workspace flex min-h-0 flex-col gap-3 lg:h-full" data-testid="paths-page">
      <div
        className="flex shrink-0 flex-wrap items-center justify-between gap-3"
        data-testid="paths-toolbar"
      >
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
            <RouteIcon className="h-5 w-5" aria-hidden /> {t("paths.title")}
          </h1>
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">{t("paths.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={jobQuery}
            onChange={(event) => setJobQuery(event.target.value)}
            placeholder={t("paths.searchPlaceholder")}
            aria-label={t("paths.searchPlaceholder")}
            data-testid="paths-search"
            className="w-44 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2.5 py-1.5 text-sm text-[var(--as-fg)] placeholder:text-[var(--as-muted-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
          />
          <select
            value={familyKey}
            onChange={(event) => setFamilyKey(event.target.value)}
            aria-label={t("paths.familyFilter")}
            data-testid="paths-filter-family"
            className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
          >
            <option value="">{t("paths.allFamilies")}</option>
            {families.map((family) => (
              <option key={family.key} value={family.key}>
                {family.label}
              </option>
            ))}
          </select>
          <select
            value={stage}
            onChange={(event) => setStage(event.target.value)}
            aria-label={t("paths.stageFilter")}
            data-testid="paths-filter-stage"
            className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
          >
            <option value="">{t("paths.allStages")}</option>
            {["student", "early_career", "experienced", "switching", "returning"].map(
              (value) => (
                <option key={value} value={value}>
                  {t(`paths.stage.${value}`)}
                </option>
              ),
            )}
          </select>
        </div>
      </div>

      {error && (
        <p role="alert" className="shrink-0 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}

      {selectedId && detail ? (
        <div
          className="ca-ws-switcher mb-2 flex shrink-0 gap-1 lg:hidden"
          role="group"
          aria-label={t("paths.panesAria")}
          data-testid="pane-switcher"
        >
          {(
            [
              ["rail", t("paths.pane.rail")],
              ["detail", t("paths.pane.detail")],
            ] as const
          ).map(([paneId, label]) => (
            <button
              key={paneId}
              type="button"
              aria-pressed={activePane === paneId}
              onClick={() => setActivePane(paneId)}
              data-testid={`pane-${paneId}`}
              className={`flex-1 cursor-pointer rounded-lg border border-[var(--as-border)] px-2 py-1.5 text-xs font-medium transition-colors duration-150 ${
                activePane === paneId
                  ? "bg-[var(--as-surface-raised)] text-[var(--as-fg)]"
                  : "bg-[var(--as-surface)] text-[var(--as-muted-fg)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="ca-ws-grid grid min-h-0 flex-1 grid-cols-1 gap-3">
        <div
          className={`ca-ws-pane cv-pane-enter min-h-0 flex-col gap-2.5 overflow-y-auto ${
            activePane === "rail" ? "flex" : "hidden"
          } lg:flex`}
          data-testid="paths-rail"
        >
          {loading ? (
            <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
              {t("common.loading")}
            </p>
          ) : paths.length === 0 ? (
            <EmptyState
              compact
              title={t("paths.emptyTitle")}
              description={t("paths.emptyBody")}
            />
          ) : (
            <>
              <p className="px-2 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("paths.groupCurated")}
              </p>
              {curated.map(railCard)}
              {mine.length > 0 ? (
                <>
                  <p className="px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("paths.groupMine")}
                  </p>
                  {mine.map(railCard)}
                </>
              ) : null}
            </>
          )}
        </div>

        <div
          className={`ca-ws-pane cv-pane-enter min-h-0 flex-col gap-3 overflow-y-auto ${
            activePane === "detail" ? "flex" : "hidden"
          } lg:flex`}
          data-testid="paths-detail"
        >
          {!detail ? (
            <div className="flex h-full items-center justify-center">
              <EmptyState
                title={t("paths.pickTitle")}
                description={t("paths.pickBody")}
              />
            </div>
          ) : (
            <div className="flex min-h-0 flex-col gap-3">
              <div
                className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
                data-testid="path-header"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-semibold text-[var(--as-fg)]">
                      {detail.title}
                    </h2>
                    <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
                      {detail.description}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={STATUS_TONES[detail.status] ?? "secondary"}>
                      {t(`paths.status.${detail.status}`, { defaultValue: detail.status })}
                    </Badge>
                    {detail.my_flag ? (
                      <Badge variant={MARK_TONES[detail.my_flag] ?? "secondary"}>
                        {t(`paths.marks.${detail.my_flag}`)}
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  {detail.job_code ? (
                    <Link
                      to={`/jobs/${detail.job_code}`}
                      data-testid="path-header-job"
                      className="inline-flex items-center gap-1 rounded-lg border border-[var(--as-border)] px-2 py-1 font-medium hover:border-[var(--as-accent)]"
                    >
                      <Compass className="size-3.5" aria-hidden />
                      {t("paths.toJob", { job: detail.job_title ?? detail.job_code })}
                    </Link>
                  ) : null}
                  <span
                    className="text-[var(--as-muted-fg)]"
                    data-testid="path-header-completeness"
                  >
                    {detail.skills_total > 0
                      ? t("paths.completeness", {
                          met: detail.skills_met,
                          total: detail.skills_total,
                        })
                      : t("paths.completenessNone")}
                  </span>
                  <span className="flex-1" />
                  <div className="flex items-center gap-1.5">
                    {MARKS.map((flag) =>
                      markButton(
                        "path-mark",
                        detail.my_flag === flag,
                        { step_id: null },
                        flag,
                      ),
                    )}
                    {detail.source === "user" ? null : (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy || growthAdded}
                        data-testid="paths-growth-add"
                        onClick={() => {
                          void createGrowthPlan(detail.job_id)
                            .then(() => setGrowthAdded(true))
                            .catch(() => setError(t("paths.growthError")));
                        }}
                      >
                        <Sparkles className="mr-1 size-3.5" aria-hidden />
                        {growthAdded ? t("paths.growthAdded") : t("paths.growthAdd")}
                      </Button>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4">
                <PathRenderer
                  view={buildPathView(detail)}
                  viewMode={viewMode}
                  onViewModeChange={setViewMode}
                  selectedStepId={selectedStepId}
                  onStepClick={setSelectedStepId}
                />
              </div>

              {currentDetailStep ? (
                <div
                  className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
                  data-testid="path-step-panel"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold text-[var(--as-fg)]">
                      {currentDetailStep.label}
                      {currentDetailStep.optional ? (
                        <span className="ml-2 text-xs font-normal text-[var(--as-muted-fg)]">
                          {t("paths.renderer.optional")}
                        </span>
                      ) : null}
                    </h3>
                    <Badge variant="secondary">
                      {t(`paths.stepKind.${currentDetailStep.kind}`, {
                        defaultValue: currentDetailStep.kind,
                      })}
                    </Badge>
                  </div>
                  {currentDetailStep.edge_label ? (
                    <p className="mt-1 text-xs text-[var(--as-accent)]">
                      {t("paths.renderer.viaBranch", { label: currentDetailStep.edge_label })}
                    </p>
                  ) : null}
                  {currentDetailStep.skill ? (
                    <div className="mt-3" data-testid="path-step-skill">
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium text-[var(--as-fg)]">
                          {currentDetailStep.skill.label}
                        </span>
                        <span className="text-xs text-[var(--as-muted-fg)]">
                          {t("paths.skillLevels", {
                            you: currentDetailStep.skill.user_level ?? "–",
                            required: currentDetailStep.skill.required_level ?? "–",
                          })}
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--as-muted)]">
                        <div
                          className={`h-1.5 rounded-full ${
                            (currentDetailStep.skill.user_level ?? 0) >=
                            (currentDetailStep.skill.required_level ?? 1)
                              ? "bg-emerald-500"
                              : "bg-amber-500"
                          }`}
                          style={{
                            width: `${
                              (Math.min(
                                currentDetailStep.skill.user_level ?? 0,
                                currentDetailStep.skill.required_level ?? 10,
                              ) /
                                10) *
                              100
                            }%`,
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                  {currentDetailStep.education_level &&
                  EDUCATION_NOTE[currentDetailStep.education_level] ? (
                    <p className="mt-3 text-xs text-[var(--as-muted-fg)]">
                      {t(EDUCATION_NOTE[currentDetailStep.education_level].key, {
                        defaultValue: currentDetailStep.education_level,
                      })}{" "}
                      · {t("paths.education.typicalYears", {
                        years: EDUCATION_NOTE[currentDetailStep.education_level].years,
                      })}
                    </p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    {MARKS.map((flag) =>
                      markButton(
                        "path-step-mark",
                        currentDetailStep.my_flag === flag,
                        { step_id: currentDetailStep.id },
                        flag,
                      ),
                    )}
                  </div>
                  {currentDetailStep.my_flag ? (
                    <div className="mt-2 flex items-center gap-2">
                      <input
                        value={noteDraft}
                        onChange={(event) => setNoteDraft(event.target.value)}
                        placeholder={t("paths.notePlaceholder")}
                        aria-label={t("paths.notePlaceholder")}
                        data-testid="path-step-note-input"
                        className="min-w-0 flex-1 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] px-2.5 py-1.5 text-sm text-[var(--as-fg)] placeholder:text-[var(--as-muted-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        data-testid="path-step-note-save"
                        onClick={() => void saveNote()}
                      >
                        {t("common.save")}
                      </Button>
                    </div>
                  ) : null}
                  {currentDetailStep.my_note ? (
                    <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="path-step-note">
                      {currentDetailStep.my_note}
                    </p>
                  ) : null}
                  <p className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                    {currentDetailStep.family_key ? (
                      <Link
                        to="/catalog"
                        className="rounded-lg border border-[var(--as-border)] px-2 py-1 hover:border-[var(--as-accent)]"
                      >
                        {t("paths.openCatalog")}
                      </Link>
                    ) : null}
                    {currentDetailStep.skill ? (
                      <Link
                        to="/growth"
                        className="rounded-lg border border-[var(--as-border)] px-2 py-1 hover:border-[var(--as-accent)]"
                      >
                        {t("paths.openSkillResources")}
                      </Link>
                    ) : null}
                    {currentDetailStep.education_level ? (
                      <Link
                        to="/profile/education"
                        className="rounded-lg border border-[var(--as-border)] px-2 py-1 hover:border-[var(--as-accent)]"
                      >
                        {t("paths.openEducation")}
                      </Link>
                    ) : null}
                  </p>
                </div>
              ) : null}

              {jobQuery.trim() ? <ComputedRoutes jobRef={jobQuery.trim()} /> : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ComputedRoutes({ jobRef }: { jobRef: string }) {
  const { t } = useTranslation();
  const [view, setView] = useState<ReturnType<typeof buildPathView> | null>(null);

  useEffect(() => {
    let alive = true;
    void fetchJobPathGraph(jobRef)
      .then((graph) => {
        if (!alive) return;
        const parentOf = new Map<string, string>();
        for (const edge of graph.edges ?? []) parentOf.set(edge.to_code, edge.from_code);
        const steps = (graph.nodes ?? [])
          .filter((node) => node.depth > 0)
          .sort((a, b) => a.depth - b.depth)
          .map((node, index) => ({
            id: node.code,
            position: index,
            kind: "job",
            label: node.title,
            parent_step_id: parentOf.get(node.code) ?? null,
            edge_label: "",
          }));
        const root = (graph.nodes ?? []).find((node) => node.depth === 0);
        setView(
          buildPathView({
            id: `computed-${graph.root}`,
            title: t("paths.computedTitle", { job: root?.title ?? graph.root }),
            source: "computed",
            status: "published",
            job_code: graph.root,
            job_title: root?.title ?? graph.root,
            steps,
          }),
        );
      })
      .catch(() => setView(null));
    return () => {
      alive = false;
    };
  }, [jobRef, t]);

  if (!view || view.nodes.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4" data-testid="paths-computed">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
        <MapIcon className="size-4" aria-hidden /> {view.title}
      </h3>
      <PathRenderer view={view} />
    </div>
  );
}
