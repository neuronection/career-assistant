import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Anchor,
  Briefcase,
  Crosshair,
  FileSearch,
  Globe,
  GraduationCap,
  ListChecks,
  Map as MapIcon,
  MessageSquare,
  Network,
  Route,
  Sparkles,
  Target,
  User,
  UserSearch,
  type LucideIcon,
} from "lucide-react";
import * as aiApi from "@/api/ai";
import type { ProviderModelInfo } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";
import { TaskAssignmentPicker } from "@/components/ui";
import type { ModelPickerProvider, TaskAssignmentSection } from "@neuronection/assistant-ui";
import { beautifyId } from "@neuronection/assistant-ui/fuzzy";
import { guessCaps } from "@/lib/aiCaps";

const STRINGS = {
  title: "aiSettings.tasks.title",
  global: "aiSettings.tasks.global",
  personal: "aiSettings.tasks.personal",
  fallbackSection: "aiSettings.tasks.fallbackSection",
  fallbackSectionHint: "aiSettings.tasks.fallbackSectionHint",
  fallbackRow: "aiSettings.tasks.fallbackRow",
  fallbackInfo: "aiSettings.tasks.fallbackInfo",
  tasksSection: "aiSettings.tasks.tasksSection",
  tasksSectionHint: "aiSettings.tasks.tasksSectionHint",
  unassignedMeta: "aiSettings.tasks.unassignedMeta",
  scopeEmpty: "aiSettings.tasks.scopeEmpty",
  clearLabel: "aiSettings.tasks.clearLabel",
  nonAdminNote: "aiSettings.tasks.nonAdminNote",
};

const TASK_LABEL_KEYS: Record<string, string> = {
  profile_analyze: "aiSettings.taskLabel.profile_analyze",
  job_generate: "aiSettings.taskLabel.job_generate",
  relation_suggest: "aiSettings.taskLabel.relation_suggest",
  match_score: "aiSettings.taskLabel.match_score",
  university_parse: "aiSettings.taskLabel.university_parse",
  chat: "aiSettings.taskLabel.chat",
  assist: "aiSettings.taskLabel.assist",
};

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
  default: Anchor,
};

type Scope = "system" | "user";

interface TasksTabProps {
  canManageGlobal: boolean;
  onChanged: () => void;
}

/** Task → model assignments on the family TaskAssignmentPicker:
 * the `default` task type is the scope's fallback model (fallback-only row),
 * every other task type gets its own assignment row. */
export function TasksTab({ canManageGlobal, onChanged }: TasksTabProps) {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<Scope>(canManageGlobal ? "system" : "user");
  const [taskRows, setTaskRows] = useState<aiApi.AITaskInfo[]>([]);
  const [allModels, setAllModels] = useState<ProviderModelInfo[]>([]);
  const [assignments, setAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setScope(canManageGlobal ? "system" : "user");
  }, [canManageGlobal]);

  const refresh = async () => {
    setError("");
    try {
      const [taskRows, modelRows, assignmentRows] = await Promise.all([
        aiApi.fetchTasks(),
        aiApi.fetchAllModels(),
        aiApi.fetchAssignments(scope).catch(() => [] as aiApi.StoredAssignment[]),
      ]);
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
  const secondaryValue: Record<string, string | null> = {};
  for (const task of taskRows) {
    value[task.value] = assignmentFor(task.value)?.model_id ?? null;
  }
  secondaryValue.default = value.default;

  const sections: TaskAssignmentSection[] = useMemo(() => {
    const fallbackTask = taskRows.find((t) => t.value === "default");
    const rest = taskRows.filter((t) => t.value !== "default");
    return [
      {
        id: "fallback",
        label: t(STRINGS.fallbackSection),
        description: t(STRINGS.fallbackSectionHint),
        tasks: fallbackTask
          ? [
              {
                id: fallbackTask.value,
                label: t(STRINGS.fallbackRow),
                secondaryOnly: true,
                icon: TASK_ICONS.default,
              },
            ]
          : [],
      },
      {
        id: "tasks",
        label: t(STRINGS.tasksSection),
        description: t(STRINGS.tasksSectionHint),
        tasks: rest.map((task) => ({
          id: task.value,
          label: t(TASK_LABEL_KEYS[task.value] ?? "", {
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
        secondaryValue={secondaryValue}
        onAssign={(taskType, modelId) => void assign(taskType, modelId)}
        onAssignSecondary={(taskType, modelId) => void assign(taskType, modelId)}
        fallbackInfo={t(STRINGS.fallbackInfo)}
        clearLabel={t(STRINGS.clearLabel)}
        disabled={busy}
        renderMeta={(task) =>
          task.id !== "default" && !value[task.id] ? (
            <p className="text-[11px] text-slate-400">{t(STRINGS.unassignedMeta)}</p>
          ) : null
        }
      />

      {!user?.is_admin && (
        <p className="text-xs text-slate-400">{t(STRINGS.nonAdminNote)}</p>
      )}
    </div>
  );
}
