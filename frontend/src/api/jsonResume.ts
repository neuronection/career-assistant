import { api } from "@/api/client";

export interface JsonResumeReport {
  mapped: {
    basics: Record<string, unknown>;
    work: Record<string, unknown>[];
    education: Record<string, unknown>[];
    skills: string[];
  };
  dropped: string[];
  warnings: string[];
  basics_conflicts: { field: string; current: unknown; incoming: unknown }[];
  applied: boolean;
  created: { work: number; education: number };
}

export async function exportJsonResume(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>("/profile/export/jsonresume");
  return data;
}

export async function importJsonResume(
  resume: Record<string, unknown>,
  apply = false
): Promise<JsonResumeReport> {
  const { data } = await api.post<JsonResumeReport>("/profile/import/jsonresume", {
    resume,
    apply,
  });
  return data;
}
