import { api } from "./client";

// Tools → connectors → extension sources (plan 32 Phase 3 / ADR-0040
// D13+D22): the git import layer — sources, consent-gated installs,
// digest pins, GitOps desired state. Data-only client: the consent copy
// (T3 perimeter disclosure) renders VERBATIM from the backend payload,
// never re-authored here.

export type RefStrategy = {
  strategy: "release-tag" | "tag-pattern" | "branch" | "commit-pin";
  value?: string;
};

export type SourceDescriptorView = {
  url: string | null;
  local: { path: string } | null;
  ref: RefStrategy;
  subpath?: string;
  credentialSlots: string[];
};

export type ConsentPayload = {
  extensionId: string | null;
  version: string | null;
  subpath: string;
  digest: string;
  tier: string;
  importClass: string;
  capabilities: string[];
  provenance: ConsentProvenance;
  disclosureKey: string;
  disclosure: string;
};

export type ExtensionCandidate = {
  extensionId: string;
  subpath: string;
  digest: string;
  ref: string;
  compatible: boolean;
  reason: string | null;
  hasEntry: boolean;
  consent?: ConsentPayload;
  manifest?: Record<string, unknown>;
};

export type ConsentProvenance = {
  author: string | null;
  license: string | null;
  repository: string | null;
  description: string | null;
};

export type ExtensionInstallView = {
  id: string;
  extensionId: string;
  version: string;
  digest: string;
  pinRef: string;
  tier: "T0" | "T3";
  originClass: "bundled" | "imported" | "listed";
  state: "installed" | "disabled" | "self-disabled" | "removed";
  enabled: boolean;
  managedBy: "manual" | "gitops";
  parked: boolean;
  sourceKey: string | null;
  contentPath: string;
  provenance: ConsentProvenance;
  consentedAt: string | null;
  update: {
    state?: string;
    ref?: string;
    digest?: string;
    requiresReconsent?: boolean;
    manifestDiff?: {
      capabilitiesAdded: string[];
      configSchemaChanged: boolean | null;
      version?: { from?: string; to?: string };
    };
    detail?: string;
  };
  tombstonedAt: string | null;
};

export type ExtensionSourceView = {
  id: string;
  kind: "git" | "local";
  origin: string;
  descriptor: SourceDescriptorView;
  status: "ok" | "degraded" | "failing" | "stale";
  error: string;
  last_checked_at: string | null;
  last_success_at: string | null;
  consecutive_failures: number;
  candidates: (ExtensionCandidate & { manifest?: Record<string, unknown> })[];
  installs: ExtensionInstallView[];
};

export async function fetchExtensionSources(): Promise<ExtensionSourceView[]> {
  const response = await api.get<ExtensionSourceView[]>("/admin/extensions/sources");
  return response.data;
}

export async function addExtensionSource(payload: {
  descriptor: Record<string, unknown>;
  secrets?: Record<string, string>;
}): Promise<ExtensionSourceView> {
  const response = await api.post("/admin/extensions/sources", payload);
  return response.data;
}

export async function removeExtensionSource(id: string): Promise<void> {
  await api.delete(`/admin/extensions/sources/${id}`);
}

export async function syncExtensionSource(id: string): Promise<{
  ok: boolean;
  error?: { code: string; detail: string };
}> {
  const response = await api.post(`/admin/extensions/sources/${id}/sync`);
  return response.data;
}

export async function installExtension(
  sourceId: string,
  extensionId: string,
  consent: boolean,
): Promise<ExtensionInstallView> {
  const response = await api.post(`/admin/extensions/sources/${sourceId}/install`, {
    extension_id: extensionId,
    consent,
  });
  return response.data;
}

export async function applyExtensionUpdate(
  installId: string,
  consent: boolean,
): Promise<ExtensionInstallView> {
  const response = await api.post(`/admin/extensions/installs/${installId}/apply`, { consent });
  return response.data;
}

export async function setExtensionEnabled(
  installId: string,
  enabled: boolean,
): Promise<ExtensionInstallView> {
  const response = await api.post(`/admin/extensions/installs/${installId}/enabled`, { enabled });
  return response.data;
}

export async function parkExtensionInstall(installId: string): Promise<ExtensionInstallView> {
  const response = await api.post(`/admin/extensions/installs/${installId}/park`);
  return response.data;
}

export async function tombstoneExtensionInstall(
  installId: string,
): Promise<ExtensionInstallView> {
  const response = await api.post(`/admin/extensions/installs/${installId}/tombstone`);
  return response.data;
}

export async function fetchDesiredState(): Promise<Record<string, unknown>> {
  const response = await api.get<Record<string, unknown>>("/admin/extensions/desired-state");
  return response.data;
}

export async function putDesiredState(
  document: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await api.put("/admin/extensions/desired-state", document);
  return response.data;
}

export async function reconcileExtensions(): Promise<Record<string, unknown>> {
  const response = await api.post("/admin/extensions/reconcile");
  return response.data;
}
