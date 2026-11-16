import { api } from "@/api/client";

export interface InterviewStory {
  id: string;
  title: string;
  competency_keys: string[];
  situation: string;
  task: string;
  action: string;
  result: string;
  experience_item_id: string | null;
  evidence_refs: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
}

export interface StorySuggestion {
  experience_item_id: string;
  title: string;
  org: string;
  hint: string;
}

export interface StoryInput {
  title: string;
  competency_keys?: string[];
  situation?: string;
  task?: string;
  action?: string;
  result?: string;
  experience_item_id?: string | null;
}

export async function fetchStories(): Promise<InterviewStory[]> {
  const { data } = await api.get<InterviewStory[]>("/me/interview/stories");
  return data;
}

export async function fetchStorySuggestions(): Promise<StorySuggestion[]> {
  const { data } = await api.get<StorySuggestion[]>("/me/interview/stories/suggestions");
  return data;
}

export async function createStory(body: StoryInput): Promise<InterviewStory> {
  const { data } = await api.post<InterviewStory>("/me/interview/stories", body);
  return data;
}

export async function updateStory(
  id: string,
  body: Partial<StoryInput>,
): Promise<InterviewStory> {
  const { data } = await api.patch<InterviewStory>(`/me/interview/stories/${id}`, body);
  return data;
}

export async function deleteStory(id: string): Promise<void> {
  await api.delete(`/me/interview/stories/${id}`);
}
