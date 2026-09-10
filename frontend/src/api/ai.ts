import axios from "axios";

import { api, apiDetail } from "./client";

export interface AIProvider {
  id: string;
  name: string;
  scope: "system" | "user";
  user_id: string | null;
  provider_type: "mock" | "openai" | "openai_compatible" | "google";
  api_base: string;
  api_key: string | null;
  is_active: boolean;
  is_local: boolean | null;
  country: string | null;
  is_mine: boolean;
  created_at: string;
}

export interface ProviderPreset {
  name: string;
  type: string;
  base_url: string;
  local: boolean;
}

export async function fetchProviderPresets(): Promise<Record<string, ProviderPreset>> {
  const { data } = await api.get<Record<string, ProviderPreset>>("/ai/providers/presets");
  return data;
}

export interface AIModel {
  id: string;
  provider_id: string;
  name: string;
  model_name: string;
  is_active: boolean;
  temperature: number | null;
  max_tokens: number | null;
  reasoning_effort: string | null;
  caps: string[] | null;
}

export interface AITaskInfo {
  value: string;
  label: string;
  description?: string;
  requires?: string;
  tier?: string;
}

export interface EffectiveAssignment {
  task_type: string;
  source: string;
  provider_type: string;
  model_name: string;
  api_base: string;
}

export interface ConfigSummary {
  tasks: EffectiveAssignment[];
  can_manage_global: boolean;
  mock_allowed: boolean;
}

export interface StoredAssignment {
  id: string;
  task_type: string;
  scope: string;
  model_id: string | null;
  is_active: boolean;
}

export interface AiToolArgument {
  name: string;
  type: string;
  required: boolean;
  description: string | null;
}

export interface AiToolInfo {
  key: string;
  title: string;
  description: string;
  scope: string;
  audiences: string[];
  cost_hint: string | null;
  requires_user: boolean;
  input_schema: {
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  } | null;
  builtin: boolean;
}

export async function fetchAiTools(): Promise<AiToolInfo[]> {
  const { data } = await api.get<AiToolInfo[]>("/ai/tools");
  return data;
}

export async function fetchConfigSummary(): Promise<ConfigSummary> {
  const { data } = await api.get<ConfigSummary>("/ai/config/summary");
  return data;
}

export async function fetchTasks(): Promise<AITaskInfo[]> {
  const { data } = await api.get<AITaskInfo[]>("/ai/tasks");
  return data;
}

export async function fetchProviders(): Promise<AIProvider[]> {
  const { data } = await api.get<AIProvider[]>("/ai/providers");
  return data;
}

export async function createProvider(body: Partial<AIProvider>): Promise<AIProvider> {
  const { data } = await api.post<AIProvider>("/ai/providers", body);
  return data;
}

export async function updateProvider(id: string, body: Partial<AIProvider>): Promise<AIProvider> {
  const { data } = await api.put<AIProvider>(`/ai/providers/${id}`, body);
  return data;
}

export async function deleteProvider(id: string): Promise<void> {
  await api.delete(`/ai/providers/${id}`);
}

export async function fetchModels(providerId: string): Promise<AIModel[]> {
  const { data } = await api.get<AIModel[]>(`/ai/providers/${providerId}/models`);
  return data;
}

export async function addModel(providerId: string, body: Partial<AIModel>): Promise<AIModel> {
  const { data } = await api.post<AIModel>(`/ai/providers/${providerId}/models`, body);
  return data;
}

export async function updateModel(modelId: string, body: Partial<AIModel>): Promise<AIModel> {
  const { data } = await api.put<AIModel>(`/ai/models/${modelId}`, body);
  return data;
}

export async function deleteModel(modelId: string): Promise<void> {
  await api.delete(`/ai/models/${modelId}`);
}

export interface ExternalModel {
  id: string;
  name: string;
  owned_by?: string;
}

export interface ProviderModelInfo extends AIModel {
  provider_name: string;
  provider_scope: "system" | "user";
  provider_type: string;
}

export async function fetchExternalModels(providerId: string): Promise<ExternalModel[]> {
  const { data } = await api.get<ExternalModel[]>(`/ai/providers/${providerId}/fetch-external-models`);
  return data;
}

export async function fetchAllModels(): Promise<ProviderModelInfo[]> {
  const { data } = await api.get<ProviderModelInfo[]>("/ai/models");
  return data;
}

export async function fetchAssignments(scope: "user" | "system"): Promise<StoredAssignment[]> {
  const { data } = await api.get<StoredAssignment[]>("/ai/assignments", { params: { scope } });
  return data;
}

export async function setAssignment(taskType: string, body: { scope: "user" | "system"; model_id: string | null }): Promise<StoredAssignment> {
  const { data } = await api.put<StoredAssignment>(`/ai/assignments/${taskType}`, body);
  return data;
}

export async function testConnection(providerId: string, modelId: string): Promise<{ ok: boolean; reply?: string; error?: string }> {
  const { data } = await api.post("/ai/test", null, { params: { provider_id: providerId, model_id: modelId } });
  return data;
}

export async function transcribeAudio(audio: Blob): Promise<{ text: string }> {
  const form = new FormData();
  form.append("file", audio, "audio.webm");
  const { data } = await api.post<{ text: string }>("/ai/transcribe", form);
  return data;
}

export function classifyDictationError(error: unknown): { kind: "unsupported" | "denied" | "unassigned" | "failed"; detail?: string } {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (status === 503 || status === 409) return { kind: "unassigned" };
    if (status === 404) return { kind: "unassigned" };
    if (status === 422) return { kind: "unsupported" };
  }
  return { kind: "failed", detail: apiDetail(error) };
}
