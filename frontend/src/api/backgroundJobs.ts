import { api } from "./client";

export interface BackgroundJob {
  id: string;
  job_type: "document_parse" | "job_generate" | "match_score" | "data_export";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number;
  stage: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
  payload: Record<string, unknown> | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export const TERMINAL_STATUSES = ["succeeded", "failed", "cancelled"] as const;

export function isTerminal(job: BackgroundJob): boolean {
  return (TERMINAL_STATUSES as readonly string[]).includes(job.status);
}

export async function fetchBackgroundJob(id: string): Promise<BackgroundJob> {
  const { data } = await api.get<BackgroundJob>(`/background-jobs/${id}`);
  return data;
}

export async function fetchBackgroundJobs(params: Record<string, unknown> = {}): Promise<BackgroundJob[]> {
  const { data } = await api.get<BackgroundJob[]>("/background-jobs", { params });
  return data;
}

export async function cancelBackgroundJob(id: string): Promise<BackgroundJob> {
  const { data } = await api.post<BackgroundJob>(`/background-jobs/${id}/cancel`);
  return data;
}

export async function requestExport(): Promise<string> {
  const { data } = await api.post<{ job_id: string }>("/me/export");
  return data.job_id;
}

export async function deleteAccount(password: string): Promise<void> {
  await api.delete("/me", { data: { password } });
}

export async function downloadExport(id: string): Promise<void> {
  const response = await api.get(`/background-jobs/${id}/download`, {
    responseType: "blob",
  });
  const disposition: string = response.headers["content-disposition"] ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const url = URL.createObjectURL(response.data as Blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = match?.[1] ?? "career-assistant-export.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
