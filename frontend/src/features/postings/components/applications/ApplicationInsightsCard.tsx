import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiDetail } from "@/api/client";
import {
  fetchApplicationInsights,
  type ApplicationInsights,
} from "@/api/applications";

function percent(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

export function ApplicationInsightsCard() {
  const { t } = useTranslation();
  const [data, setData] = useState<ApplicationInsights | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchApplicationInsights()
      .then(setData)
      .catch((err) => setError(apiDetail(err)));
  }, []);

  if (error !== "") {
    return (
      <p role="alert" className="text-xs text-[var(--as-danger)]" data-testid="insights-error">
        {error}
      </p>
    );
  }
  if (data === null) return null;

  return (
    <section
      className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="application-insights"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[var(--as-fg)]">
            {t("applicationInsights.title")}
          </h2>
          <p className="text-xs text-[var(--as-muted-fg)]">{t("applicationInsights.caveat")}</p>
        </div>
        <p className="text-xs font-medium text-[var(--as-fg)]" data-testid="insights-next">
          {data.next_action}
        </p>
      </div>
      {data.suppressed ? (
        <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="insights-suppressed">
          {t("applicationInsights.suppressed", { floor: data.floor })}
        </p>
      ) : (
        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs" data-testid="insights-rates">
          <div className="rounded border border-[var(--as-border)] p-2">
            <dt className="text-[var(--as-muted-fg)]">{t("applicationInsights.tailored")}</dt>
            <dd className="text-lg font-semibold text-[var(--as-fg)]">
              {percent(data.tailored.rate)}
            </dd>
            <dd className="text-[var(--as-muted-fg)]">
              n = {data.tailored.n} · {data.tailored.responses}{" "}
              {t("applicationInsights.responses")}
            </dd>
          </div>
          <div className="rounded border border-[var(--as-border)] p-2">
            <dt className="text-[var(--as-muted-fg)]">{t("applicationInsights.untailored")}</dt>
            <dd className="text-lg font-semibold text-[var(--as-fg)]">
              {percent(data.untailored.rate)}
            </dd>
            <dd className="text-[var(--as-muted-fg)]">
              n = {data.untailored.n} · {data.untailored.responses}{" "}
              {t("applicationInsights.responses")}
            </dd>
          </div>
        </dl>
      )}
      <p className="mt-2 text-[10px] text-[var(--as-muted-fg)]">{data.caveat}</p>
    </section>
  );
}
