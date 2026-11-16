import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  clearPostingHygiene,
  fetchPostingHygiene,
  mergePostingHygiene,
  scanPostingHygiene,
  type HygieneOverview,
} from "@/api/postingHygiene";

export function PostingHygieneSection() {
  const { t } = useTranslation();
  const [overview, setOverview] = useState<HygieneOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const data = await fetchPostingHygiene();
    setOverview(data);
  }, []);

  useEffect(() => {
    void load().catch((err) => setError(apiDetail(err)));
  }, [load]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="posting-hygiene">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">
            {t("postingHygiene.title")}
          </h2>
          <p className="max-w-2xl text-xs text-slate-500">{t("postingHygiene.subtitle")}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void run(async () => void (await scanPostingHygiene()))}
          data-testid="hygiene-scan"
        >
          <RefreshCw className={`mr-1 size-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden />
          {t("postingHygiene.scan")}
        </Button>
      </div>

      {error !== "" && (
        <p role="alert" className="text-sm text-[var(--as-danger)]" data-testid="hygiene-error">
          {error}
        </p>
      )}

      {overview !== null && (
        <div className="grid gap-3 sm:grid-cols-3" data-testid="hygiene-counts">
          <Count label={t("postingHygiene.counts.canonical")} value={overview.counts.canonical} />
          <Count label={t("postingHygiene.counts.duplicates")} value={overview.counts.duplicates} />
          <Count label={t("postingHygiene.counts.candidates")} value={overview.counts.candidates} />
        </div>
      )}

      <section className="space-y-2" data-testid="hygiene-candidates">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("postingHygiene.candidates")}
        </h3>
        {(overview?.candidates ?? []).map((row) =>
          row.candidates.map((hint) => (
            <div
              key={`${row.id}-${hint.posting_id}`}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-2"
              data-testid={`hygiene-candidate-${row.id}`}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-900">{row.title}</p>
                <p className="truncate text-xs text-slate-500">
                  {row.org} · {t("postingHygiene.suggests", { title: hint.title })}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  void run(() => mergePostingHygiene(row.id, hint.posting_id))
                }
                data-testid={`hygiene-merge-${row.id}`}
              >
                {t("postingHygiene.merge")}
              </Button>
            </div>
          ))
        )}
        {(overview?.candidates ?? []).length === 0 && (
          <p className="text-xs text-slate-500">{t("postingHygiene.noCandidates")}</p>
        )}
      </section>

      <section className="space-y-2" data-testid="hygiene-duplicates">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("postingHygiene.merged")}
        </h3>
        {(overview?.duplicates ?? []).map((row) => (
          <div
            key={row.id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-2"
            data-testid={`hygiene-duplicate-${row.id}`}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-slate-900">{row.title}</p>
              <p className="truncate text-xs text-slate-500">{row.org}</p>
            </div>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void run(() => clearPostingHygiene(row.id))}
              data-testid={`hygiene-clear-${row.id}`}
            >
              {t("postingHygiene.clear")}
            </Button>
          </div>
        ))}
        {(overview?.duplicates ?? []).length === 0 && (
          <p className="text-xs text-slate-500">{t("postingHygiene.noMerged")}</p>
        )}
      </section>

      <section className="space-y-2" data-testid="hygiene-canonical">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("postingHygiene.canonical")}
        </h3>
        {(overview?.canonical ?? []).map((row) => (
          <p key={row.id} className="truncate text-xs text-slate-600">
            {row.title} · {row.org} ·{" "}
            {t("postingHygiene.reposts", { count: row.repost_count })}
            {row.last_verified_at
              ? ` · ${t("postingHygiene.lastVerified", {
                  date: new Date(row.last_verified_at).toLocaleDateString(),
                })}`
              : ""}
          </p>
        ))}
        {(overview?.canonical ?? []).length === 0 && (
          <p className="text-xs text-slate-500">{t("postingHygiene.noCanonical")}</p>
        )}
      </section>
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="text-lg font-semibold tabular-nums text-slate-900">{value}</p>
      <p className="text-xs text-slate-500">{label}</p>
    </div>
  );
}
