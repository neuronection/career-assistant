import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  dryRunMappingsPolicy,
  fetchMappingsPolicy,
  fetchMappingsQueue,
  mappingActionError,
  saveMappingsPolicy,
  type MappingDryRunResult,
  type MappingPolicy,
  type MappingPolicyDraft,
} from "@/api/mappings";
import { apiDetail } from "@/api/client";
import { Badge, Button } from "@/components/ui";
import { NumberField } from "@/features/cv/components/cv/formPrimitives";

/**
 * The editable mapping policy card (plan 205 S8): the four thresholds with
 * a bounded dry-run (savepoint + rollback, no embed/spend) and a Save that
 * is effective on the NEXT decision. The blend weights and the candidate
 * cap are read-only by design (AD8); the defaults are bit-identical to the
 * shipped constants.
 */
export function MappingPolicyCard() {
  const { t } = useTranslation();
  const [policy, setPolicy] = useState<MappingPolicy | null>(null);
  const [draft, setDraft] = useState<MappingPolicyDraft>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<MappingDryRunResult | null>(null);

  const load = useCallback(async () => {
    try {
      const current = await fetchMappingsPolicy();
      setPolicy(current);
      setDraft({
        tau_job: current.tau_job,
        delta: current.delta,
        semantic_threshold: current.semantic_threshold,
        semantic_min_shared_skills: current.semantic_min_shared_skills,
      });
    } catch (caught) {
      setError(apiDetail(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!window.confirm(t("mappingsConsole.policy.confirmSave"))) return;
    setBusy(true);
    setNote(null);
    try {
      const result = await saveMappingsPolicy(draft);
      setNote(t("mappingsConsole.policy.saved", { hash: result.policy_hash }));
      await load();
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runDry = async () => {
    setBusy(true);
    setNote(null);
    setDryRun(null);
    try {
      const queue = await fetchMappingsQueue({ limit: 50 });
      const ids = queue.items.map((row) => row.id).slice(0, 50);
      if (ids.length === 0) {
        setNote(t("mappingsConsole.policy.dryRunEmpty"));
        return;
      }
      const result = await dryRunMappingsPolicy(draft, ids);
      setDryRun(result);
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!policy) return null;

  const changed = dryRun?.results.filter((row) => row.changed) ?? [];

  return (
    <div className="rounded-xl border p-4" data-testid="mappings-policy">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-800">
          {t("mappingsConsole.policy.title")}
        </h3>
        <Badge variant="secondary">{policy.policy_hash.slice(0, 8)}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <NumberField
          label={t("mappingsConsole.policy.tauJob")}
          value={draft.tau_job ?? null}
          onChange={(value: number | null) =>
            setDraft((current) => ({ ...current, tau_job: value }))
          }
          min={0}
          max={1}
          testId="mappings-policy-tau"
        />
        <NumberField
          label={t("mappingsConsole.policy.delta")}
          value={draft.delta ?? null}
          onChange={(value: number | null) =>
            setDraft((current) => ({ ...current, delta: value }))
          }
          min={0}
          max={1}
          testId="mappings-policy-delta"
        />
        <NumberField
          label={t("mappingsConsole.policy.semanticThreshold")}
          value={draft.semantic_threshold ?? null}
          onChange={(value: number | null) =>
            setDraft((current) => ({ ...current, semantic_threshold: value }))
          }
          min={0}
          max={1}
          testId="mappings-policy-semantic-threshold"
        />
        <NumberField
          label={t("mappingsConsole.policy.semanticMinShared")}
          value={draft.semantic_min_shared_skills ?? null}
          onChange={(value) =>
            setDraft((current) => ({ ...current, semantic_min_shared_skills: value }))
          }
          min={1}
          testId="mappings-policy-semantic-min-shared"
        />
      </div>
      <p className="mt-2 text-xs text-slate-500" data-testid="mappings-policy-readonly">
        {t("mappingsConsole.policy.readonlyLine", {
          blendDeterministic: policy.blend_deterministic,
          blendSemantic: policy.blend_semantic,
          k: policy.k,
        })}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => void runDry()}
          data-testid="mappings-policy-dry-run"
        >
          {t("mappingsConsole.policy.dryRun")}
        </Button>
        <Button
          size="sm"
          disabled={busy}
          onClick={() => void save()}
          data-testid="mappings-policy-save"
        >
          {t("mappingsConsole.policy.save")}
        </Button>
      </div>
      <p className="mt-1 text-xs text-slate-500">{t("mappingsConsole.policy.effectiveNote")}</p>
      {note && (
        <p className="mt-2 text-sm text-slate-600" data-testid="mappings-policy-note">
          {note}
        </p>
      )}
      {dryRun && (
        <div className="mt-3 rounded-lg border p-3 text-sm" data-testid="mappings-dry-run">
          <p className="text-slate-600">
            {t("mappingsConsole.policy.dryRunSummary", {
              scanned: dryRun.scanned,
              changed: changed.length,
            })}
            {dryRun.degraded_semantic
              ? ` ${t("mappingsConsole.policy.dryRunDegraded")}`
              : ""}
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
            {changed.slice(0, 5).map((row) => (
              <li key={row.posting_id}>
                {row.before.state ?? "—"} → {row.after.state}
                {row.after.catalog_job_id ? ` (${row.after.catalog_job_id.slice(0, 8)})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
