import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Briefcase,
  Braces,
  Check,
  Crosshair,
  Database,
  Eye,
  FileSearch,
  Gauge,
  Globe,
  GraduationCap,
  ListChecks,
  Map as MapIcon,
  MessageSquare,
  Mic,
  Network,
  Route,
  Sparkles,
  Target,
  User,
  UserSearch,
  Volume2,
  X,
  type LucideIcon,
} from "lucide-react";
import * as aiApi from "@/api/ai";
import type { ProviderModelInfo } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";
import { ModelPicker, TaskAssignmentPicker } from "@/components/ui";
import type { ModelPickerProvider, TaskAssignmentSection } from "@neuronection/assistant-ui";
import { beautifyId } from "@neuronection/assistant-ui/fuzzy";
import { guessCaps } from "@/lib/aiCaps";

const STRINGS = {
  title: "aiSettings.tasks.title",
  global: "aiSettings.tasks.global",
  personal: "aiSettings.tasks.personal",
  defaultsSection: "aiSettings.tasks.defaultModelsTitle",
  defaultsSectionHint: "aiSettings.tasks.defaultModelsHint",
  kindsSection: "aiSettings.tasks.decisionKindsTitle",
  kindsSectionHint: "aiSettings.tasks.decisionGroupPrivacy",
  decisionDefaultLabel: "aiSettings.decisionDefaultLabel",
  inheritsLabel: "aiSettings.decisionInheritsLabel",
  inheritsEmpty: "aiSettings.decisionInheritsEmpty",
  defaultsEmptyHint: "aiSettings.decisionDefaultsEmptyHint",
  inheritsWithModel: "aiSettings.decisionInheritsLabel",
  simplify: "aiSettings.decisionSimplifyUseAsDefault",
  suggestedDecisionDefault: "aiSettings.tasks.suggestedDecisionDefault",
  tasksSection: "aiSettings.tasks.tasksSection",
  tasksSectionHint: "aiSettings.tasks.tasksSectionHint",
  unassignedMeta: "aiSettings.tasks.unassignedMeta",
  scopeEmpty: "aiSettings.tasks.scopeEmpty",
  clearLabel: "aiSettings.tasks.clearLabel",
  nonAdminNote: "aiSettings.tasks.nonAdminNote",
};

const SLOT_ICONS: Record<string, LucideIcon> = {
  text: ListChecks,
  vision: Eye,
  stt: Mic,
  tts: Volume2,
  embeddings: Database,
};

const DECISION_DEFAULT_TASK_TYPE = "decision"; // ADR-0036: the decision default slot
const DECISION_KIND_META: Record<string, { id: string; icon: LucideIcon }> = {
  decision_tool_dispatch: { id: "tool-dispatch", icon: Braces },
  decision_boolean_gate: { id: "boolean-gate", icon: Check },
  decision_choice: { id: "choice", icon: ListChecks },
  decision_score: { id: "score", icon: Gauge },
};

/** One Decision kinds group row (plan 29 / ADR-0036 D4, uniform ruling):
 * composed app-side from the library `ModelPicker` — single picker, no
 * explicit inherit option: an unset kind simply *is* the inherit state.
 * The trigger reads a short muted "Inherited"; the meta line carries the
 * detail (what it defaults to). Clearing (X) returns the kind to inherit.
 * `TaskAssignmentPicker` untouched. Career kind rows are single-picker
 * (career has no per-assignment fallback concept — ADR-0037 natively).
 */
function DecisionKindRow({
  label,
  description,
  icon: Icon,
  catalog,
  modelValue,
  placeholder,
  clearLabel,
  disabled,
  meta,
  onAssign,
}: {
  label: string
  description: string
  icon: LucideIcon
  catalog: ModelPickerProvider[]
  modelValue: string | null
  placeholder: string
  clearLabel: string
  disabled: boolean
  meta?: ReactNode
  onAssign: (modelId: string | null) => void
}) {
  return (
    <div className="flex flex-col gap-2 rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--as-radius)] bg-[var(--as-muted)] text-[var(--as-muted-fg)]">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-[var(--as-fg)]">{label}</p>
          <p className="truncate text-xs text-[var(--as-muted-fg)]">{description}</p>
          {meta ?? null}
        </div>
      </div>
      <div className="flex items-center gap-1.5 self-center">
        <ModelPicker
          providers={catalog}
          value={modelValue ?? ''}
          placeholder={placeholder}
          onChange={(modelId: string | null) => onAssign(modelId)}
          disabled={disabled}
          clearable={false}
          label={label}
          hideLabel
          className="w-56"
        />
        {modelValue ? (
          <button
            type="button"
            aria-label={`${clearLabel} — ${label}`}
            disabled={disabled}
            onClick={() => onAssign(null)}
            className="cursor-pointer rounded-[var(--as-radius-sm)] p-1.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-focus-ring)] disabled:pointer-events-none disabled:opacity-50"
          >
            <X className="size-4" aria-hidden />
          </button>
        ) : null}
      </div>
    </div>
  );
}

