import { api } from "@/api/client";

export interface SavedAnswer {
  id: string;
  question_key: string;
  question_text: string;
  answer_text: string;
  evidence_refs: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
}

export async function saveAnswer(payload: {
  question_key: string;
  question_text: string;
  answer_text: string;
}): Promise<SavedAnswer> {
  const { data } = await api.post<SavedAnswer>("/me/answers", payload);
  return data;
}

export async function deleteAnswer(id: string): Promise<void> {
  await api.delete(`/me/answers/${id}`);
}
