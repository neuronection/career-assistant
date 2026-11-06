import { api } from "@/api/client";
import type { LabelOverlay, LocaleState, OverlayDraftResult } from "@/types/wire";

/** The caller's effective UI locale plus the supported registry. */
export async function fetchLocale(): Promise<LocaleState> {
  const { data } = await api.get<LocaleState>("/me/locale");
  return data;
}

/** Persist the caller's UI locale (the SPA re-initialises i18next). */
export async function setMyLocale(locale: string): Promise<LocaleState> {
  const { data } = await api.put<LocaleState>("/me/locale", { locale });
  return data;
}

/** Instance-wide default locale (admin surface). */
export async function fetchInstanceLocale(): Promise<LocaleState> {
  const { data } = await api.get<LocaleState>("/admin/i18n/locale");
  return data;
}

export async function setInstanceLocale(locale: string): Promise<LocaleState> {
  const { data } = await api.put<LocaleState>("/admin/i18n/locale", { locale });
  return data;
}

/** Overlay queue status; `""` omits the status filter (the backend
 * treats an empty status as "all"). */
export type OverlayQueueStatus = "draft" | "approved" | "rejected" | "";

/**
 * Catalog-label overlays for (or after) review. The review board calls
 * this with NO filters: one bounded fetch at the endpoint's max page
 * (500 rows, all locales, all statuses) and the locale/status pill
 * counts, kind groups and search are derived client-side — pill counts
 * stay exact within that page and every refresh costs a single request
 * (plan 150 phase 4). A locale may be passed to scope the page.
 */
export async function fetchOverlayQueue(
  locale = "",
  status: OverlayQueueStatus = "",
): Promise<LabelOverlay[]> {
  const { data } = await api.get<LabelOverlay[]>("/admin/i18n/overlays", {
    params: { locale, status, limit: 500 },
  });
  return data;
}

/** AI-draft overlays for taxonomy rows (draft status; never renders). */
export async function draftOverlays(
  locale: string,
  entityKinds: string[] = ["job", "skill", "family"],
): Promise<OverlayDraftResult> {
  const { data } = await api.post<OverlayDraftResult>("/admin/i18n/overlays/draft", {
    locale,
    entity_kinds: entityKinds,
    limit: 20,
  });
  return data;
}

export async function updateOverlay(id: string, value: string): Promise<LabelOverlay> {
  const { data } = await api.patch<LabelOverlay>(`/admin/i18n/overlays/${id}`, {
    value,
  });
  return data;
}

export async function approveOverlay(id: string): Promise<{ id: string; status: string }> {
  const { data } = await api.post<{ id: string; status: string }>(
    `/admin/i18n/overlays/${id}/approve`,
  );
  return data;
}

export async function rejectOverlay(id: string): Promise<{ id: string; status: string }> {
  const { data } = await api.post<{ id: string; status: string }>(
    `/admin/i18n/overlays/${id}/reject`,
  );
  return data;
}

export type OverlayBulkAction = "approve" | "reject";

export interface OverlayBulkFailure {
  id: string;
  reason: string;
}

export interface OverlayBulkResult {
  affected: string[];
  failed: OverlayBulkFailure[];
}

const BULK_CHUNK = 200;

/** Approve or reject a batch of overlays; the server caps one call at 200
 * ids, so larger selections chunk transparently and the results merge
 * (plan 200, the `bulkSkillAction` precedent). */
export async function bulkOverlayAction(
  ids: string[],
  action: OverlayBulkAction,
): Promise<OverlayBulkResult> {
  const results: OverlayBulkResult[] = [];
  for (let start = 0; start < ids.length; start += BULK_CHUNK) {
    const { data } = await api.post<OverlayBulkResult>("/admin/i18n/overlays/bulk", {
      ids: ids.slice(start, start + BULK_CHUNK),
      action,
    });
    results.push(data);
  }
  return {
    affected: results.flatMap((result) => result.affected),
    failed: results.flatMap((result) => result.failed),
  };
}