const TASK_ICONS: Record<string, LucideIcon> = {
  assessment_generate: ListChecks,
  profile_analyze: UserSearch,
  job_generate: Briefcase,
  relation_suggest: Network,
  match_score: Target,
  university_parse: GraduationCap,
  chat: MessageSquare,
  assist: Sparkles,
  path_suggest: Route,
  posting_map: MapIcon,
  posting_extract: FileSearch,
  target_resolve: Crosshair,
  cv_ocr: Eye,
  cv_parse: ListChecks,
  cv_template_design: ListChecks,
  cv_template_review: Eye,
  cv_template_pick: ListChecks,
  cv_build_review: Eye,
  cv_suggest: ListChecks,
  cv_cover_letter: ListChecks,
  cv_builder_chat: ListChecks,
  cv_draft: ListChecks,
  cv_synth: ListChecks,
  catalog_enrich: Database,
  chat_title: MessageSquare,
  chat_ops: MessageSquare,
  autopilot_run: Braces,
  transcribe: Mic,
  interview_plan: ListChecks,
  interview_turn: MessageSquare,
  interview_debrief: ListChecks,
  embed: Database,
  mcp_tool_call: Braces,
};

const DECISION_TASK_PREFIX = "decision_";

type Scope = "system" | "user";

interface TasksTabProps {
  canManageGlobal: boolean;
  onChanged: () => void;
}

/** Task → model assignments on the family TaskAssignmentPicker, §15
 * defaults-first: capability-slot defaults (text/vision/stt/tts/
 * embeddings) lead, the Decision group (decision:* slots, primary) is
 * second, concrete tasks follow — every row a per-task override. */
