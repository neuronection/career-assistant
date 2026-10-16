import { api } from "./client";

// Extension surfaces (plan 32 Phase 4 / ADR-0040 clause 16): installed,
// enabled mini-app extensions declaring ui:page / ui:panel declarative
// schemas. The backend assembles their render views (nodes + resolved
// labels + rows from the declared T0 data); the frontend renders the SAME
// family SurfaceRenderer — no extension markup, ever. The kill switch is
// the data boundary: a disabled install vanishes from the registry and
// the page route 404s.

export type SurfaceCapabilityView = {
  honored: string[];
  degrades: Record<string, string>;
  declared: string[];
};

export type SurfaceCard = {
  extensionId: string;
  title: string;
  summary: string | null;
  version: string;
  tier: string;
  originClass: "imported";
  enabled: boolean;
  capabilities: string[];
  surfaces: SurfaceCapabilityView;
  routes: string | null;
  consentedAt: string | null;
  provenance: {
    author: string | null;
    license: string | null;
    repository: string | null;
    description: string | null;
  };
};

export type SurfaceRowShaped = {
  id: string;
  values: Record<string, unknown>;
  title?: string;
  badge?: string;
  badgeField?: string;
  group?: string;
  meta?: string[];
  evidence?: unknown;
  evidenceSummary?: string;
  actions?: string[];
};

export type SurfacePageView = {
  extensionId: string;
  version: string;
  title: string;
  surface: {
    kind: string;
    degraded: Record<string, string>;
    nodes: unknown[];
    labels: Record<string, string>;
    rows: SurfaceRowShaped[];
    values: Record<string, unknown>;
    groups: Record<string, string>;
    filters: { id: string; options: { value: string; label: string | null }[] }[];
  };
  placeholders: string[];
  manifestSummary: {
    kind: string;
    packKind: string | null;
    tier: string;
    originClass: string;
    capabilities: string[];
    surfaces: SurfaceCapabilityView;
    configSchema: Record<string, unknown> | null;
    description: string | null;
  };
};

export type SurfaceExport = {
  extensionId: string;
  version: string;
  source: string;
  rows: Record<string, unknown>[];
  values: Record<string, unknown>;
};

export async function fetchSurfaceCards(): Promise<SurfaceCard[]> {
  const { data } = await api.get<SurfaceCard[]>("/extensions/surfaces");
  return data;
}

export async function fetchSurfacePage(
  extensionId: string,
): Promise<SurfacePageView> {
  const { data } = await api.get<SurfacePageView>(`/extensions/surfaces/${extensionId}`);
  return data;
}

export async function exportSurfacePage(
  extensionId: string,
): Promise<SurfaceExport> {
  const { data } = await api.get<SurfaceExport>(`/extensions/surfaces/${extensionId}/export`);
  return data;
}
