import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Scale } from "lucide-react";

import { apiDetail } from "@/api/client";
import { formatMoney } from "@/lib/money";
import { formatDay } from "@/lib/time";
import { fetchOfferComparison } from "@/api/offers";
import { Button, Card, EmptyState, Spinner } from "@/components/ui";
import type { OfferComparison } from "@/types/application";

export function OfferComparisonPage() {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<OfferComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setData(null);
    void fetchOfferComparison()
      .then(setData)
      .catch((err) => setError(apiDetail(err)));
  }, []);

  useEffect(load, [load]);

  if (error !== null) {
    return (
      <div className="mx-auto max-w-5xl p-6" data-testid="offers-page">
        <div data-testid="offers-error">
          <EmptyState
            title={t("offers.errorTitle")}
            description={error || t("offers.errorBody")}
            action={
              <Button variant="outline" onClick={load}>
                {t("offers.retry")}
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  if (data === null) {
    return (
      <div className="flex justify-center p-10" data-testid="offers-loading">
        <Spinner />
      </div>
    );
  }

  if (data.total === 0) {
    return (
      <div className="mx-auto max-w-5xl p-6" data-testid="offers-page">
        <EmptyState
          title={t("offers.emptyTitle")}
          description={t("offers.emptyBody")}
          action={
            <Link to="/applications" className="text-sm text-[var(--as-accent)]">
              {t("offers.openTracker")}
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl p-6" data-testid="offers-page">
      <header className="mb-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-[var(--as-fg)]">
          <Scale className="size-5 text-[var(--as-accent)]" aria-hidden />
          {t("offers.title")}
        </h1>
        <p className="mt-1 max-w-prose text-sm text-[var(--as-muted-fg)]">
          {t("offers.subtitle")}
        </p>
        {data.total > data.items.length && (
          <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
            {t("offers.truncated", { count: data.items.length, total: data.total })}
          </p>
        )}
      </header>

      {data.mixed_currencies && (
        <p
          className="mb-3 rounded border border-[color-mix(in_srgb,var(--as-warning)_25%,transparent)] bg-[var(--as-surface)] p-2 text-xs text-[var(--as-fg)]"
          data-testid="offers-mixed-currency"
        >
          {t("offers.mixedCurrency")}
        </p>
      )}

      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[42rem] border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-[var(--as-border)] align-top">
              <th scope="col" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.rowLabel")}
              </th>
              {data.items.map((offer) => (
                <th
                  key={offer.application_id}
                  scope="col"
                  className="p-3 font-medium text-[var(--as-fg)]"
                  data-testid={`offer-header-${offer.application_id}`}
                >
                  <Link
                    to={`/applications/${offer.application_id}`}
                    className="hover:underline"
                  >
                    {offer.posting_title}
                  </Link>
                  <span className="mt-0.5 block text-[11px] font-normal text-[var(--as-muted-fg)]">
                    {offer.posting_org}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.annual")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {formatMoney(offer.annual_amount, offer.currency, i18n.language)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.monthly")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {formatMoney(offer.monthly_amount, offer.currency, i18n.language)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.location")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {offer.location || "—"}
                </td>
              ))}
            </tr>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.costOfLiving")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {formatMoney(offer.annual_cost_of_living, offer.currency, i18n.language)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.netAfterCol")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {formatMoney(offer.net_annual_after_col, offer.currency, i18n.language)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-[var(--as-border)]">
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.benefits")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {offer.benefits.length === 0 ? (
                    "—"
                  ) : (
                    <ul className="list-disc space-y-0.5 pl-4">
                      {offer.benefits.map((benefit) => (
                        <li key={benefit}>{benefit}</li>
                      ))}
                    </ul>
                  )}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row" className="p-3 font-medium text-[var(--as-muted-fg)]">
                {t("offers.deadline")}
              </th>
              {data.items.map((offer) => (
                <td key={offer.application_id} className="p-3 text-[var(--as-fg)]">
                  {formatDay(offer.deadline, i18n.language)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </Card>

      <p className="mt-3 text-xs text-[var(--as-muted-fg)]">
        {t("offers.disclaimer")}
      </p>
      <Link
        to="/applications"
        className="mt-3 inline-block text-sm text-[var(--as-accent)] hover:underline"
      >
        {t("offers.back")}
      </Link>
    </div>
  );
}
