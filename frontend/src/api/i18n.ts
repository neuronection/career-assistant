import { api } from "@/api/client";
import type { LabelOverlay, LocaleState, OverlayDraftResult } from "@/types";

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

/** Catalog-label overlays awaiting (or having completed) review. */
export async function fetchOverlayQueue(
  locale: string,
  status: "draft" | "approved" | "rejected" = "draft",
): Promise<LabelOverlay[]> {
  const { data } = await api.get<LabelOverlay[]>("/admin/i18n/overlays", {
    params: { locale, status, limit: 200 },
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
