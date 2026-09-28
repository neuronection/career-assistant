import { api } from "./client";

/** Public instance facts (`GET /api/v1/instance/config`) — readable
 * without a session so the demo badge renders before login
 * (identity-auth §4/§13). */
export interface InstanceConfig {
  demo_mode: boolean;
  auth_mode: string;
  registration_enabled: boolean;
}

export async function getInstanceConfig(): Promise<InstanceConfig> {
  const { data } = await api.get<InstanceConfig>("/instance/config");
  return data;
}
