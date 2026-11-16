import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

import {
  fetchMappingsOverview,
  mappingsRedecideAll,
  type MappingOverviewWithSwitches,
  type MappingRedecideScope,
} from "@/api/mappings";
import { apiDetail } from "@/api/client";
import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { MappingAlertsCard } from "@/components/settings/MappingAlertsCard";
import { MappingPolicyCard } from "@/components/settings/MappingPolicyCard";
import { RETRIEVAL_RUNBOOK_URL } from "@/components/audit/retrieval/retrievalHelpers";

const SWITCH_LINK = "/settings/taxonomy?tab=relations";

/**
 * The Runs view (plan 205 S5): the three mapping switches shown READ-ONLY
 * with a link to their Taxonomy home (retrieval-ops §1/§6 — no move), the
 * job-index link to Tools → Retrieval (no second reindex action) and the
 * audit/runbook links.
 */
export function MappingRunsView() {
  const { t } = useTranslation();
  const [data, setData] = useState<MappingOverviewWithSwitches | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    fetchMappingsOverview()
      .then(setData)
      .catch((caught) => setError(apiDetail(caught)));
  }, []);

  const redecide = async (scope: MappingRedecideScope) => {
    if (!data) return;
    const confirmKey =
      scope === "all" ? "mappingsConsole.runs.forceConfirm" : "mappingsConsole.runs.confirm";
    if (!window.confirm(t(confirmKey, { count: data.active }))) return;
    setBusy(true);
    setNote(null);
    try {
      const result = await mappingsRedecideAll(scope);
      setNote(
        t("mappingsConsole.runs.queued", {
          count: result.active,
          scope: result.scope,
        }),
      );
      setData(await fetchMappingsOverview());
    } catch (caught) {
      setError(apiDetail(caught));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) {
    return (
      <div className="flex justify-center py-8">
        <Spinner className="h-6 w-6 text-slate-400" />
      </div>
    );
  }
  if (!data.last_remap && data.active === 0) {
    return (
      <EmptyState
        compact
        title={t("mappingsConsole.empty.runs.title")}
        description={t("mappingsConsole.empty.runs.description")}
      />
    );
  }

  return (
    <div className="space-y-5" data-testid="mappings-runs">
      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border p-4" data-testid="mappings-run-controls">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">
            {t("mappingsConsole.overview.runControlsTitle")}
          </h3>
          <ul className="space-y-1.5 text-sm">
            {(
              [
                ["job_proposals", "jobProposals"],
                ["semantic_rescue", "semanticRescue"],
                ["semantic_rerank", "semanticRerank"],
              ] as const
            ).map(([key, labelKey]) => (
              <li key={key} className="flex items-center gap-2">
                <Badge variant={data.switches[key] ? "success" : "secondary"}>
                  {data.switches[key]
                    ? t("mappingsConsole.overview.switchOn")
                    : t("mappingsConsole.overview.switchOff")}
                </Badge>
                <span className="text-slate-600">
                  {t(`mappingsConsole.overview.switch.${labelKey}`)}
                </span>
              </li>
            ))}
          </ul>
          <Link
            className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--as-accent)] underline-offset-2 hover:underline"
            to={SWITCH_LINK}
            data-testid="mappings-switch-link"
          >
            {t("mappingsConsole.overview.switchLink")}
            <ArrowUpRight className="size-3" />
          </Link>
          <p className="mt-1 text-xs text-slate-500">
            {t("mappingsConsole.overview.switchNote")}
          </p>
          <div className="mt-3 border-t pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void redecide("stale")}
                data-testid="mappings-redecide-stale"
              >
                {t("mappingsConsole.runs.redecideAll")}
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void redecide("all")}
                data-testid="mappings-redecide-force-all"
              >
                {t("mappingsConsole.runs.forceAll")}
              </Button>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {t("mappingsConsole.runs.redecideAllNote")}
            </p>
            {note && <p className="text-xs text-slate-600">{note}</p>}
          </div>
        </div>

        <div className="rounded-xl border p-4" data-testid="mappings-runbook-links">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">
            {t("mappingsConsole.overview.linksTitle")}
          </h3>
          <ul className="space-y-1.5 text-sm">
            <li>
              <Link
                className="underline-offset-2 hover:underline"
                to="/settings/tools?section=retrieval"
                data-testid="mappings-index-link"
              >
                {t("mappingsConsole.overview.indexLink")}
              </Link>
            </li>
            <li>
              <Link
                className="underline-offset-2 hover:underline"
                to="/settings/audit?tab=retrieval&section=overview"
                data-testid="mappings-audit-link"
              >
                {t("mappingsConsole.overview.auditLink")}
              </Link>
            </li>
            <li>
              <a
                className="underline-offset-2 hover:underline"
                href={RETRIEVAL_RUNBOOK_URL}
                target="_blank"
                rel="noreferrer"
                data-testid="mappings-runbook-link"
              >
                {t("mappingsConsole.overview.runbookLink")}
              </a>
            </li>
          </ul>
          {data.last_remap && (
            <p className="mt-2 text-xs text-slate-500" data-testid="mappings-last-remap">
              {t("mappingsConsole.overview.lastRemap", {
                status: data.last_remap.status,
              })}
              {data.last_remap.created_at
                ? ` · ${new Date(data.last_remap.created_at).toLocaleString()}`
                : ""}
            </p>
          )}
        </div>

      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        <MappingPolicyCard />
        <MappingAlertsCard />
      </div>
      <p className="text-xs text-slate-500">{t("mappingsConsole.overview.switchNote")}</p>
    </div>
  );
}
