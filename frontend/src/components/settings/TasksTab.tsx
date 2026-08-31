import { useEffect, useMemo, useState } from "react";
import { Cpu, Globe, Search, User, X } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { ProviderModelInfo } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";

interface TasksTabProps {
  canManageGlobal: boolean;
  onChanged: () => void;
}

type Scope = "system" | "user";

const TASK_LABELS: Record<string, string> = {
  default: "Global Default Fallback",
  profile_analyze: "Profile Analysis & Guidance",
  job_generate: "Job Generation",
  relation_suggest: "Job Relation Suggestions",
  match_score: "Job Match Scoring",
  university_parse: "University PDF Parsing",
  chat: "Career Assistant Chat",
  assist: "Contextual Ask-AI Buttons",
};

function fuzzy(text: string, query: string): boolean {
  const cleanText = text.toLowerCase();
  const cleanQuery = query.toLowerCase().trim();
  if (!cleanQuery) return true;
  if (cleanText.includes(cleanQuery)) return true;
  const flatText = cleanText.replace(/[^a-z0-9]/g, "");
  const flatQuery = cleanQuery.replace(/[^a-z0-9]/g, "");
  if (flatText.includes(flatQuery)) return true;
  let textIdx = 0;
  let queryIdx = 0;
  while (textIdx < cleanText.length && queryIdx < flatQuery.length) {
    if (cleanText[textIdx] === flatQuery[queryIdx]) queryIdx++;
    textIdx++;
  }
  return queryIdx === flatQuery.length;
}

/**
 * Task → model assignment cards. Mirrors Health-Assistant TaskAssignment:
 * each task shows "Provider / Model" (or the fallback note); clicking opens
 * an inline grouped, fuzzy-searchable provider→models picker.
 */
