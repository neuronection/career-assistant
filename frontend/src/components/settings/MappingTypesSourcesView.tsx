import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { fetchSourcesBreakdown, fetchJobTypesBreakdown, type JobTypesBreakdown, type SourceBreakdown } from "@/api/mappings";
import { apiDetail } from "@/api/client";
import { Badge, EmptyState, Spinner } from "@/components/ui";

const STATE_ORDER = [
  "no_description",
  "detail_not_fetched",
  "extract_failed",
  "not_extracted",
  "needs_review",
  "semantic_unavailable",
  "semantic_pending",
  "no_skills",
  "below_threshold",
  "no_candidate",
  "unmapped_by_admin",
  "unknown",
] as const;

/**
 * The Types & sources view (plan 205 S4): the per-source funnel table and
 * the per-job-type table with the zero-posting flag and the capped
 * proposal clusters.
 */
export function MappingTypesSourcesView() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<SourceBreakdown[] | null>(null);
  const [types, setTypes] = useState<JobTypesBreakdown | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSourcesBreakdown(), fetchJobTypesBreakdown()])
      .then(([sourceItems, typeItems]) => {
        setSources(sourceItems.items);
        setTypes(typeItems);
      })
      .catch((caught) => setError(apiDetail(caught)));
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (sources === null || types === null) {
    return (
      <div className="flex justify-center py-8">
        <Spinner className="h-6 w-6 text-slate-400" />
      </div>
    );
  }
  if (sources.length === 0 && types.items.length === 0) {
    return (
      <EmptyState
        compact
        title={t("mappingsConsole.typesSources.emptyTitle")}
        description={t("mappingsConsole.typesSources.emptyBody")}
      />
    );
  }

  return (
    <div className="space-y-6" data-testid="mappings-types-sources">
      <section className="rounded-xl border p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">
          {t("mappingsConsole.typesSources.sourcesTitle")}
        </h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" data-testid="mappings-sources-table">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colSource")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colDetailMode")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colActive")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colDescribed")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colExtracted")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colMapped")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colAccounted")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colTopReason")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colLastSync")}</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const topReason = STATE_ORDER.map(
                  (state) =>
                    [state, source.states[state] ?? 0] as [
                      (typeof STATE_ORDER)[number],
                      number,
                    ],
                ).filter(([, count]) => count > 0)[0];
                return (
                  <tr key={source.source_id} data-testid="mappings-source-row">
                    <td className="px-3 py-2">
                      <Link
                        className="underline-offset-2 hover:underline"
                        to="/settings/tools?section=sources"
                      >
                        {source.title}
                      </Link>
                      {source.paused && (
                        <Badge variant="warning" className="ml-2">
                          {t("mappingsConsole.typesSources.paused")}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{source.detail_mode}</td>
                    <td className="px-3 py-2">{source.active}</td>
                    <td className="px-3 py-2">{source.described}</td>
                    <td className="px-3 py-2">{source.extracted}</td>
                    <td className="px-3 py-2">{source.mapped}</td>
                    <td className="px-3 py-2">{source.accounted}</td>
                    <td className="px-3 py-2 text-slate-600">
                      {topReason ? t(`mappingsConsole.state.${topReason[0]}`) : "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-500">
                      {source.last_run_at
                        ? new Date(source.last_run_at).toLocaleDateString()
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">
          {t("mappingsConsole.typesSources.typesTitle")}
        </h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" data-testid="mappings-job-types-table">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colType")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colFamily")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colMappedPostings")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colOpenRoles")}</th>
                <th className="px-3 py-2">{t("mappingsConsole.typesSources.colFlag")}</th>
              </tr>
            </thead>
            <tbody>
              {types.items.map((entry) => (
                <tr key={entry.job_id} data-testid="mappings-job-type-row">
                  <td className="px-3 py-2">
                    <Link className="underline-offset-2 hover:underline" to={`/jobs/${entry.code}`}>
                      {entry.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{entry.family ?? "—"}</td>
                  <td className="px-3 py-2">{entry.mapped_postings}</td>
                  <td className="px-3 py-2">{entry.open_roles}</td>
                  <td className="px-3 py-2">
                    {entry.zero_postings && (
                      <Badge variant="warning">{t("mappingsConsole.typesSources.zero")}</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {types.proposal_clusters.length > 0 && (
          <div className="mt-3" data-testid="mappings-proposal-clusters">
            <p className="mb-1 text-sm font-semibold text-slate-800">
              {t("mappingsConsole.typesSources.clustersTitle")}
            </p>
            <ul className="flex flex-wrap gap-2">
              {types.proposal_clusters.map((cluster) => (
                <li key={cluster.job_type}>
                  <Badge variant="secondary">
                    {cluster.job_type} · {cluster.postings}
                  </Badge>
                </li>
              ))}
            </ul>
            <Link
              className="mt-2 inline-block text-xs underline"
              to="/settings/taxonomy?tab=enrichment"
            >
              {t("mappingsConsole.triage.proposalQueue")}
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
