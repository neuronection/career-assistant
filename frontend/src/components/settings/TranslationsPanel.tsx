import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  approveOverlay,
  draftOverlays,
  fetchOverlayQueue,
  rejectOverlay,
  updateOverlay,
} from "@/api/i18n";
import { apiDetail } from "@/api/client";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import type { LabelOverlay } from "@/types/wire";

const TARGET_LOCALES = ["de", "el"] as const;
const STATUSES = ["draft", "approved", "rejected"] as const;

/**
 * Catalog-label overlay review (plan 121.4): AI drafts land here as
 * `draft`; only an explicit approval renders on catalog surfaces. The
 * base label stays visible next to every draft so reviewers judge the
 * translation against the source, never blind.
 */
export function TranslationsPanel() {
  const { t } = useTranslation();
  const [locale, setLocale] = useState<(typeof TARGET_LOCALES)[number]>("de");
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("draft");
  const [rows, setRows] = useState<LabelOverlay[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchOverlayQueue(locale, status));
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, [locale, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const draft = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await draftOverlays(locale);
      const total = Object.values(result.drafted).reduce((sum, value) => sum + value, 0);
      setNote(t("translations.drafted", { count: total }));
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const approve = async (id: string) => {
    setBusy(true);
    try {
      await approveOverlay(id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const reject = async (id: string) => {
    setBusy(true);
    try {
      await rejectOverlay(id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async (row: LabelOverlay) => {
    const value = edits[row.id] ?? row.value;
    if (!value.trim() || value === row.value) return;
    setBusy(true);
    try {
      await updateOverlay(row.id, value.trim());
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="space-y-3 p-4" data-testid="translations-panel">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">{t("translations.title")}</h2>
          <p className="text-xs text-slate-500">{t("translations.description")}</p>
        </div>
        <Button size="sm" disabled={busy} data-testid="draft-overlays" onClick={() => void draft()}>
          {t("translations.draft")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {TARGET_LOCALES.map((code) => (
            <Button
              key={code}
              size="sm"
              variant={locale === code ? "default" : "outline"}
              aria-pressed={locale === code}
              data-testid={`overlay-locale-${code}`}
              onClick={() => setLocale(code)}
            >
              {code.toUpperCase()}
            </Button>
          ))}
        </div>
        <div className="flex gap-1">
          {STATUSES.map((value) => (
            <Button
              key={value}
              size="sm"
              variant={status === value ? "secondary" : "ghost"}
              aria-pressed={status === value}
              data-testid={`overlay-status-${value}`}
              onClick={() => setStatus(value)}
            >
              {t(`translations.status.${value}`)}
            </Button>
          ))}
        </div>
      </div>

      {error ? <p className="text-sm text-rose-600">{error}</p> : null}
      {note ? <p className="text-xs text-emerald-600">{note}</p> : null}

      {loading ? (
        <div className="flex items-center gap-2 py-6 text-xs text-slate-400">
          <Spinner size="sm" /> {t("common.loading")}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          title={t("translations.emptyTitle")}
          description={t("translations.emptyBody")}
        />
      ) : (
        <div className="space-y-2" data-testid="overlay-queue">
          {rows.map((row) => (
            <div
              key={row.id}
              className="rounded-lg border border-slate-200 p-3"
              data-testid={`overlay-row-${row.id}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t(`translations.kind.${row.entity_kind}`)} · {row.field}
                </p>
                <span className="text-[11px] text-slate-400">{row.locale}</span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {t("translations.base")}: {row.base_value || "—"}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input
                  value={edits[row.id] ?? row.value}
                  onChange={(event) =>
                    setEdits((current) => ({ ...current, [row.id]: event.target.value }))
                  }
                  className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
                  data-testid={`overlay-value-${row.id}`}
                />
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void save(row)}>
                  {t("common.save")}
                </Button>
                {row.status === "draft" ? (
                  <>
                    <Button
                      size="sm"
                      disabled={busy}
                      data-testid={`overlay-approve-${row.id}`}
                      onClick={() => void approve(row.id)}
                    >
                      {t("translations.approve")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      data-testid={`overlay-reject-${row.id}`}
                      onClick={() => void reject(row.id)}
                    >
                      {t("translations.reject")}
                    </Button>
                  </>
                ) : (
                  <span className="text-xs text-slate-400">
                    {t(`translations.status.${row.status}`)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
