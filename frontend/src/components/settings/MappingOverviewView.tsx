import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  fetchMappingsOverview,
  fetchMappingsTrend,
  mappingsBackfill,
  mappingsCaptureSnapshot,
  mappingActionError,
  type MappingFunnelState,
  type MappingOverviewWithSwitches,
  type MappingTrendPoint,
} from "@/api/mappings";
import { apiDetail } from "@/api/client";
import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";

const FUNNEL_ORDER: MappingFunnelState[] = [
  "mapped",
  "ignored",
  "no_skills",
  "below_threshold",
  "no_candidate",
  "unmapped_by_admin",
  "unknown",
  "semantic_pending",
  "semantic_unavailable",
  "needs_review",
  "not_extracted",
  "extract_failed",
  "detail_not_fetched",
  "no_description",
];

/**
 * The Overview view (plan 205 S5): the honest funnel (AD1/AD2) as tiles +
 * bars, the accounted-for gate, the run controls' read-only switch states
 * with their Taxonomy home link, the retrieval health/index links and the
 * legacy backfill action.
 */
export function MappingOverviewView() {
  const { t } = useTranslation();
  const [data, setData] = useState<MappingOverviewWithSwitches | null>(null);
  const [trend, setTrend] = useState<MappingTrendPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    fetchMappingsOverview()
      .then(setData)
      .catch((caught) => setError(apiDetail(caught)));
    fetchMappingsTrend()
      .then((payload) => setTrend(payload.items))
      .catch(() => setTrend([]));
  }, []);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) {
    return (
      <div className="flex justify-center py-8">
        <Spinner className="h-6 w-6 text-slate-400" />
      </div>
    );
  }
  if (data.active === 0 && data.legacy_outcome_count === 0) {
    return (
      <EmptyState
        compact
        title={t("mappingsConsole.overview.emptyTitle")}
        description={t("mappingsConsole.overview.emptyBody")}
      />
    );
  }

  const states = data.states;
  const rate = Math.round(data.gate.rate * 100);
  const tiles: StatTile[] = [
    {
      label: t("mappingsConsole.overview.tileActive"),
      value: data.active,
      testId: "mappings-tile-active",
    },
    {
      label: t("mappingsConsole.overview.tileDescribed"),
      value: data.described,
      distribution: data.active ? (data.described / data.active) * 100 : 0,
      testId: "mappings-tile-described",
    },
    {
      label: t("mappingsConsole.overview.tileExtracted"),
      value: data.extracted,
      distribution: data.active ? (data.extracted / data.active) * 100 : 0,
      testId: "mappings-tile-extracted",
    },
    {
      label: t("mappingsConsole.overview.tileMapped"),
      value: data.mapped,
      distribution: data.active ? (data.mapped / data.active) * 100 : 0,
      testId: "mappings-tile-mapped",
    },
    {
      label: t("mappingsConsole.overview.tileAccounted"),
      value: data.accounted.total,
      hint: t("mappingsConsole.overview.tileAccountedHint", {
        mapped: data.accounted.mapped,
        machine: data.accounted.machine_terminal,
        human: data.accounted.human_terminal,
      }),
      distribution: data.active ? (data.accounted.total / data.active) * 100 : 0,
      sparkline: trend.map((point) => ({ count: point.accounted })),
      testId: "mappings-tile-accounted",
    },
  ];

  const captureSnapshot = async () => {
    setBusy(true);
    setNote(null);
    try {
      await mappingsCaptureSnapshot();
      setNote(t("mappingsConsole.overview.snapshotDone"));
      const payload = await fetchMappingsTrend();
      setTrend(payload.items);
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runBackfill = async () => {
    setBusy(true);
    setNote(null);
    try {
      await mappingsBackfill();
      setNote(t("mappingsConsole.overview.backfillQueued"));
      setData(await fetchMappingsOverview());
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const reasonRows = FUNNEL_ORDER.filter((state) => (states[state] ?? 0) > 0);

  return (
    <div className="space-y-5" data-testid="mappings-overview">
      <StatTiles tiles={tiles} columns={5} testId="mappings-stat-tiles" />

      <section
        className="rounded-xl border p-4"
        data-testid="mappings-gate"
        data-pass={data.gate.pass}
      >
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800">
            {t("mappingsConsole.overview.gateTitle")}
          </h3>
          <Badge variant={data.gate.pass ? "success" : "danger"}>
            {data.gate.pass
              ? t("mappingsConsole.overview.gatePass")
              : t("mappingsConsole.overview.gateFail")}
          </Badge>
          <span className="text-sm text-slate-500">
            {t("mappingsConsole.overview.gateLine", {
              rate,
              floor: Math.round(data.gate.floor * 100),
            })}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {t("mappingsConsole.overview.gateNote")}
        </p>
      </section>

      <section className="rounded-xl border p-4" data-testid="mappings-funnel">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">
          {t("mappingsConsole.overview.funnelTitle")}
        </h3>
        <ul className="space-y-1.5">
          {reasonRows.map((state) => {
            const count = states[state] ?? 0;
            const share = data.active ? (count / data.active) * 100 : 0;
            return (
              <li key={state} className="flex items-center gap-2 text-sm">
                <span className="w-44 shrink-0 text-slate-600">
                  {t(`mappingsConsole.state.${state}`)}
                </span>
                <span className="h-2 grow overflow-hidden rounded-full bg-slate-100">
                  <span
                    className="block h-full rounded-full bg-[var(--as-accent)]"
                    style={{ width: `${share}%` }}
                    data-testid={`mappings-bar-${state}`}
                  />
                </span>
                <span className="w-10 text-right tabular-nums text-slate-700">{count}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="rounded-xl border p-4" data-testid="mappings-proposals-legacy">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-600">
            {t("mappingsConsole.overview.proposals", { count: data.proposals_pending })}
          </span>
          <Link
            className="text-xs underline"
            to="/settings/taxonomy?tab=enrichment"
            data-testid="mappings-proposal-link"
          >
            {t("mappingsConsole.triage.proposalQueue")}
          </Link>
          <span className="grow" />
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void captureSnapshot()}
            data-testid="mappings-snapshot"
          >
            {t("mappingsConsole.overview.snapshot")}
          </Button>
          {data.legacy_outcome_count > 0 && (
            <>
              <span className="text-sm text-slate-600" data-testid="mappings-legacy-count">
                {t("mappingsConsole.overview.legacy", { count: data.legacy_outcome_count })}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void runBackfill()}
                data-testid="mappings-backfill"
              >
                {t("mappingsConsole.overview.backfill")}
              </Button>
            </>
          )}
        </div>
        {note && <p className="mt-2 text-sm text-slate-600">{note}</p>}
      </section>
    </div>
  );
}
