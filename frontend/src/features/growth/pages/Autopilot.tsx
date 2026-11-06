import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import {
  Bot,
  CirclePause,
  CirclePlay,
  Pencil,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  Button,
  ChipInput,
  ConfirmationModal,
  EmptyState,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  PanelModal,
  Spinner,
} from "@/components/ui";
import { AiSetupPrompt } from "@/components/ai/AiSetupPrompt";
import { ActiveFilterChips } from "@/components/filters/ActiveFilterChips";
import { useContainerBand, type ContainerBand } from "@/hooks/useContainerBand";
import {
  ChipTogglesRow,
  NumberField,
  SegmentedRow,
  StepperRow,
  TextareaField,
  ToggleRow,
} from "@/features/cv/components/cv/formPrimitives";
import {
  createGoal,
  DEFAULT_PROFILE_USAGE,
  deleteGoal,
  fetchFindingsFeed,
  fetchGoals,
  fetchProfileContext,
  fetchRunDetail,
  fetchRunsRail,
  patchGoal,
  runGoal,
  sendFindingFeedback,
} from "@/api/autopilot";
import { apiDetail } from "@/api/client";
import type {
  AutopilotConstraints,
  AutopilotFindingFeedItem,
  AutopilotGoal,
  AutopilotRunDetail,
  FindingFeedResponse,
  ProfileContextSnapshot,
  ProfileUsage,
  RunsRailRow,
} from "@/api/autopilot";
import { AutopilotFindingCard } from "@/features/growth/components/AutopilotFindingCard";
import {
  RunDetail,
  RUN_STATUS_KEYS,
  RUN_STATUS_STYLE,
} from "@/features/growth/components/RunDetail";
import { FindingsRail } from "@/features/growth/components/FindingsRail";
import {
  DEFAULT_FINDINGS_FILTERS,
  countActiveFindingsFilters,
  findingsFilterChips,
  parseFindingsFilters,
  toFeedParams,
  toFindingsSearchParams,
  type FindingsFilters,
} from "@/features/growth/findingsFilterState";

const SENIORITY_OPTIONS = [
  { value: "intern", labelKey: "autopilot.seniority.intern" },
  { value: "junior", labelKey: "autopilot.seniority.junior" },
  { value: "mid", labelKey: "autopilot.seniority.mid" },
  { value: "senior", labelKey: "autopilot.seniority.senior" },
];

function constraintChips(goal: AutopilotGoal): string[] {
  const t = i18next.t;
  const c = goal.constraints;
  const chips: string[] = [];
  for (const term of c.must_terms ?? [])
    chips.push(t("autopilot.chip.must", { term }));
  for (const term of c.never_terms ?? [])
    chips.push(t("autopilot.chip.never", { term }));
  if (c.remote) chips.push(t("autopilot.chip.remote"));
  if (c.salary_min)
    chips.push(t("autopilot.chip.salaryMin", { salary: c.salary_min.toLocaleString() }));
  for (const s of c.seniority ?? [])
    chips.push(t(`autopilot.seniority.${s}`, { defaultValue: s }));
  const usage: ProfileUsage = { ...DEFAULT_PROFILE_USAGE, ...(c.profile ?? {}) };
  const offKeys: (keyof ProfileUsage)[] = [
    "use_skills",
    "use_education",
    "use_languages",
    "use_location",
    "use_experience",
    "use_lifestyle",
  ];
  for (const key of offKeys) {
    if (!usage[key]) chips.push(t(`autopilot.profileUsage.chips.${key}`));
  }
  if (usage.stage_source === "goal") chips.push(t("autopilot.profileUsage.chips.stage_source"));
  return chips;
}

function cadenceLabel(goal: AutopilotGoal): string {
  const t = i18next.t;
  const cadence = goal.cadence;
  if (!cadence) return t("autopilot.cadence.manual");
  if (cadence.type === "daily_at")
    return t("autopilot.cadence.dailyAt", { time: cadence.params.time ?? "" });
  if (cadence.type === "weekly") return t("autopilot.cadence.weekly");
  if (cadence.type === "interval")
    return t("autopilot.cadence.interval", {
      hours: Math.round(Number(cadence.params.every_minutes ?? 0) / 60),
    });
  return cadence.type;
}

