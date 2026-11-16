import { api } from "@/api/client";

/** Public instance facts (`GET /api/v1/instance/config`) — readable
 * without a session so the demo badge renders before login
 * (identity-auth §4/§13). */
export interface DatastoreQuarantine {
  /** Where the previous datastore was moved (desktop only). */
  path: string;
  reason: "incompatible-schema" | "unreadable" | string;
  quarantined_at: string;
  schema_revision: string | null;
  from_version: string | null;
}

export interface InstanceConfig {
  demo_mode: boolean;
  auth_mode: string;
  registration_enabled: boolean;
  /** Entrypoint mode (identity-auth §4) — `server` instances are
   * permanently authenticated; the §4.5 control blocks accordingly. */
  identity_mode: "server" | "desktop";
  /** One-time notice after a deliberate datastore break (family
   * datastore-breaks contract); only ever set on the desktop identity. */
  datastore_quarantine?: DatastoreQuarantine | null;
}

export async function getInstanceConfig(): Promise<InstanceConfig> {
  const { data } = await api.get<InstanceConfig>("/instance/config");
  return data;
}