export function TasksTab({ canManageGlobal, onChanged }: TasksTabProps) {
  const user = useAuthStore((s) => s.user);
  const [scope, setScope] = useState<Scope>(canManageGlobal ? "system" : "user");
  const [tasks, setTasks] = useState<string[]>([]);
  const [allModels, setAllModels] = useState<ProviderModelInfo[]>([]);
  const [assignments, setAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [openPicker, setOpenPicker] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

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

  const modelsForScope = useMemo(
    () => allModels.filter((m) => m.provider_scope === scope),
    [allModels, scope]
  );

  const grouped = useMemo(() => {
    const groups: Record<string, { providerName: string; models: ProviderModelInfo[] }> = {};
    for (const m of modelsForScope) {
      groups[m.provider_id] = groups[m.provider_id] ?? { providerName: m.provider_name, models: [] };
      groups[m.provider_id].models.push(m);
    }
    return Object.entries(groups).map(([providerId, g]) => ({ providerId, ...g }));
  }, [modelsForScope]);

  const filteredGroups = useMemo(() => {
    if (!search) return grouped;
    return grouped
      .map((g) => ({
        ...g,
        models: g.models.filter(
          (m) => fuzzy(m.name, search) || fuzzy(m.model_name, search) || fuzzy(g.providerName, search)
        ),
      }))
      .filter((g) => g.models.length > 0);
  }, [grouped, search]);

  const assignmentFor = (taskType: string) =>
    assignments.find((a) => a.task_type === taskType && a.is_active);

  const modelById = (modelId?: string | null) =>
    allModels.find((m) => m.id === modelId);

  const assign = async (taskType: string, modelId: string | null) => {
    setError("");
    try {
      await aiApi.setAssignment(taskType, { scope, model_id: modelId });
      setOpenPicker(null);
      setSearch("");
      await refresh();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="tasks-tab">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-slate-900">Task Assignments</h3>
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
              {s === "system" ? "Global" : "Personal"}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="grid grid-cols-1 gap-4">
        {tasks.map((taskType) => {
          const assignment = assignmentFor(taskType);
          const model = modelById(assignment?.model_id);
          const isDefault = taskType === "default";
          const isOpen = openPicker === taskType;
          const canConfigure = scope === "user" || canManageGlobal;

          return (
            <div
              key={taskType}
              className={`p-4 rounded-xl border transition-all group ${
                isDefault
                  ? "bg-primary-50/40 border-primary-200 shadow-sm"
                  : "bg-white border-slate-200 hover:border-primary-300"
              } ${isOpen ? "border-primary-500 ring-1 ring-primary-500/20" : ""}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`p-2 rounded-lg shrink-0 ${
                      isDefault
                        ? "bg-primary-600 text-white"
                        : "bg-primary-50 text-primary-600 group-hover:bg-primary-100"
                    }`}
                  >
                    <Cpu className="w-5 h-5" />
                  </div>
                  <div className="min-w-0">
                    <h4 className={`text-md font-bold flex items-center gap-2 ${isDefault ? "text-primary-900" : "text-slate-900"}`}>
                      <span className="truncate">{TASK_LABELS[taskType] ?? taskType.replace(/_/g, " ")}</span>
                      {isDefault && (
                        <span className="px-2 py-0.5 bg-primary-100 text-primary-700 text-[9px] font-black uppercase tracking-tighter rounded shrink-0">
                          System Fallback
                        </span>
                      )}
                      {assignment?.scope === "user" && (
                        <span className="flex items-center gap-1 px-1.5 py-0.5 bg-emerald-100 text-emerald-700 text-[8px] font-black uppercase tracking-tighter rounded shrink-0">
                          <User className="w-2 h-2" /> Mine
                        </span>
                      )}
                    </h4>
                    {assignment && model ? (
                      <p className={`text-sm font-medium ${isDefault ? "text-primary-600" : "text-primary-600"}`}>
                        {model.provider_name} / {model.name}
                      </p>
                    ) : (
                      <p className="text-sm text-slate-500 italic">
                        Not assigned — will use built-in env default
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {assignment && canConfigure && (
                    <button
                      aria-label={`Clear assignment for ${taskType}`}
                      onClick={() => void assign(taskType, null)}
                      className="p-1.5 text-slate-300 hover:text-rose-600"
                      title="Clear assignment (inherit)"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                  {canConfigure && (
                    <button
                      onClick={() => {
                        setOpenPicker(isOpen ? null : taskType);
                        setSearch("");
                      }}
                      className="text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg font-bold uppercase tracking-wider text-slate-600"
                    >
                      {assignment ? "Change" : "Assign"}
                    </button>
                  )}
                </div>
              </div>

              {isOpen && (
                <div className="mt-3 border-t border-slate-100 pt-3">
                  <div className="relative mb-2">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      autoFocus
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search models…"
                      className="w-full pl-10 pr-4 py-2 bg-slate-50 border border-slate-100 rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary-500/20"
                    />
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {filteredGroups.length === 0 ? (
                      <p className="text-sm text-slate-400 italic text-center py-6">
                        No models in this scope yet — add one in the Models tab.
                      </p>
                    ) : (
                      filteredGroups.map((g) => (
                        <div key={g.providerId} className="mb-2">
                          <div className="px-3 pt-2 pb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
                            {g.providerName}
                          </div>
                          {g.models.map((m) => (
                            <button
                              key={m.id}
                              onClick={() => void assign(taskType, m.id)}
                              className={`w-full text-left px-4 py-2.5 text-sm hover:bg-primary-50 rounded-lg m-0.5 flex items-center justify-between ${
                                assignment?.model_id === m.id ? "bg-primary-50" : ""
                              }`}
                            >
                              <span className="flex flex-col">
                                <span className="font-bold text-slate-700">{m.name}</span>
                                <span className="text-[10px] text-slate-400 uppercase tracking-tighter font-mono">
                                  {m.model_name}
                                </span>
                              </span>
                              {assignment?.model_id === m.id && (
                                <span className="text-[9px] font-black uppercase text-primary-600">assigned</span>
                              )}
                            </button>
                          ))}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {!user?.is_admin && (
        <p className="text-xs text-slate-400">
          Global assignments are managed by an administrator; set personal overrides to customize your own AI models.
        </p>
      )}
    </div>
  );
}