export function TasksTab({ canManageGlobal, onChanged }: TasksTabProps) {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<Scope>(canManageGlobal ? "system" : "user");
  const [taskRows, setTaskRows] = useState<aiApi.AITaskInfo[]>([]);
  const [allModels, setAllModels] = useState<ProviderModelInfo[]>([]);
  const [assignments, setAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [presets, setPresets] = useState<Record<string, aiApi.ProviderPreset>>({});

  /** The family's basic decision default: the first canonical preset
   * declaring one — a display-level suggestion, never an assignment. */
  const decisionSuggestion = (() => {
    for (const preset of Object.values(presets)) {
      if (preset.decision_default) {
        return { model: preset.decision_default, provider: preset.name };
      }
    }
    return null;
  })();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setScope(canManageGlobal ? "system" : "user");
  }, [canManageGlobal]);

  const refresh = async () => {
    setError("");
    try {
      const [taskRows, modelRows, assignmentRows, presetRows] = await Promise.all([
        aiApi.fetchTasks(),
        aiApi.fetchAllModels(),
        aiApi.fetchAssignments(scope).catch(() => [] as aiApi.StoredAssignment[]),
        aiApi.fetchProviderPresets().catch(() => ({})),
      ]);
      setPresets(presetRows);
      setTaskRows(taskRows);
      setAllModels(modelRows);
      setAssignments(assignmentRows);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const assign = async (taskType: string, modelId: string | null) => {
    setError("");
    setBusy(true);
    try {
      await aiApi.setAssignment(taskType, { scope, model_id: modelId });
      await refresh();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const modelsForScope = useMemo(
    () => allModels.filter((m) => m.provider_scope === scope),
    [allModels, scope],
  );

  const catalog: ModelPickerProvider[] = useMemo(() => {
    const groups = new Map<string, ModelPickerProvider>();
    for (const m of modelsForScope) {
      const provider = groups.get(m.provider_id) ?? { id: m.provider_id, name: m.provider_name, models: [] };
      provider.models.push({
        id: m.id,
        name: m.name || beautifyId(m.model_name),
        capabilities: m.caps ?? guessCaps(m.model_name),
      });
      groups.set(m.provider_id, provider);
    }
    return [...groups.values()];
  }, [modelsForScope]);

  const assignmentFor = (taskType: string) =>
    assignments.find((a) => a.task_type === taskType && a.is_active);

  const value: Record<string, string | null> = {};
  for (const task of taskRows) {
    value[task.value] = assignmentFor(task.value)?.model_id ?? null;
  }

  // ADR-0036 §4: what a kind's labeled null option names — the `decision`
  // default row's model (career's kind rows are single-picker; the
  // transport declares all four kinds).
  const decisionKindRows = taskRows.filter(
    (t) => !t.is_slot && t.value.startsWith(DECISION_TASK_PREFIX),
  );
  const modelLabelOf = (modelId: string | null): string | null => {
    if (!modelId) return null;
    return (
      allModels.find((m) => m.id === modelId)?.name ??
      allModels.find((m) => m.id === modelId)?.model_name ??
      null
    );
  };
  const decisionDefaultId = value[DECISION_DEFAULT_TASK_TYPE] ?? null;
  const decisionDefaultLabel = modelLabelOf(decisionDefaultId);

  // D7 "Simplify": only when all four kinds resolve to one model and the
  // default is empty — a suggestion, never automatic.
  let simplifyModelId: string | null = null;
  if (!decisionDefaultId) {
    let resolved: string | null = null;
    let uniform = true;
    for (const row of decisionKindRows) {
      const kindModel = value[row.value] ?? null;
      if (!kindModel) {
        uniform = false;
        break;
      }
      if (resolved === null) {
        resolved = kindModel;
      } else if (resolved !== kindModel) {
        uniform = false;
        break;
      }
    }
    if (uniform && resolved !== null) {
      simplifyModelId = resolved;
    }
  }

  const kindsGroup = (
    <div className="flex flex-col gap-2">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t(STRINGS.kindsSection)}
        </p>
        <p className="mt-0.5 text-xs text-slate-500">{t(STRINGS.kindsSectionHint)}</p>
      </div>
      {decisionKindRows.map((row) => {
        const meta = DECISION_KIND_META[row.value];
        return (
          <DecisionKindRow
            key={row.value}
            label={t(`aiSettings.decisionSlots.${row.value.slice(DECISION_TASK_PREFIX.length)}`, {
              defaultValue: beautifyId(row.value.replace(/_/g, " ")),
            })}
            description={t(
              `aiSettings.decisionSlots.${row.value.slice(DECISION_TASK_PREFIX.length)}Description`
            )}
            icon={meta?.icon ?? Sparkles}
            catalog={catalog}
            modelValue={value[row.value] ?? null}
            placeholder={t("aiSettings.decisionInherited")}
            clearLabel={t(STRINGS.clearLabel)}
            disabled={busy}
            meta={
              <>
                {decisionDefaultId && decisionDefaultLabel ? (
                  <p className="text-[11px] text-slate-400">
                    {t("aiSettings.decisionDefaultsTo", {
                      model: decisionDefaultLabel,
                    })}
                  </p>
                ) : null}
                {!value[row.value] && decisionSuggestion && !decisionDefaultId ? (
                  <p className="text-[11px] text-slate-400">
                    {t("aiSettings.tasks.suggestedDecisionDefault", {
                      model: decisionSuggestion.model,
                      provider: decisionSuggestion.provider,
                    })}
                  </p>
                ) : null}
              </>
            }
            onAssign={(modelId) => void assign(row.value, modelId)}
          />
        );
      })}
    </div>
  );

  const sections: TaskAssignmentSection[] = useMemo(() => {
    const slots = taskRows.filter((t) => t.is_slot);
    const decisionDefaultRow = taskRows.find((t) => t.value === DECISION_DEFAULT_TASK_TYPE);
    const rest = taskRows.filter(
      (t) => !t.is_slot && !t.value.startsWith(DECISION_TASK_PREFIX) && t.value !== DECISION_DEFAULT_TASK_TYPE,
    );
    // Uniform shape (plan 29 owner ruling + ADR-0037): the decision
    // default row rides the "Default models" section like every other
    // default; the four kind rows leave the picker for the quiet
    // "Decision kinds" group below.
    const defaultsTasks: TaskAssignmentSection["tasks"] = slots.map((slot) => ({
      id: slot.value,
      label: t(`aiSettings.caps.${slot.value}`, { defaultValue: slot.label }),
      requires: slot.value,
      icon: SLOT_ICONS[slot.value],
      secondaryOnly: true,
    }));
    if (decisionDefaultRow) {
      defaultsTasks.push({
        id: decisionDefaultRow.value,
        label: t(STRINGS.decisionDefaultLabel),
        requires: "decision",
        icon: Sparkles,
        secondaryOnly: true,
      });
    }
    return [
      {
        id: "defaults",
        label: t(STRINGS.defaultsSection),
        description: t(STRINGS.defaultsSectionHint),
        tasks: defaultsTasks,
      },
      {
        id: "tasks",
        label: t(STRINGS.tasksSection),
        description: t(STRINGS.tasksSectionHint),
        tasks: rest.map((task) => ({
          id: task.value,
          label: t(`aiSettings.taskLabel.${task.value}`, {
            defaultValue: beautifyId(task.value.replace(/_/g, " ")),
          }),
          description: task.description,
          requires: task.requires,
          icon: TASK_ICONS[task.value],
        })),
      },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskRows, t]);

  return (
    <div className="space-y-4" data-testid="tasks-tab">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-slate-900">{t(STRINGS.title)}</h3>
        {canManageGlobal && (
          <div className="flex rounded-lg border border-slate-200 overflow-hidden">
            {(["system", "user"] as Scope[]).map((s) => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={`text-xs px-3 py-1.5 flex items-center gap-1 ${
                  scope === s ? "bg-primary-600 text-white" : "bg-white"
                }`}
              >
                {s === "system" ? <Globe className="w-3 h-3" /> : <User className="w-3 h-3" />}
                {s === "system" ? t(STRINGS.global) : t(STRINGS.personal)}
              </button>
            ))}
          </div>
        )}
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {modelsForScope.length === 0 && (
        <p className="text-sm text-slate-500" data-testid="tasks-scope-empty">
          {t(STRINGS.scopeEmpty)}
        </p>
      )}

      <TaskAssignmentPicker
        sections={sections}
        providers={catalog}
        value={value}
        onAssign={(taskType, modelId) => void assign(taskType, modelId)}
        clearLabel={t(STRINGS.clearLabel)}
        disabled={busy}
        renderMeta={(task) =>
          task.id === DECISION_DEFAULT_TASK_TYPE && !value[task.id] ? (
            <div className="space-y-1">
              <p className="text-[11px] text-slate-400">{t(STRINGS.defaultsEmptyHint)}</p>
              {decisionSuggestion ? (
                <p className="text-[11px] text-slate-400">
                  {t("aiSettings.tasks.suggestedDecisionDefault", {
                    model: decisionSuggestion.model,
                    provider: decisionSuggestion.provider,
                  })}
                </p>
              ) : null}
              {simplifyModelId ? (
                <button
                  type="button"
                  className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
                  disabled={busy}
                  onClick={() => void assign(DECISION_DEFAULT_TASK_TYPE, simplifyModelId)}
                >
                  {t(STRINGS.simplify, {
                    model: modelLabelOf(simplifyModelId) ?? simplifyModelId,
                  })}
                </button>
              ) : null}
            </div>
          ) : task.id.startsWith(DECISION_TASK_PREFIX) && !value[task.id] ? (
            <p className="text-[11px] text-slate-400">
              {t("aiSettings.tasks.decisionUnassignedMeta")}
            </p>
          ) : !value[task.id] ? (
            <p className="text-[11px] text-slate-400">{t(STRINGS.unassignedMeta)}</p>
          ) : null
        }
      />

      {/* Decision kinds group (plan 29 / ADR-0036 uniform ruling): the
          four kind rows with the labeled inherit entry; the privacy
          notice (§13.5) is the section description. */}
      {kindsGroup}

      {!user?.is_admin && (
        <p className="text-xs text-slate-400">{t(STRINGS.nonAdminNote)}</p>
      )}
    </div>
  );
}
