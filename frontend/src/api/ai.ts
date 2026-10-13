import axios from "axios";

import { api, apiDetail } from "./client";

export interface AIProvider {
  id: string;
  name: string;
  scope: "system" | "user";
  user_id: string | null;
  provider_type: "mock" | "openai" | "openai_compatible" | "google" | "decision";
  api_base: string;
  api_key: string | null;
  is_active: boolean;
  is_local: boolean | null;
  country: string | null;
  preset_key: string | null;
  is_mine: boolean;
  created_at: string;
}

export interface PreferredModel {
  id: string;
  name: string;
  caps: string[];
}

export interface DecisionModelData {
  id: string;
  name: string;
  transport: string;
  base_url_override?: string;
  caps: string[];
  provisional?: boolean;
}

export interface ProviderPreset {
  name: string;
  type: string;
  base_url: string;
  fixed_base?: boolean;
  local: boolean;
  key_url?: string | null;
  preferred_model?: PreferredModel | null;
  curated_models?: string[] | null;
  stt_model?: string | null;
  decision_models?: DecisionModelData[] | null;
  decision_default?: string | null;
  provisional?: boolean | null;
  steps?: string[] | null;
  free_tier_note?: string | null;
}

export async function fetchProviderPresets(): Promise<Record<string, ProviderPreset>> {
  const { data } = await api.get<Record<string, ProviderPreset>>("/ai/providers/presets");
  return data;
}

export interface ProviderSetupOptions {
  curated_ids?: string[];
  bind_chat: boolean;
  bind_vision: boolean;
  bind_stt: boolean;
  bind_decision: boolean;
}

export interface ProviderSetupResult {
  ok: boolean;
  provider: AIProvider;
  catalog_count: number;
  curated_missed: boolean;
  assigned_chat_model: string | null;
  assigned_vision_model: string | null;
  assigned_stt_model: string | null;
  assigned_decision_slots: Record<string, string> | null;
}

export async function setupProviderPreset(
  presetKey: string,
  body: {
    api_key: string | null;
    name?: string | null;
    scope?: "user" | "system";
    options?: ProviderSetupOptions;
  }
): Promise<ProviderSetupResult> {
  const { data } = await api.post<ProviderSetupResult>(`/ai/providers/${presetKey}/setup`, body);
  return data;
}

/** §15 classified setup failure (the API's 422 detail shape). */
export interface ProviderSetupErrorDetail {
  code: string;
  suspected_vendor: string | null;
  detail: string;
}

export function setupErrorDetail(detail: unknown): ProviderSetupErrorDetail | null {
  if (typeof detail !== "object" || detail === null) return null;
  const candidate = detail as { code?: unknown; suspected_vendor?: unknown; detail?: unknown };
  if (typeof candidate.code !== "string") return null;
  return {
    code: candidate.code,
    suspected_vendor: typeof candidate.suspected_vendor === "string" ? candidate.suspected_vendor : null,
    detail: typeof candidate.detail === "string" ? candidate.detail : "",
  };
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
  decision_transport?: string | null;
}

export interface AITaskInfo {
  value: string;
  label: string;
  description?: string;
  requires?: string;
  tier?: string;
  is_slot?: boolean;
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
  kind?: "tool" | "capability";
  hitl?: boolean;
}

export async function fetchAiTools(options?: {
  includeCapabilities?: boolean;
  bindableOnly?: boolean;
}): Promise<AiToolInfo[]> {
  const { data } = await api.get<AiToolInfo[]>("/ai/tools", {
    params: {
      ...(options?.includeCapabilities
        ? { include_capabilities: true }
        : {}),
      ...(options?.bindableOnly ? { bindable_only: true } : {}),
    },
  });
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

export interface WebSettings {
  searxng_url: string;
  searxng_probe: { status: string; status_code?: number };
  github_token_set: boolean;
}

export async function fetchWebSettings(): Promise<WebSettings> {
  const { data } = await api.get<WebSettings>("/ai/web");
  return data;
}

export async function updateWebSettings(
  payload: Partial<Pick<WebSettings, "searxng_url">> & { github_token?: string }
): Promise<WebSettings> {
  const { data } = await api.put<WebSettings>("/ai/web", payload);
  return data;
}
