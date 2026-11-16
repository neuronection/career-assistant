import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Coins, Plus, Trash2 } from "lucide-react";
import {
  deleteAiPrice,
  fetchAiCosts,
  fetchAiPrices,
  saveAiPrice,
  type CostsResponse,
  type PricesResponse,
} from "@/api/aiPricing";
import { apiDetail } from "@/api/client";
import { Spinner } from "@/components/ui";
import type { AuditWindow } from "@/api/audit";

function usd(micros: number | null): string {
  if (micros === null) return "—";
  if (micros === 0) return "$0.00";
  return `$${(micros / 1_000_000).toFixed(4)}`;
}

export function DataCostCard({ window }: { window: AuditWindow }) {
  const { t } = useTranslation();
  const [costs, setCosts] = useState<CostsResponse | null>(null);
  const [prices, setPrices] = useState<PricesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    model: "",
    provider_key: "",
    input: "",
    output: "",
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([fetchAiCosts(window), fetchAiPrices()])
      .then(([costsData, pricesData]) => {
        if (cancelled) return;
        setCosts(costsData);
        setPrices(pricesData);
      })
      .catch((err) => {
        if (!cancelled) setError(apiDetail(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [window]);

  const reload = async () => {
    const [costData, priceData] = await Promise.all([
      fetchAiCosts(window),
      fetchAiPrices(),
    ]);
    setCosts(costData);
    setPrices(priceData);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await saveAiPrice({
        model: form.model.trim(),
        provider_key: form.provider_key.trim() || null,
        input_micros_per_million: Math.round(Number(form.input || 0) * 1_000_000),
        output_micros_per_million: Math.round(Number(form.output || 0) * 1_000_000),
      });
      setShowForm(false);
      setForm({ model: "", provider_key: "", input: "", output: "" });
      await reload();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    setError("");
    try {
      await deleteAiPrice(id);
      await reload();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const totals = useMemo(() => {
    const rows = costs?.rows ?? [];
    return {
      cost: rows.reduce((sum, row) => sum + (row.cost_micros ?? 0), 0),
      priced: rows.reduce((sum, row) => sum + row.priced_calls, 0),
      unpriced: rows.reduce((sum, row) => sum + row.unpriced_calls, 0),
    };
  }, [costs]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-[var(--as-muted-fg)]">
        <Spinner /> {t("common.loading")}
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-600">{error}</p>;

  return (
    <div
      data-testid="audit-data-cost"
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
    >
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <Coins className="h-4 w-4" />
            {t("audit.usage.dataCost", { defaultValue: "Data & cost" })}
          </h3>
          <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
            {t("audit.usage.dataCostHint", {
              defaultValue:
                "Cost is recorded at call time from the price in effect then. Unknown prices stay unpriced.",
            })}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-semibold tabular-nums text-[var(--as-fg)]">
            {usd(totals.cost)}
          </div>
          <div className="text-xs text-[var(--as-muted-fg)]">
            {t("audit.usage.pricedCalls", {
              defaultValue: "{{priced}} priced · {{unpriced}} unpriced",
              priced: totals.priced,
              unpriced: totals.unpriced,
            })}
          </div>
        </div>
      </div>

      {costs && costs.rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[var(--as-muted-fg)]">
                <th className="py-1.5 pr-3 font-medium">
                  {t("audit.usage.model", { defaultValue: "Model" })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t("audit.usage.calls", { defaultValue: "Calls" })}
                </th>
                <th className="py-1.5 pr-3 text-right font-medium">
                  {t("audit.usage.tokens", { defaultValue: "Tokens" })}
                </th>
                <th className="py-1.5 text-right font-medium">
                  {t("audit.usage.cost", { defaultValue: "Cost" })}
                </th>
              </tr>
            </thead>
            <tbody>
              {costs.rows.slice(0, 8).map((row) => (
                <tr
                  key={`${row.provider}:${row.model}`}
                  className="border-t border-[var(--as-border)]"
                >
                  <td className="max-w-[18rem] truncate py-1.5 pr-3 text-[var(--as-fg)]">
                    {row.model}
                    {row.unpriced_calls > 0 ? (
                      <span className="ml-1 text-[var(--as-muted-fg)]">
                        {t("audit.usage.unpriced", { count: row.unpriced_calls })}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {row.calls.toLocaleString()}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {(row.tokens_in + row.tokens_out).toLocaleString()}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-[var(--as-fg)]">
                    {usd(row.cost_micros)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t("audit.usage.noCostData", { defaultValue: "No billable calls in this range." })}
        </p>
      )}

      <div className="mt-3 space-y-2 border-t border-[var(--as-border)] pt-3">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold text-[var(--as-fg)]">
            {t("audit.usage.priceOverrides", { defaultValue: "Price overrides" })}
          </h4>
          <button
            type="button"
            onClick={() => setShowForm((value) => !value)}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--as-border)] px-2 py-1 text-xs text-[var(--as-fg)]"
          >
            <Plus className="h-3 w-3" />
            {t("audit.usage.addOverride", { defaultValue: "Add" })}
          </button>
        </div>

        {showForm ? (
          <form onSubmit={submit} className="grid gap-2 sm:grid-cols-5">
            <input
              required
              value={form.model}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
              placeholder={t("audit.usage.modelId", { defaultValue: "Model id" })}
              className="rounded-md border border-[var(--as-border)] bg-transparent px-2 py-1 text-xs text-[var(--as-fg)] sm:col-span-2"
            />
            <input
              value={form.provider_key}
              onChange={(event) => setForm({ ...form, provider_key: event.target.value })}
              placeholder={t("audit.usage.providerKey", { defaultValue: "Preset key" })}
              className="rounded-md border border-[var(--as-border)] bg-transparent px-2 py-1 text-xs text-[var(--as-fg)]"
            />
            <input
              required
              type="number"
              min="0"
              step="0.01"
              value={form.input}
              onChange={(event) => setForm({ ...form, input: event.target.value })}
              placeholder={t("audit.usage.inputPricePlaceholder")}
              className="rounded-md border border-[var(--as-border)] bg-transparent px-2 py-1 text-xs text-[var(--as-fg)]"
            />
            <input
              required
              type="number"
              min="0"
              step="0.01"
              value={form.output}
              onChange={(event) => setForm({ ...form, output: event.target.value })}
              placeholder={t("audit.usage.outputPricePlaceholder")}
              className="rounded-md border border-[var(--as-border)] bg-transparent px-2 py-1 text-xs text-[var(--as-fg)]"
            />
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-[var(--as-accent,var(--chart-1,#6172f3))] px-2 py-1 text-xs font-medium text-white disabled:opacity-50 sm:col-span-5"
            >
              {saving ? t("common.saving", { defaultValue: "Saving…" }) : t("common.save", { defaultValue: "Save" })}
            </button>
          </form>
        ) : null}

        {prices && prices.overrides.length > 0 ? (
          <ul className="space-y-1">
            {prices.overrides.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate text-[var(--as-fg)]">
                  {row.model}
                  {row.provider_key ? (
                    <span className="ml-1 text-[var(--as-muted-fg)]">({row.provider_key})</span>
                  ) : null}
                </span>
                <span className="flex-none tabular-nums text-[var(--as-muted-fg)]">
                  ${(row.input_micros_per_million / 1_000_000).toFixed(2)} / $ 
                  {(row.output_micros_per_million / 1_000_000).toFixed(2)}{" "}
                  {t("audit.usage.perMillion")}
                </span>
                <button
                  type="button"
                  aria-label={t("audit.usage.deleteOverride", { model: row.model })}
                  onClick={() => void remove(row.id)}
                  className="flex-none text-[var(--as-muted-fg)] hover:text-rose-600"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("audit.usage.noPriceOverrides", {
              defaultValue: "No overrides — built-in prices apply where known.",
            })}
          </p>
        )}
      </div>
    </div>
  );
}
