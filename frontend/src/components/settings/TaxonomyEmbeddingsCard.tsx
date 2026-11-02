import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Database } from "lucide-react";
import { Button, Spinner, SwitchRow } from "@/components/ui";
import {
  fetchCatalogMappingSettings,
  fetchEmbeddingStatus,
  putCatalogMappingSettings,
  recomputeEmbeddings,
  type CatalogMappingSettings,
  type EmbeddingBucket,
} from "@/api/taxonomy";

/** "Embeddings & mapping" (plan 185 S6.3): the embedding store's per-kind
 * buckets (API-only until now), the admin recompute passes, and the two
 * run switches — read per decision, effective on the next decision, so
 * there is no restart to manage: the pipeline is queue/event-driven and
 * these switches + re-extract/re-decide + the Failures-tab requeue are
 * its only levers. */
export function TaxonomyEmbeddingsCard() {
  const { t } = useTranslation();
  const [buckets, setBuckets] = useState<EmbeddingBucket[]>([]);
  const [settings, setSettings] = useState<CatalogMappingSettings | null>(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [status, mappingSettings] = await Promise.all([
        fetchEmbeddingStatus(),
        fetchCatalogMappingSettings(),
      ]);
      setBuckets(status);
      setSettings(mappingSettings);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const recompute = async (kind: "posting" | "job") => {
    setBusy(kind);
    setNote("");
    try {
      const result = await recomputeEmbeddings(kind);
      setNote(
        t("taxonomy.embeddings.recomputeDone", {
          kind,
          count: result.embedded,
        }),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const flip = async (key: "semantic_rescue" | "job_proposals", enabled: boolean) => {
    setBusy(key);
    try {
      setSettings(await putCatalogMappingSettings({ [key]: enabled }));
      setNote(t("taxonomy.embeddings.switchNote"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  return (
    <section
      className="space-y-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="embeddings-card"
    >
      <div className="flex items-center gap-2">
        <Database className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          {t("taxonomy.embeddings.sectionTitle")}
        </h2>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {note && (
        <p className="text-xs text-emerald-700" data-testid="embeddings-note">
          {note}
        </p>
      )}
      {buckets.length === 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]">{t("taxonomy.embeddings.empty")}</p>
      ) : (
        <ul className="space-y-1" data-testid="embeddings-buckets">
          {buckets.map((bucket) => (
            <li
              key={`${bucket.entity_kind}-${bucket.dim}`}
              className="flex items-center justify-between gap-2 text-xs text-[var(--as-fg)]"
              data-testid={`embeddings-bucket-${bucket.entity_kind}`}
            >
              <span className="font-mono">{bucket.entity_kind}</span>
              <span className="text-[var(--as-muted-fg)]">
                {t("taxonomy.embeddings.bucket", {
                  dim: bucket.dim,
                  count: bucket.count,
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy !== ""}
          onClick={() => void recompute("posting")}
          data-testid="embeddings-recompute-posting"
        >
          {busy === "posting" ? <Spinner size="sm" /> : t("taxonomy.embeddings.recomputePosting")}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy !== ""}
          onClick={() => void recompute("job")}
          data-testid="embeddings-recompute-job"
        >
          {busy === "job" ? <Spinner size="sm" /> : t("taxonomy.embeddings.recomputeJob")}
        </Button>
      </div>
      {settings && (
        <div className="space-y-1 border-t border-[var(--as-border)] pt-2">
          <SwitchRow
            label={t("taxonomy.embeddings.semanticRescue")}
            currentValue={t("taxonomy.embeddings.semanticRescueHint")}
            checked={settings.semantic_rescue}
            onCheckedChange={(enabled) => void flip("semantic_rescue", enabled)}
            data-testid="embeddings-switch-semantic"
          />
          <SwitchRow
            label={t("taxonomy.embeddings.jobProposalsSwitch")}
            currentValue={t("taxonomy.embeddings.jobProposalsHint")}
            checked={settings.job_proposals}
            onCheckedChange={(enabled) => void flip("job_proposals", enabled)}
            data-testid="embeddings-switch-proposals"
          />
        </div>
      )}
    </section>
  );
}
