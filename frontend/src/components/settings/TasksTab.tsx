import { useEffect, useMemo, useState } from "react";
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
  title: "Task Assignments",
  global: "Global",
  personal: "Personal",
  fallbackSection: "Fallback model",
  fallbackSectionHint: "Used by every task without its own assignment in this scope.",
  fallbackRow: "All tasks",
  fallbackInfo: "This model serves every task that has no assignment in this scope.",
  tasksSection: "Per-task assignments",
  tasksSectionHint: "Overrides the fallback model above for that task.",
  unassignedMeta: "Unassigned — falls back to the fallback model above.",
  clearLabel: "Clear assignment",
  nonAdminNote:
    "Global assignments are managed by an administrator; set personal overrides to customize your own AI models.",
};

const TASK_LABELS: Record<string, string> = {
  profile_analyze: "Profile Analysis & Guidance",
  job_generate: "Job Generation",
  relation_suggest: "Job Relation Suggestions",
  match_score: "Job Match Scoring",
  university_parse: "University PDF Parsing",
  chat: "Career Assistant Chat",
  assist: "Contextual Ask-AI Buttons",
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
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<Scope>(canManageGlobal ? "system" : "user");
  const [tasks, setTasks] = useState<string[]>([]);
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
      setTasks(taskRows.map((t) => t.value));
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
        capabilities: guessCaps(m.model_name),
      });
      groups.set(m.provider_id, provider);
    }
    return [...groups.values()];
  }, [modelsForScope]);

  const assignmentFor = (taskType: string) =>
    assignments.find((a) => a.task_type === taskType && a.is_active);

  const value: Record<string, string | null> = {};
  const secondaryValue: Record<string, string | null> = {};
  for (const taskType of tasks) {
    value[taskType] = assignmentFor(taskType)?.model_id ?? null;
  }
  secondaryValue.default = value.default;

  const sections: TaskAssignmentSection[] = useMemo(() => {
    const fallbackTask = tasks.find((t) => t === "default");
    const rest = tasks.filter((t) => t !== "default");
    return [
      {
        id: "fallback",
        label: STRINGS.fallbackSection,
        description: STRINGS.fallbackSectionHint,
        tasks: fallbackTask
          ? [{ id: fallbackTask, label: STRINGS.fallbackRow, secondaryOnly: true, icon: TASK_ICONS.default }]
          : [],
      },
      {
        id: "tasks",
        label: STRINGS.tasksSection,
        description: STRINGS.tasksSectionHint,
        tasks: rest.map((taskType) => ({
          id: taskType,
          label: TASK_LABELS[taskType] ?? beautifyId(taskType.replace(/_/g, " ")),
          icon: TASK_ICONS[taskType],
        })),
      },
    ];
  }, [tasks]);

  return (
    <div className="space-y-4" data-testid="tasks-tab">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-slate-900">{STRINGS.title}</h3>
        <div className="flex rounded-lg border border-slate-200 overflow-hidden">
          {(["system", "user"] as Scope[]).map((s) => (
            <button
              key={s}
              onClick={() => setScope(s)}
              disabled={s === "system" && !canManageGlobal}
              className={`text-xs px-3 py-1.5 flex items-center gap-1 disabled:opacity-40 ${
                scope === s ? "bg-primary-600 text-white" : "bg-white"
              }`}
            >
              {s === "system" ? <Globe className="w-3 h-3" /> : <User className="w-3 h-3" />}
              {s === "system" ? STRINGS.global : STRINGS.personal}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      <TaskAssignmentPicker
        sections={sections}
        providers={catalog}
        value={value}
        secondaryValue={secondaryValue}
        onAssign={(taskType, modelId) => void assign(taskType, modelId)}
        onAssignSecondary={(taskType, modelId) => void assign(taskType, modelId)}
        fallbackInfo={STRINGS.fallbackInfo}
        clearLabel={STRINGS.clearLabel}
        disabled={busy}
        renderMeta={(task) =>
          task.id !== "default" && !value[task.id] ? (
            <p className="text-[11px] text-slate-400">{STRINGS.unassignedMeta}</p>
          ) : null
        }
      />

      {!user?.is_admin && (
        <p className="text-xs text-slate-400">{STRINGS.nonAdminNote}</p>
      )}
    </div>
  );
}
