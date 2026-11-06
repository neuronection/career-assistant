import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  fetchMappingsQuality,
  mappingsResolve,
  mappingsSample,
  mappingActionError,
  type MappingQuality,
} from "@/api/mappings";
import { apiDetail } from "@/api/client";
import { Badge, Button, EmptyState, Spinner } from "@/components/ui";
import { NumberField } from "@/features/cv/components/cv/formPrimitives";

function pct(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

/**
 * The Quality view (plan 205 S7): golden set + sampled audit with the
 * precision/recall/agreement metrics, the confusion pairs and the
 * ADVISORY gate. Resolving happens from the pending rows here and from
 * the trace drawer ("Mark correct/wrong").
 */
export function MappingQualityView() {
  const { t } = useTranslation();
  const [data, setData] = useState<MappingQuality | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sampleCount, setSampleCount] = useState(20);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetchMappingsQuality());
      setError(null);
    } catch (caught) {
      setError(apiDetail(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (reviewId: string, correct: boolean) => {
    setBusy(true);
    setNote(null);
    try {
      await mappingsResolve(reviewId, correct);
      await load();
    } catch (caught) {
      setNote(mappingActionError(caught));
    } finally {
      setBusy(false);
    }
  };

  const runSample = async () => {
    setBusy(true);
    setNote(null);
    try {
      const result = await mappingsSample(sampleCount);
      setNote(t("mappingsConsole.quality.sampleDone", { count: result.created }));
      await load();
    } catch (caught) {
      setNote(mappingActionError(caught));
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

  const gateBadge =
    data.gate.state === "pass" ? (
      <Badge variant="success">{t("mappingsConsole.quality.gatePass")}</Badge>
    ) : data.gate.state === "no-golden" ? (
      <Badge variant="secondary">{t("mappingsConsole.quality.noGolden")}</Badge>
    ) : (
      <Badge variant="danger">{t("mappingsConsole.quality.gateFail")}</Badge>
    );

  return (
    <div className="space-y-5" data-testid="mappings-quality">
      <section className="rounded-xl border p-4" data-testid="mappings-quality-gate">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800">
            {t("mappingsConsole.quality.gateTitle")}
          </h3>
          {gateBadge}
          <span className="text-sm text-slate-500">
            {t("mappingsConsole.quality.gateLine", {
              min: data.gate.min_golden,
              floor: Math.round(data.gate.precision_floor * 100),
              resolved: data.golden.resolved,
            })}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {t("mappingsConsole.quality.advisoryNote")}
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        {(
          [
            ["golden", data.golden],
            ["sample", data.sample],
          ] as const
        ).map(([kind, stats]) => (
          <div key={kind} className="rounded-xl border p-4" data-testid={`mappings-quality-${kind}`}>
            <h3 className="mb-2 text-sm font-semibold text-slate-800">
              {t(`mappingsConsole.quality.${kind}Title`)}
            </h3>
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-500">{t("mappingsConsole.quality.resolved")}</dt>
                <dd>{stats.resolved}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">{t("mappingsConsole.quality.precision")}</dt>
                <dd>{pct(stats.precision)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">{t("mappingsConsole.quality.recall")}</dt>
                <dd>{pct(stats.recall)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">{t("mappingsConsole.quality.agreement")}</dt>
                <dd>{pct(stats.agreement)}</dd>
              </div>
            </dl>
          </div>
        ))}
      </section>

      {data.confusion.length > 0 && (
        <section className="rounded-xl border p-4" data-testid="mappings-confusion">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">
            {t("mappingsConsole.quality.confusionTitle")}
          </h3>
          <ul className="space-y-1 text-sm text-slate-600">
            {data.confusion.map((pair) => (
              <li key={`${pair.predicted}->${pair.expected}`}>
                {pair.predicted} → {pair.expected}: {pair.count}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-xl border p-4" data-testid="mappings-sample-card">
        <div className="flex flex-wrap items-end gap-3">
          <h3 className="text-sm font-semibold text-slate-800">
            {t("mappingsConsole.quality.sampleCardTitle")}
          </h3>
          <div className="w-28">
            <NumberField
              label={t("mappingsConsole.quality.sampleCount")}
              value={sampleCount}
              onChange={(value) => setSampleCount(value ?? 20)}
              min={1}
              max={50}
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void runSample()}
            data-testid="mappings-sample-create"
          >
            {t("mappingsConsole.quality.sampleCreate")}
          </Button>
        </div>
      </section>

      {note && <p className="text-sm text-slate-600">{note}</p>}

      <section className="rounded-xl border p-4" data-testid="mappings-pending">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">
          {t("mappingsConsole.quality.pendingTitle")}
        </h3>
        {data.pending.length === 0 ? (
          <EmptyState
            compact
            title={t("mappingsConsole.quality.pendingEmptyTitle")}
            description={t("mappingsConsole.quality.pendingEmptyBody")}
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm" data-testid="mappings-pending-table">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">{t("mappingsConsole.quality.colPosting")}</th>
                  <th className="px-3 py-2">{t("mappingsConsole.quality.colKind")}</th>
                  <th className="px-3 py-2">{t("mappingsConsole.quality.colExpected")}</th>
                  <th className="px-3 py-2" aria-label={t("mappingsConsole.quality.resolve")} />
                </tr>
              </thead>
              <tbody>
                {data.pending.map((row) => (
                  <tr key={row.id} data-testid="mappings-pending-row">
                    <td className="px-3 py-2">
                      {row.posting.title}
                      <span className="ml-2 text-xs text-slate-400">{row.posting.ref}</span>
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={row.kind === "golden" ? "default" : "secondary"}>
                        {t(`mappingsConsole.quality.kind.${row.kind}`)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                      {row.expected_job_id ?? t("mappingsConsole.quality.expectedNone")}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() => void resolve(row.id, true)}
                          data-testid={`mappings-correct-${row.id}`}
                        >
                          {t("mappingsConsole.quality.markCorrect")}
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={busy}
                          onClick={() => void resolve(row.id, false)}
                          data-testid={`mappings-wrong-${row.id}`}
                        >
                          {t("mappingsConsole.quality.markWrong")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
