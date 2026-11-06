import { api } from "@/api/client";

export type McpToolScope = "read" | "write";

export interface McpToolView {
  key: string;
  title: string;
  description: string;
  scope: McpToolScope;
  risk_class: string;
}

export interface McpStatus {
  endpoint: string;
  transport: string;
  write_enabled: boolean;
  tools: McpToolView[];
  read_tools: string[];
  write_tools: string[];
  active_tokens: number;
}

export interface McpTokenView {
  id: string;
  label: string;
  scopes: McpToolScope[];
  bound_user_id: string | null;
  created_at: string;
  last_used_at: string | null;
  rotated_at: string | null;
  revoked_at: string | null;
  rotated_from_id: string | null;
  active: boolean;
}

export interface McpTokenMinted extends McpTokenView {
  /** Shown exactly once — mint/rotation response only. */
  token: string;
}

export interface McpAuditRow {
  id: string;
  tool: string | null;
  label: string;
  status: string;
  latency_ms: number;
  request_id: string | null;
  created_at: string;
}

export async function fetchMcpStatus(): Promise<McpStatus> {
  const { data } = await api.get<McpStatus>("/ai/mcp/status");
  return data;
}

export async function setMcpWriteEnabled(writeEnabled: boolean): Promise<{
  write_enabled: boolean;
  tools: McpToolView[];
  write_tools: string[];
}> {
  const { data } = await api.put("/ai/mcp/settings", {
    write_enabled: writeEnabled,
  });
  return data;
}

export async function fetchMcpTokens(): Promise<McpTokenView[]> {
  const { data } = await api.get<McpTokenView[]>("/ai/mcp/tokens");
  return data;
}

export async function mintMcpToken(payload: {
  label: string;
  scopes: McpToolScope[];
}): Promise<McpTokenMinted> {
  const { data } = await api.post<McpTokenMinted>("/ai/mcp/tokens", payload);
  return data;
}

export async function rotateMcpToken(id: string): Promise<McpTokenMinted> {
  const { data } = await api.post<McpTokenMinted>(`/ai/mcp/tokens/${id}/rotate`);
  return data;
}

export async function revokeMcpToken(id: string): Promise<void> {
  await api.delete(`/ai/mcp/tokens/${id}`);
}

export async function fetchMcpAudit(limit = 25): Promise<McpAuditRow[]> {
  const { data } = await api.get<McpAuditRow[]>("/ai/mcp/audit", {
    params: { limit },
  });
  return data;
}
