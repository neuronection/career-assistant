import type { AuditWindow } from "@/api/audit";
import type {
  RetrievalGate,
  RetrievalRunStatus,
  RetrievalWindow,
} from "@/api/retrieval";

export type RetrievalSection =
  | "overview"
  | "spaces"
  | "runs"
  | "quality"
  | "query-health"
  | "failures"
  | "usage"
  | "changes";

export const RETRIEVAL_SECTIONS: readonly RetrievalSection[] = [
  "overview",
  "spaces",
  "runs",
  "quality",
  "query-health",
  "failures",
  "usage",
  "changes",
];

const SECTION_KEY: Record<RetrievalSection, string> = {
  overview: "overview",
  spaces: "spaces",
  runs: "runs",
  quality: "quality",
  "query-health": "queryHealth",
  failures: "failures",
  usage: "usage",
  changes: "changes",
};

export function sectionLabelKey(section: RetrievalSection): string {
  return `audit.retrieval.section.${SECTION_KEY[section]}`;
}

export function parseRetrievalSection(raw: string | null): RetrievalSection {
  return (RETRIEVAL_SECTIONS as readonly string[]).includes(raw ?? "")
    ? (raw as RetrievalSection)
    : "overview";
}

export function parseRetrievalWindow(raw: string | null): RetrievalWindow {
  if (raw === "7d" || raw === "30d" || raw === "90d") return raw;
  return "24h";
}

export function retrievalAuditWindow(window: RetrievalWindow): AuditWindow {
  return window === "90d" ? "30d" : window;
}

export const TOOLS_RETRIEVAL_URL = "/settings/tools?section=retrieval";
export const RETRIEVAL_RUNBOOK_URL =
  "https://github.com/neuronection/career-assistant/blob/main/docs/dev/retrieval-ops.md";

export function retrievalDetailUrl(
  section: RetrievalSection,
  detail: string,
  window?: RetrievalWindow,
): string {
  const params = new URLSearchParams({ tab: "retrieval", section, detail });
  if (window && window !== "24h") params.set("window", window);
  return `/settings/audit?${params.toString()}`;
}

export function retrievalRunUrl(
  runId: string,
  window?: RetrievalWindow,
): string {
  return retrievalDetailUrl("runs", runId, window);
}

export function retrievalSpaceUrl(
  spaceId: string,
  window?: RetrievalWindow,
): string {
  return retrievalDetailUrl("spaces", spaceId, window);
}

const rate = (value: number | null | undefined): string =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

export const formatRate = rate;

export const shortId = (value: string | null | undefined): string =>
  value ? value.slice(0, 8) : "—";

export const when = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleString() : "—";

export const formatMs = (value: number | null | undefined): string =>
  value == null ? "—" : `${Math.round(value)}ms`;

export const formatNumber = (value: number | null | undefined): string =>
  value == null ? "—" : value.toLocaleString();

export const gateVariant = (
  gate: RetrievalGate,
): "success" | "danger" | "secondary" =>
  gate === "pass" ? "success" : gate === "fail" ? "danger" : "secondary";

export const statusVariant = (
  status: RetrievalRunStatus | string,
): "success" | "danger" | "warning" | "secondary" => {
  if (status === "succeeded" || status === "active" || status === "ok") return "success";
  if (status === "failed" || status === "retired") return "danger";
  if (status === "queued" || status === "running" || status === "building") {
    return "warning";
  }
  return "secondary";
};

export interface RetrievalResourceTarget {
  kind: "run" | "space";
  id: string;
}

/** Parse the emitter's structured `resource` ref (`space:<id>;action=…`
 * or `run:<id>;space=…`) into a navigation target; ids only. */
export function parseRetrievalResource(
  resource: string | null | undefined,
): RetrievalResourceTarget | null {
  if (!resource) return null;
  const head = resource.split(";")[0]?.trim() ?? "";
  const [kind, id] = head.split(":", 2);
  if (!id) return null;
  if (kind === "run") return { kind: "run", id };
  if (kind === "space" && id !== "new") return { kind: "space", id };
  return null;
}

/** Failure groups have no standalone id; the detail param is a stable
 * composite of the structured fields the drawer needs. */
export function failureDetailId(kind: string, spaceId: string, runId: string | null): string {
  return `${kind}:${spaceId}:${runId ?? "none"}`;
}

export function parseFailureDetailId(
  raw: string | null,
): { kind: string; spaceId: string; runId: string | null } | null {
  if (!raw) return null;
  const [kind, spaceId, runId] = raw.split(":");
  if (!kind || !spaceId || !runId) return null;
  return { kind, spaceId, runId: runId === "none" ? null : runId };
}

export function isDegradedRate(value: number | null | undefined): boolean {
  return typeof value === "number" && value > 0;
}
