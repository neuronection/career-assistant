import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Database } from "lucide-react";
import { SwitchRow } from "@/components/ui";
import {
  fetchCatalogMappingSettings,
  putCatalogMappingSettings,
  type CatalogMappingSettings,
} from "@/api/taxonomy";

/** "Embeddings & mapping" (plan 185 S6.3, plan 50 P2c.4): the catalog
 * mapping run switches — read per decision, effective on the next decision,
 * so there is no restart to manage: the pipeline is queue/event-driven and
 * these switches + re-extract/re-decide + the Failures-tab requeue are its
 * only levers. The semantic rescue and the semantic rerank are independent:
 * either can run without the other. Retrieval coverage and reindex controls
 * live on the retrieval ops surface (plan 51). */
export function TaxonomyEmbeddingsCard() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<CatalogMappingSettings | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setSettings(await fetchCatalogMappingSettings());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const flip = async (
    key: "job_proposals" | "semantic_rescue" | "semantic_rerank",
    enabled: boolean,
  ) => {
    try {
      setSettings(await putCatalogMappingSettings({ [key]: enabled }));
      setNote(t("taxonomy.embeddings.switchNote"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
      {settings && (
        <div className="space-y-1">
          <SwitchRow
            label={t("taxonomy.embeddings.jobProposalsSwitch")}
            currentValue={t("taxonomy.embeddings.jobProposalsHint")}
            checked={settings.job_proposals}
            onCheckedChange={(enabled) => void flip("job_proposals", enabled)}
            data-testid="embeddings-switch-proposals"
          />
          <SwitchRow
            label={t("taxonomy.embeddings.semanticRescueSwitch")}
            currentValue={t("taxonomy.embeddings.semanticRescueHint")}
            checked={settings.semantic_rescue}
            onCheckedChange={(enabled) => void flip("semantic_rescue", enabled)}
            data-testid="embeddings-switch-semantic-rescue"
          />
          <SwitchRow
            label={t("taxonomy.embeddings.semanticRerankSwitch")}
            currentValue={t("taxonomy.embeddings.semanticRerankHint")}
            checked={settings.semantic_rerank}
            onCheckedChange={(enabled) => void flip("semantic_rerank", enabled)}
            data-testid="embeddings-switch-semantic-rerank"
          />
        </div>
      )}
    </section>
  );
}
