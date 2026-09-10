import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAIGenerations, type AIGenerationRow } from "@/api/admin";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";

const TASKS = [
  "",
  "job_generate",
  "match_score",
  "university_parse",
  "profile_analyze",
  "relation_suggest",
  "chat",
  "assist",
];

/** Admin audit viewer for the ai_generations trail. */
export function AIAudit() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AIGenerationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [task, setTask] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = { limit: 100 };
      if (task) params.task = task;
      if (status) params.status = status;
      const result = await fetchAIGenerations(params);
      setRows(result.items);
      setTotal(result.total);
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, [task, status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-4" data-testid="settings-ai-audit">
      <div className="flex gap-2 flex-wrap">
        <select
          value={task}
          onChange={(e) => setTask(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white"
        >
          {TASKS.map((task) => (
            <option key={task} value={task}>
              {task === ""
                ? t("aiSettings.allTasks")
                : t(`aiSettings.task.${task}`, {
                    defaultValue: task.replace("_", " "),
                  })}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">{t("aiSettings.allStatuses")}</option>
          <option value="ok">{t("aiSettings.status.ok")}</option>
          <option value="error">{t("aiSettings.status.error")}</option>
        </select>
        <span className="text-sm text-slate-400 self-center">
          {t("aiSettings.generationCount", { count: total })}
        </span>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">{t("common.loading")}</p>
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={t("aiSettings.noGenerations")} />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <div
              key={row.id}
              className="bg-white border border-slate-200 rounded-xl p-3 text-sm"
            >
              <button
                className="w-full text-left flex items-center gap-3 flex-wrap"
                onClick={() => setExpanded(expanded === row.id ? null : row.id)}
              >
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    row.status === "ok"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-rose-50 text-rose-700"
                  }`}
                >
                  {t(`aiSettings.status.${row.status}`, { defaultValue: row.status })}
                </span>
                <span className="font-medium">
                  {t(`aiSettings.task.${row.task_type}`, {
                    defaultValue: row.task_type.replace("_", " "),
                  })}
                </span>
                <span className="text-slate-400 text-xs">
                  {row.provider}/{row.model}
                </span>
                <span className="text-slate-400 text-xs">
                  {t("aiSettings.tokens", {
                    input: row.tokens_in ?? "?",
                    output: row.tokens_out ?? "?",
                  })}
                  {row.latency_ms != null && ` · ${Math.round(row.latency_ms)}ms`}
                </span>
                <span className="text-slate-400 text-xs ml-auto">
                  {new Date(row.created_at).toLocaleString()}
                </span>
              </button>
              {expanded === row.id && (
                <div className="mt-2 border-t border-slate-100 pt-2 space-y-1">
                  <p className="text-xs text-slate-400">
                    {t("aiSettings.promptLabel")} {row.prompt.slice(0, 300) || "—"}
                  </p>
                  {row.error && <p className="text-xs text-rose-600">{row.error}</p>}
                  {row.output && (
                    <pre className="text-xs bg-slate-50 rounded-lg p-2 overflow-x-auto max-h-60">
                      {JSON.stringify(row.output, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
