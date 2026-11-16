import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  CalendarClock,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Info,
} from "lucide-react";

import { Card, SegmentedTabs } from "@/components/ui";
import {
  GRADE_ROWS,
  GRADE_SOURCES,
  MARKETS,
  MARKET_GUIDE_REVIEWED,
  type MarketId,
  type MarketSection,
} from "@/features/career/marketPacks";

const SECTION_KEYS = ["cv1", "cv2"] as const;
const NORM_KEYS = ["norms1", "norms2"] as const;
const CYCLE_KEYS = ["cycle1", "cycle2"] as const;

export function MarketGuide() {
  const { t, i18n } = useTranslation();
  const [marketId, setMarketId] = useState<MarketId>("uk");
  const market = MARKETS.find((item) => item.id === marketId) ?? MARKETS[0];
  const reviewed = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
  }).format(new Date(`${MARKET_GUIDE_REVIEWED}T12:00:00Z`));

  const sourceLinks = (section: MarketSection) => (
    <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--as-muted-fg)]">
      <span>{t("marketGuide.sourceLabel")}</span>
      {market.sources
        .filter((source) => source.section === section)
        .map((source) => (
          <a
            key={source.url}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 underline decoration-[var(--as-border)] underline-offset-2 hover:text-[var(--as-fg)]"
          >
            {t(source.labelKey)}
            <ExternalLink className="size-2.5" aria-hidden />
          </a>
        ))}
    </p>
  );

  return (
    <div className="mx-auto w-full max-w-5xl p-6" data-testid="market-guide">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--as-fg)]">
          {t("marketGuide.title")}
        </h1>
        <p className="mt-1 max-w-prose text-sm text-[var(--as-muted-fg)]">
          {t("marketGuide.subtitle")}
        </p>
        <p className="mt-2 max-w-prose text-xs text-[var(--as-muted-fg)]">
          {t("marketGuide.headerDisclaimer")}
        </p>
      </header>

      <Card className="mb-4 p-4" data-testid="market-guide-grades">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
          <FileText className="size-4 text-[var(--as-accent)]" aria-hidden />
          {t("marketGuide.grades.title")}
        </h2>
        <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
          {t("marketGuide.grades.intro")}
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-[var(--as-border)] text-[var(--as-muted-fg)]">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  {t("marketGuide.grades.uk")}
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  {t("marketGuide.grades.germany")}
                </th>
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  {t("marketGuide.grades.austria")}
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  {t("marketGuide.grades.note")}
                </th>
              </tr>
            </thead>
            <tbody>
              {GRADE_ROWS.map((row) => (
                <tr key={row} className="border-b border-[var(--as-border)] last:border-0">
                  <td className="py-1.5 pr-3 text-[var(--as-fg)]">
                    {t(`marketGuide.grades.rows.${row}.uk`)}
                  </td>
                  <td className="py-1.5 pr-3 text-[var(--as-fg)]">
                    {t(`marketGuide.grades.rows.${row}.de`)}
                  </td>
                  <td className="py-1.5 pr-3 text-[var(--as-fg)]">
                    {t(`marketGuide.grades.rows.${row}.at`)}
                  </td>
                  <td className="py-1.5 text-[var(--as-muted-fg)]">
                    {t(`marketGuide.grades.rows.${row}.note`)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
          {t("marketGuide.grades.disclaimer")}
        </p>
        <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
          {t("marketGuide.grades.austriaNote")}
        </p>
        {marketId === "ch" && (
          <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
            {t("marketGuide.markets.ch.gradeNote")}
          </p>
        )}
        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--as-muted-fg)]">
          <span>{t("marketGuide.grades.sourceLabel")}</span>
          {GRADE_SOURCES.map((source) => (
            <a
              key={source.url}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 underline decoration-[var(--as-border)] underline-offset-2 hover:text-[var(--as-fg)]"
            >
              {t(source.labelKey)}
              <ExternalLink className="size-2.5" aria-hidden />
            </a>
          ))}
        </p>
      </Card>

      <div className="mb-4">
        <SegmentedTabs
          ariaLabel={t("marketGuide.marketAria")}
          items={MARKETS.map((item) => ({
            value: item.id,
            label: t(`marketGuide.markets.${item.id}.label`),
          }))}
          value={marketId}
          onValueChange={(next) => setMarketId(next as MarketId)}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="p-4" data-testid="market-guide-cv">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <FileText className="size-4 text-[var(--as-accent)]" aria-hidden />
            {t("marketGuide.cvTitle")}
          </h2>
          <ul className="mt-2 list-disc space-y-2 pl-5 text-xs text-[var(--as-muted-fg)]">
            {SECTION_KEYS.map((key) => (
              <li key={key}>{t(`marketGuide.markets.${market.id}.${key}`)}</li>
            ))}
          </ul>
          {sourceLinks("cv")}
        </Card>

        <Card className="p-4" data-testid="market-guide-norms">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <ClipboardCheck className="size-4 text-[var(--as-accent)]" aria-hidden />
            {t("marketGuide.normsTitle")}
          </h2>
          <ul className="mt-2 list-disc space-y-2 pl-5 text-xs text-[var(--as-muted-fg)]">
            {NORM_KEYS.map((key) => (
              <li key={key}>{t(`marketGuide.markets.${market.id}.${key}`)}</li>
            ))}
          </ul>
          {sourceLinks("norms")}
        </Card>

        <Card className="p-4" data-testid="market-guide-cycle">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <CalendarClock className="size-4 text-[var(--as-accent)]" aria-hidden />
            {t("marketGuide.cycleTitle")}
          </h2>
          <ul className="mt-2 list-disc space-y-2 pl-5 text-xs text-[var(--as-muted-fg)]">
            {CYCLE_KEYS.map((key) => (
              <li key={key}>{t(`marketGuide.markets.${market.id}.${key}`)}</li>
            ))}
          </ul>
          {sourceLinks("cycle")}
        </Card>
      </div>

      <Card className="mt-4 p-4">
        <div className="flex flex-wrap items-start gap-2">
          <Info className="mt-0.5 size-4 shrink-0 text-[var(--as-accent)]" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-[var(--as-muted-fg)]">
              {t("marketGuide.disclaimer")}
            </p>
            <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
              {t("marketGuide.reviewed", { date: reviewed })}
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