function dateLabel(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface GoalDraft {
  goal_text: string;
  must_terms: string[];
  never_terms: string[];
  remote: boolean;
  salary_min: number | null;
  seniority: string[];
  cooldown_days: number;
  top_n: number;
  cadence: string;
  profile: ProfileUsage;
}

const USAGE_TOGGLE_KEYS: { key: keyof ProfileUsage; labelKey: string; hintKey: string }[] = [
  {
    key: "use_skills",
    labelKey: "autopilot.profileUsage.toggles.use_skills.label",
    hintKey: "autopilot.profileUsage.toggles.use_skills.description",
  },
  {
    key: "use_education",
    labelKey: "autopilot.profileUsage.toggles.use_education.label",
    hintKey: "autopilot.profileUsage.toggles.use_education.description",
  },
  {
    key: "use_languages",
    labelKey: "autopilot.profileUsage.toggles.use_languages.label",
    hintKey: "autopilot.profileUsage.toggles.use_languages.description",
  },
  {
    key: "use_location",
    labelKey: "autopilot.profileUsage.toggles.use_location.label",
    hintKey: "autopilot.profileUsage.toggles.use_location.description",
  },
  {
    key: "use_experience",
    labelKey: "autopilot.profileUsage.toggles.use_experience.label",
    hintKey: "autopilot.profileUsage.toggles.use_experience.description",
  },
  {
    key: "use_lifestyle",
    labelKey: "autopilot.profileUsage.toggles.use_lifestyle.label",
    hintKey: "autopilot.profileUsage.toggles.use_lifestyle.description",
  },
];

function usageSummary(
  profile: ProfileUsage,
  seniority: string[],
  snapshot: ProfileContextSnapshot | null,
  t: (key: string, options?: Record<string, unknown>) => string
): string {
  const lines: string[] = [];
  const skills = snapshot?.skills?.map((row) => row.key) ?? [];
  lines.push(
    profile.use_skills
      ? skills.length
        ? t("autopilot.summary.skills", { items: skills.join(", ") })
        : t("autopilot.summary.skillsNone")
      : t("autopilot.summary.skillsUnused")
  );
  lines.push(
    profile.use_education
      ? snapshot?.education_level
        ? t("autopilot.summary.education", { level: snapshot.education_level })
        : t("autopilot.summary.educationNone")
      : t("autopilot.summary.educationUnused")
  );
  const languages = snapshot?.languages?.map((row) => row.code) ?? [];
  lines.push(
    profile.use_languages
      ? languages.length
        ? t("autopilot.summary.languages", { items: languages.join(", ") })
        : t("autopilot.summary.languagesNone")
      : t("autopilot.summary.languagesUnused")
  );
  if (!profile.use_experience) {
    lines.push(t("autopilot.summary.stageUnused"));
  } else if (snapshot?.stage && snapshot.stage_source === "goal") {
    lines.push(t("autopilot.summary.stage", { stage: snapshot.stage }));
  } else if (profile.stage_source === "goal" && !seniority.length) {
    lines.push(t("autopilot.summary.stageFromProfile"));
  } else if (snapshot?.stage) {
    lines.push(t("autopilot.summary.stage", { stage: snapshot.stage }));
  } else {
    lines.push(t("autopilot.summary.stageNone"));
  }
  const location = snapshot?.city ?? snapshot?.country;
  lines.push(
    profile.use_location
      ? location
        ? t("autopilot.summary.location", { city: location })
        : t("autopilot.summary.locationNone")
      : t("autopilot.summary.locationUnused")
  );
  lines.push(
    profile.use_lifestyle
      ? t("autopilot.summary.lifestyle", { count: snapshot?.lifestyle_count ?? 0 })
      : t("autopilot.summary.lifestyleUnused")
  );
  return lines.join(" · ");
}

function draftFromGoal(goal: AutopilotGoal | null): GoalDraft {
  const c: AutopilotConstraints = goal?.constraints ?? {
    must_terms: [],
    never_terms: [],
    family_keys: [],
    source_keys: [],
    remote: false,
    salary_min: null,
    seniority: [],
    exclude_seen: true,
    cooldown_days: 7,
    top_n: 5,
    profile: DEFAULT_PROFILE_USAGE,
  };
  const cadence = goal?.cadence?.type ?? "manual";
  return {
    goal_text: goal?.goal_text ?? "",
    must_terms: [...(c.must_terms ?? [])],
    never_terms: [...(c.never_terms ?? [])],
    remote: c.remote ?? false,
    salary_min: c.salary_min ?? null,
    seniority: [...(c.seniority ?? [])],
    cooldown_days: c.cooldown_days ?? 7,
    top_n: c.top_n ?? 5,
    cadence: cadence === "daily_at" ? "daily" : cadence === "weekly" ? "weekly" : "manual",
    profile: { ...DEFAULT_PROFILE_USAGE, ...(c.profile ?? {}) },
  };
}

function GoalModal({
  open,
  goal,
  onClose,
  onSaved,
}: {
  open: boolean;
  goal: AutopilotGoal | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<GoalDraft>(() => draftFromGoal(goal));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<ProfileContextSnapshot | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (open) {
      setDraft(draftFromGoal(goal));
      setError(null);
      setUsageOpen(false);
      setSnapshot(null);
    }
  }, [open, goal]);

  useEffect(() => {
    if (!open || !usageOpen) return;
    let live = true;
    fetchProfileContext(draft.profile, draft.seniority)
      .then((result) => {
        if (live) setSnapshot(result);
      })
      .catch(() => {
        if (live) setSnapshot(null);
      });
    return () => {
      live = false;
    };
  }, [open, usageOpen, draft.profile, draft.seniority]);

  const save = async () => {
    if (draft.goal_text.trim().length < 3) {
      setError(t("autopilot.validation.goal"));
      return;
    }
    setSaving(true);
    setError(null);
    const cadence =
      draft.cadence === "daily"
        ? { type: "daily_at", params: { time: "08:00", timezone: "UTC" } }
        : draft.cadence === "weekly"
          ? { type: "weekly", params: { weekday: 0, time: "08:00", timezone: "UTC" } }
          : undefined;
    const constraints = {
      must_terms: draft.must_terms,
      never_terms: draft.never_terms,
      remote: draft.remote || null,
      salary_min: draft.salary_min,
      seniority: draft.seniority,
      cooldown_days: draft.cooldown_days,
      top_n: draft.top_n,
      profile: draft.profile,
    };
    try {
      if (goal) {
        await patchGoal(goal.id, {
          goal_text: draft.goal_text.trim(),
          constraints,
          ...(cadence ? { cadence } : {}),
          ...(draft.cadence === "manual" && goal.cadence ? { remove_cadence: true } : {}),
        });
      } else {
        await createGoal({
          goal_text: draft.goal_text.trim(),
          constraints,
          cadence: cadence ?? null,
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>
            {goal ? t("autopilot.modal.editTitle") : t("autopilot.modal.newTitle")}
          </ModalTitle>
        </ModalHeader>
        <div className="space-y-4">
          <TextareaField
            label={t("autopilot.goalLabel")}
            value={draft.goal_text}
            onChange={(value) => setDraft({ ...draft, goal_text: value })}
            rows={3}
            maxLength={2000}
            counter
            placeholder={t("autopilot.goalPlaceholder")}
            testId="goal-text"
          />
          <div>
            <p className="mb-1 text-xs text-[var(--as-muted-fg)]">
              {t("autopilot.mustTerms")}
            </p>
            <ChipInput
              value={draft.must_terms}
              onChange={(value) => setDraft({ ...draft, must_terms: value })}
              placeholder={t("autopilot.chipPlaceholder")}
              inputLabel={t("autopilot.addMustTerm")}
              addLabel={t("common.add")}
              data-testid="goal-must-terms"
            />
          </div>
          <div>
            <p className="mb-1 text-xs text-[var(--as-muted-fg)]">
              {t("autopilot.neverTerms")}
            </p>
            <ChipInput
              value={draft.never_terms}
              onChange={(value) => setDraft({ ...draft, never_terms: value })}
              placeholder={t("autopilot.chipPlaceholder")}
              inputLabel={t("autopilot.addNeverTerm")}
              addLabel={t("common.add")}
              data-testid="goal-never-terms"
            />
          </div>
          <ChipTogglesRow
            label={t("autopilot.seniorityLabel")}
            values={draft.seniority}
            options={SENIORITY_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey),
            }))}
            onChange={(values) => setDraft({ ...draft, seniority: values })}
          />
          <div className="grid grid-cols-2 gap-3">
            <NumberField
              label={t("autopilot.minSalary")}
              value={draft.salary_min}
              onChange={(value) => setDraft({ ...draft, salary_min: value })}
              min={0}
              testId="goal-salary"
            />
            <StepperRow
              label={t("autopilot.shortlist")}
              value={draft.top_n}
              min={1}
              max={10}
              onChange={(value) => setDraft({ ...draft, top_n: value })}
            />
          </div>
          <ToggleRow
            label={t("autopilot.remoteOnly")}
            checked={draft.remote}
            onChange={(checked) => setDraft({ ...draft, remote: checked })}
          />
          <StepperRow
            label={t("autopilot.cooldown")}
            value={draft.cooldown_days}
            min={0}
            max={90}
            suffix={t("autopilot.cooldownSuffix")}
            onChange={(value) => setDraft({ ...draft, cooldown_days: value })}
          />
          <SegmentedRow
            label={t("autopilot.cadenceLabel")}
            value={draft.cadence}
            options={[
              { value: "manual", label: t("autopilot.cadenceOpt.manual") },
              { value: "daily", label: t("autopilot.cadenceOpt.daily") },
              { value: "weekly", label: t("autopilot.cadenceOpt.weekly") },
            ]}
            onChange={(value) => setDraft({ ...draft, cadence: value })}
          />
          <div className="rounded-xl border border-[var(--as-border)] p-3">
            <button
              type="button"
              className="flex w-full cursor-pointer items-center justify-between gap-2 text-xs font-medium text-[var(--as-fg)]"
              aria-expanded={usageOpen}
              onClick={() => setUsageOpen((next) => !next)}
              data-testid="usage-section-toggle"
            >
              {t("autopilot.profileUsage.title")}
              <span className="text-[var(--as-muted-fg)]">{usageOpen ? "−" : "+"}</span>
            </button>
            {usageOpen && (
              <div className="mt-3 space-y-3" data-testid="usage-section">
                {draft.profile.use_skills &&
                draft.profile.use_education &&
                draft.profile.use_languages &&
                draft.profile.use_location &&
                draft.profile.use_experience &&
                draft.profile.use_lifestyle ? null : (
                  <p className="text-xs text-[var(--as-muted-fg)]" data-testid="usage-goal-only">
                    {t("autopilot.profileUsage.goalOnly")}
                  </p>
                )}
                {USAGE_TOGGLE_KEYS.map(({ key, labelKey, hintKey }) => (
                  <div key={key}>
                    <ToggleRow
                      label={t(labelKey)}
                      checked={draft.profile[key] as boolean}
                      onChange={(checked) =>
                        setDraft({ ...draft, profile: { ...draft.profile, [key]: checked } })
                      }
                    />
                    <p className="mt-0.5 text-[11px] text-[var(--as-muted-fg)]">{t(hintKey)}</p>
                  </div>
                ))}
                <SegmentedRow
                  label={t("autopilot.profileUsage.stageSourceLabel")}
                  value={draft.profile.stage_source}
                  options={[
                    {
                      value: "profile",
                      label: t("autopilot.profileUsage.stageSource.profile"),
                    },
                    { value: "goal", label: t("autopilot.profileUsage.stageSource.goal") },
                  ]}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      profile: {
                        ...draft.profile,
                        stage_source: value as ProfileUsage["stage_source"],
                      },
                    })
                  }
                />
                <div
                  className="rounded-lg bg-[var(--as-muted)] p-2 text-[11px] text-[var(--as-muted-fg)]"
                  data-testid="usage-summary"
                >
                  {snapshot === null
                    ? t("autopilot.summary.loading")
                    : usageSummary(draft.profile, draft.seniority, snapshot, t)}
                </div>
                <p className="text-[11px] text-[var(--as-muted-fg)]">
                  {t("autopilot.profileUsage.footnote")}
                </p>
              </div>
            )}
          </div>
          {error && (
            <p className="text-xs text-red-600" role="alert" data-testid="goal-error">
              {error}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={saving} data-testid="goal-save">
            {saving
              ? t("common.saving")
              : goal
                ? t("autopilot.saveChanges")
                : t("autopilot.createGoal")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function RunsRail({
  runs,
  open,
  onToggle,
}: {
  runs: RunsRailRow[] | null;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside className="ca-ap-runs-rail shrink-0 self-start" data-testid="autopilot-runs-rail">
      <div className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3">
        <button
          type="button"
          className="flex w-full items-center justify-between gap-2 text-sm font-semibold text-slate-700"
          aria-expanded={open}
          onClick={onToggle}
          data-testid="runs-rail-toggle"
        >
          {t("autopilot.workspace.runsRail")}
          <span className="flex items-center gap-2">
            {runs && runs.length > 0 ? (
              <span className="text-xs text-primary-600" data-testid="runs-rail-count">
                {runs.length}
              </span>
            ) : null}
            <span aria-hidden>{open ? "−" : "+"}</span>
          </span>
        </button>
        {open ? (
          <ul className="mt-2 space-y-2">
            {(runs ?? []).map((run) => (
              <li key={run.id}>
                <Link
                  to={`/autopilot/runs/${run.id}`}
                  className="block rounded-lg border border-[var(--as-border)] p-2 transition-colors hover:border-[var(--as-accent)]"
                  data-testid={`runs-rail-row-${run.id}`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] ${
                        RUN_STATUS_STYLE[run.status] ?? "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {RUN_STATUS_KEYS[run.status]
                        ? t(RUN_STATUS_KEYS[run.status])
                        : run.status}
                    </span>
                    <span className="text-[11px] text-[var(--as-muted-fg)]">
                      {dateLabel(run.created_at)}
                    </span>
                  </div>
                  <p
                    className="mt-1 truncate text-xs font-medium text-slate-800"
                    title={run.goal_text}
                  >
                    {run.goal_text}
                  </p>
                  <p
                    className="mt-0.5 text-[11px] tabular-nums text-[var(--as-muted-fg)]"
                    data-testid={`runs-rail-counts-${run.id}`}
                  >
                    {t("autopilot.workspace.railFindings", { count: run.findings_count })}
                    {` · `}
                    {t("autopilot.workspace.railExamined", { count: run.examined_sum })}
                    {run.tokens_used
                      ? ` · ${t("autopilot.tokens", { count: run.tokens_used })}`
                      : ""}
                  </p>
                </Link>
              </li>
            ))}
            {runs !== null && runs.length === 0 ? (
              <li className="text-xs text-[var(--as-muted-fg)]">{t("autopilot.noRunsTitle")}</li>
            ) : null}
          </ul>
        ) : null}
      </div>
    </aside>
  );
}

function RunDetailModal({
  runId,
  onClose,
}: {
  runId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<AutopilotRunDetail | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setMissing(false);
    fetchRunDetail(runId)
      .then((result) => {
        if (live) setDetail(result);
      })
      .catch(() => {
        if (live) setMissing(true);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  return (
    <PanelModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={
        <span className="flex items-center gap-3 truncate">
          <span className="truncate">{t("autopilot.runDetail.title")}</span>
          <Link
            to={`/autopilot/runs/${runId}`}
            className="text-xs font-normal text-[var(--as-accent)] hover:underline"
            data-testid="run-detail-open-full"
          >
            {t("autopilot.runDetail.openFull")}
          </Link>
        </span>
      }
      size="xl"
      data-testid="run-detail-modal"
    >
      {missing ? (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="run-detail-missing">
          {t("autopilot.runDetail.missing")}
        </p>
      ) : detail === null ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <RunDetail detail={detail} />
      )}
    </PanelModal>
  );
}

export function Autopilot({ band: bandOverride }: { band?: ContainerBand } = {}) {
  const { t } = useTranslation();
  const { ref: bandRef, band } = useContainerBand(bandOverride);
  const [searchParams, setSearchParams] = useSearchParams();
  const [goals, setGoals] = useState<AutopilotGoal[] | null>(null);
  const [rail, setRail] = useState<RunsRailRow[] | null>(null);
  const [feed, setFeed] = useState<FindingFeedResponse | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<AutopilotGoal | null>(null);
  const [deleting, setDeleting] = useState<AutopilotGoal | null>(null);
  const [busyGoal, setBusyGoal] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [runsOpen, setRunsOpen] = useState(true);
  const [peekRunId, setPeekRunId] = useState<string | null>(null);
  const runParam = searchParams.get("run");
  const filters = useMemo(() => parseFindingsFilters(searchParams), [searchParams]);
  const goalParam = filters.goal;
  const view = filters.view;

  const writeFilters = useCallback(
    (next: FindingsFilters) => {
      setSearchParams(toFindingsSearchParams(next), { replace: true });
    },
    [setSearchParams],
  );

  const loadGoalsAndRail = useCallback(() => {
    void fetchGoals().then(setGoals).catch(() => setGoals([]));
    void fetchRunsRail().then(setRail).catch(() => setRail([]));
  }, []);

  const loadFeed = useCallback(
    (cursor?: string) => {
      void fetchFindingsFeed({ ...toFeedParams(filters), limit: 20, cursor })
        .then((page) =>
          setFeed((prev) =>
            cursor && prev
              ? { items: [...prev.items, ...page.items], next_cursor: page.next_cursor, facets: prev.facets }
              : page,
          ),
        )
        .catch(() =>
          setFeed({
            items: [],
            next_cursor: null,
            facets: { goal: {}, source: {}, seniority: {}, state: { open: 0, dismissed: 0 } },
          }),
        );
    },
    [filters],
  );

  useEffect(loadGoalsAndRail, [loadGoalsAndRail]);
  useEffect(() => {
    setFeed(null);
    loadFeed();
  }, [loadFeed]);

  const reload = useCallback(() => {
    loadGoalsAndRail();
    loadFeed();
  }, [loadGoalsAndRail, loadFeed]);

  const runNow = async (goal: AutopilotGoal) => {
    setBusyGoal(goal.id);
    setNotice(null);
    try {
      const result = await runGoal(goal.id);
      setNotice(
        result.findings.length
          ? t("autopilot.notice.found", { count: result.findings.length })
          : t("autopilot.notice.quiet")
      );
      reload();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusyGoal(null);
    }
  };

  const togglePause = async (goal: AutopilotGoal) => {
    await patchGoal(goal.id, { status: goal.status === "active" ? "paused" : "active" }).catch(
      (err) => setNotice(apiDetail(err))
    );
    reload();
  };

  const feedback = async (
    findingId: string,
    kind: "more_like_this" | "hide_like_this"
  ) => {
    try {
      const result = await sendFindingFeedback(findingId, kind);
      setNotice(
        result.goal_paused
          ? t("autopilot.notice.goalPaused")
          : result.learned_terms.length
            ? t("autopilot.notice.learned", { terms: result.learned_terms.join(", ") })
            : null
      );
      reload();
    } catch (err) {
      setNotice(apiDetail(err));
    }
  };

  const selectedGoal = goalParam ? (goals ?? []).find((g) => g.id === goalParam) ?? null : null;
  const groupedByRun = useMemo(() => {
    if (view !== "byrun") return [];
    const groups = new Map<string, AutopilotFindingFeedItem[]>();
    for (const item of feed?.items ?? []) {
      const bucket = groups.get(item.run_id) ?? [];
      bucket.push(item);
      groups.set(item.run_id, bucket);
    }
    return [...groups.entries()];
  }, [view, feed]);
  const chips = useMemo(() => findingsFilterChips(filters, t), [filters, t]);

  if (runParam) {
    return <Navigate to={`/autopilot/runs/${runParam}`} replace />;
  }

  return (
    <div
      className="ca-stats-page space-y-4"
      data-testid="autopilot-page"
      data-band={band}
      ref={bandRef}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Bot className="h-6 w-6 text-primary-600" /> {t("autopilot.title")}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {t("autopilot.subtitle")}
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
          data-testid="new-goal"
        >
          <Sparkles className="mr-1 h-4 w-4" /> {t("autopilot.newGoal")}
        </Button>
      </div>

      <AiSetupPrompt variant="banner" />

      {notice && (
        <div
          className="rounded-xl border border-[var(--as-border)] bg-[var(--as-muted)] px-4 py-2 text-sm text-slate-700"
          data-testid="autopilot-notice"
        >
          {notice}
        </div>
      )}

      {goals !== null && goals.length === 0 ? (
        <EmptyState
          title={t("autopilot.emptyTitle")}
          description={t("autopilot.emptyBody")}
          action={
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setModalOpen(true);
              }}
            >
              {t("autopilot.emptyAction")}
            </Button>
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5" data-testid="goal-switcher">
            <button
              type="button"
              aria-pressed={!goalParam}
              onClick={() => writeFilters({ ...filters, goal: null })}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                !goalParam
                  ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                  : "border-[var(--as-border)] text-slate-600 hover:bg-slate-50"
              }`}
              data-testid="goal-chip-all"
            >
              {t("autopilot.workspace.allGoals")}
            </button>
            {(goals ?? []).map((goal) => (
              <button
                key={goal.id}
                type="button"
                aria-pressed={goalParam === goal.id}
                onClick={() =>
                  writeFilters({
                    ...filters,
                    goal: goalParam === goal.id ? null : goal.id,
                  })
                }
                className={`max-w-[280px] truncate rounded-full border px-3 py-1 text-xs transition-colors ${
                  goalParam === goal.id
                    ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                    : "border-[var(--as-border)] text-slate-600 hover:bg-slate-50"
                }`}
                data-testid={`goal-chip-${goal.id}`}
                title={goal.goal_text}
              >
                {goal.goal_text}
              </button>
            ))}
          </div>

          {selectedGoal ? (
            <div
              className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
              data-testid={`goal-card-${selectedGoal.id}`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 flex-1 text-sm font-medium text-slate-900">
                  {selectedGoal.goal_text}
                </p>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
                    selectedGoal.status === "active"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-amber-50 text-amber-700"
                  }`}
                >
                  {t(`autopilot.status.${selectedGoal.status}`, {
                    defaultValue: selectedGoal.status,
                  })}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {constraintChips(selectedGoal).map((chip) => (
                  <span
                    key={chip}
                    className="rounded-full bg-[var(--as-muted)] px-2 py-0.5 text-xs text-[var(--as-muted-fg)]"
                  >
                    {chip}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
                {cadenceLabel(selectedGoal)}
                {selectedGoal.last_run
                  ? ` · ${t("autopilot.lastRun", {
                      date: dateLabel(selectedGoal.last_run.created_at),
                    })}`
                  : ""}
                {selectedGoal.open_findings
                  ? ` · ${t("autopilot.openCount", { count: selectedGoal.open_findings })}`
                  : ""}
              </p>
              <div className="mt-3 flex items-center gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busyGoal === selectedGoal.id || selectedGoal.status !== "active"}
                  onClick={() => void runNow(selectedGoal)}
                  data-testid={`run-now-${selectedGoal.id}`}
                >
                  {busyGoal === selectedGoal.id
                    ? t("autopilot.searching")
                    : t("autopilot.runNow")}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={
                    selectedGoal.status === "active"
                      ? t("autopilot.pauseGoal")
                      : t("autopilot.resumeGoal")
                  }
                  title={
                    selectedGoal.status === "active"
                      ? t("autopilot.pauseGoal")
                      : t("autopilot.resumeGoal")
                  }
                  onClick={() => void togglePause(selectedGoal)}
                  data-testid={`pause-goal-${selectedGoal.id}`}
                >
                  {selectedGoal.status === "active" ? (
                    <CirclePause className="h-4 w-4" />
                  ) : (
                    <CirclePlay className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("autopilot.editGoal")}
                  title={t("autopilot.editGoal")}
                  onClick={() => {
                    setEditing(selectedGoal);
                    setModalOpen(true);
                  }}
                  data-testid={`edit-goal-${selectedGoal.id}`}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={t("autopilot.deleteGoal")}
                  title={t("autopilot.deleteGoal")}
                  onClick={() => setDeleting(selectedGoal)}
                  data-testid={`delete-goal-${selectedGoal.id}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : null}

          <div className="ca-stats-cols">
            <FindingsRail
              filters={filters}
              facets={feed?.facets ?? null}
              sources={Object.entries(feed?.facets.source ?? {}).map(([key, count]) => ({
                key,
                label: `${key} (${count})`,
              }))}
              onChange={writeFilters}
              onClear={() =>
                writeFilters({
                  ...DEFAULT_FINDINGS_FILTERS,
                  goal: filters.goal,
                  runId: filters.runId,
                  view: filters.view,
                })
              }
              band={band}
              resultCount={feed?.items.length ?? 0}
            />

            <section className="min-w-0 space-y-3" data-testid="findings-feed">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-slate-500" data-testid="feed-count">
                  {feed
                    ? t("autopilot.workspace.feedCount", { count: feed.items.length })
                    : ""}
                </p>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1 text-xs text-slate-500">
                    {t("autopilot.workspace.sortLabel")}
                    <select
                      className="border border-slate-200 rounded px-1.5 py-1 text-xs"
                      value={filters.sort}
                      onChange={(e) =>
                        writeFilters({
                          ...filters,
                          sort: e.target.value as FindingsFilters["sort"],
                        })
                      }
                      data-testid="findings-sort"
                    >
                      <option value="newest">{t("autopilot.workspace.sortNewest")}</option>
                      <option value="score">{t("autopilot.workspace.sortScore")}</option>
                    </select>
                  </label>
                  <SegmentedRow
                    label={t("autopilot.workspace.viewLabel")}
                    value={view}
                    options={[
                      { value: "flat", label: t("autopilot.workspace.viewFlat") },
                      { value: "byrun", label: t("autopilot.workspace.viewByRun") },
                    ]}
                    onChange={(value) =>
                      writeFilters({
                        ...filters,
                        view: value as FindingsFilters["view"],
                        latest: value !== "byrun",
                      })
                    }
                  />
                </div>
              </div>

              <ActiveFilterChips
                chips={chips}
                onRemove={(key) => {
                  const chip = chips.find((entry) => entry.key === key);
                  if (chip) writeFilters({ ...filters, ...chip.patch });
                }}
                testId="findings-active-chips"
                chipTestId={(key) => `findings-chip-${key}`}
              />

              {goals !== null && (goals ?? []).length === 0 ? null : feed === null ? (
                <div className="flex justify-center py-16">
                  <Spinner />
                </div>
              ) : feed.items.length === 0 ? (
                countActiveFindingsFilters(filters) > 0 ? (
                  <EmptyState
                    title={t("autopilot.workspace.emptyFilteredTitle")}
                    description={t("autopilot.workspace.emptyFilteredBody")}
                    action={
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          writeFilters({
                            ...DEFAULT_FINDINGS_FILTERS,
                            goal: filters.goal,
                            runId: filters.runId,
                            view: filters.view,
                          })
                        }
                        data-testid="feed-clear-filters"
                      >
                        {t("filters.clearAll")}
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    title={t("autopilot.noRunsTitle")}
                    description={t("autopilot.noRunsBody")}
                  />
                )
              ) : view === "byrun" ? (
                groupedByRun.map(([runId, items]) => (
                  <div key={runId} className="space-y-2" data-testid={`feed-run-group-${runId}`}>
                    <div className="flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
                      <span
                        className={`rounded-full px-2 py-0.5 ${
                          RUN_STATUS_STYLE[items[0].run_status] ?? "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {items[0].run_status}
                      </span>
                      <span>{dateLabel(items[0].created_at)}</span>
                      <span className="truncate">{items[0].goal_text}</span>
                    </div>
                    {items.map((item) => (
                      <AutopilotFindingCard
                        key={item.id}
                        item={item}
                        onFeedback={(id, kind) => void feedback(id, kind)}
                        onOpenRun={() => setPeekRunId(item.run_id)}
                      />
                    ))}
                  </div>
                ))
              ) : (
                feed.items.map((item) => (
                  <AutopilotFindingCard
                    key={item.id}
                    item={item}
                    onFeedback={(id, kind) => void feedback(id, kind)}
                    onOpenRun={() => setPeekRunId(item.run_id)}
                  />
                ))
              )}

              {feed?.next_cursor ? (
                <div className="flex justify-center">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => loadFeed(feed.next_cursor ?? undefined)}
                    data-testid="feed-load-more"
                  >
                    {t("autopilot.workspace.loadMore")}
                  </Button>
                </div>
              ) : null}
            </section>

            <RunsRail runs={rail} open={runsOpen} onToggle={() => setRunsOpen((v) => !v)} />
          </div>
        </>
      )}

      <GoalModal
        open={modalOpen}
        goal={editing}
        onClose={() => setModalOpen(false)}
        onSaved={reload}
      />

      {peekRunId && <RunDetailModal runId={peekRunId} onClose={() => setPeekRunId(null)} />}

      {deleting && (
        <ConfirmationModal
          open
          title={t("autopilot.deleteTitle")}
          description={t("autopilot.deleteBody")}
          confirmLabel={t("autopilot.delete")}
          onConfirm={() => {
            void deleteGoal(deleting.id).then(() => {
              setDeleting(null);
              if (goalParam === deleting.id) {
                writeFilters({ ...filters, goal: null });
              }
              reload();
            });
          }}
          onOpenChange={(open) => (open ? undefined : setDeleting(null))}
        />
      )}
    </div>
  );
}
