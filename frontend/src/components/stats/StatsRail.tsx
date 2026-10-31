import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ExternalLink, RefreshCw } from "lucide-react";

import { StatTiles } from "@/components/stats/StatTiles";
import { DeltaBadge } from "@/components/stats/charts/DeltaBadge";
import { Sparkline } from "@/components/stats/charts/Sparkline";
import { SkillTrendList } from "@/components/stats/charts/SkillTrendList";
import {
  fetchCompanyStatsOverview,
  fetchCompanyStatsSummary,
  fetchPostingStatsBreakdown,
  fetchPostingStatsSkills,
  fetchPostingStatsSummary,
  type PostingStatsSkills,
  type PostingStatsSummary,
  type CompanyStatsOverview,
  type CompanyStatsSummary,
  type BreakdownRow,
} from "@/api/stats";

const RAIL_WINDOW = "30d";

/** The consolidated stats rail (plan 170 slice 3): the market pulse as a
 * third column on `/postings` and `/companies` — one card set, thin page
 * wrappers. Every chip applies its filter mapping through the owning
 * page's URL-state seam; metrics without one render plain. Fetches only
 * the summary/aggregates needed for these chips — never the page's full
 * suite. */

function OutOfService({ note }: { note: string }) {
  return (
    <p className="py-2 text-xs text-[var(--as-muted-fg)]" data-testid="stats-rail-note">
      {note}
    </p>
  );
}

function RailShell({
  title,
  refresh,
  children,
}: {
  title: string;
  refresh?: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const { t } = useTranslation();
  return (
    <aside data-testid="stats-rail" className="ca-stats-rail min-w-0">
      <details
        open={open}
        className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      >
        <summary
          className="flex cursor-pointer list-none items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
          data-testid="stats-rail-toggle"
          aria-expanded={open}
          onClick={(event) => {
            event.preventDefault();
            setOpen((value) => !value);
          }}
        >
          {t("marketStats.rail.title")}
          {refresh ? (
            <button
              type="button"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                refresh();
              }}
              className="rounded p-0.5 text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              aria-label={title}
              data-testid="stats-rail-refresh"
            >
              <RefreshCw className="size-3" aria-hidden />
            </button>
          ) : null}
        </summary>
        <div className="mt-2">{children}</div>
      </details>
    </aside>
  );
}

/** The postings market pulse: pulse tiles (open basis — the explore
 * feed's basis), the 14-day sparkline, rising skills and top sources. */
export function PostingsStatsRail({
  onPostedWithin,
  onSkill,
  onSource,
}: {
  onPostedWithin: (value: string) => void;
  onSkill: (key: string) => void;
  onSource: (key: string) => void;
}) {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<PostingStatsSummary | null>(null);
  const [skills, setSkills] = useState<PostingStatsSkills | null>(null);
  const [sources, setSources] = useState<BreakdownRow[]>([]);
  const [failed, setFailed] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setFailed(false);
    const results = await Promise.allSettled([
      fetchPostingStatsSummary({ status_basis: "open" }),
      fetchPostingStatsSkills({ window: RAIL_WINDOW, status_basis: "open" }),
      fetchPostingStatsBreakdown("source", {
        window: RAIL_WINDOW,
        status_basis: "open",
        limit: 3,
      }),
    ]);
    if (id !== requestId.current) return;
    const [rSummary, rSkills, rSources] = results;
    setSummary(rSummary.status === "fulfilled" ? rSummary.value : null);
    setSkills(rSkills.status === "fulfilled" ? rSkills.value : null);
    setSources(
      rSources.status === "fulfilled" ? rSources.value.rows.slice(0, 3) : []
    );
    if (results.every((result) => result.status === "rejected")) setFailed(true);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <RailShell title={t("marketStats.rail.title")} refresh={() => void load()}>
      {failed ? (
        <OutOfService note={t("marketStats.rail.unavailable")} />
      ) : (
        <>
          <StatTiles
            testId="rail-postings"
            layout="auto"
            columns={2}
            tiles={
              summary
                ? [
                    {
                      label: t("marketStats.tiles.new24h"),
                      value: summary.new_24h.count.toLocaleString(),
                      hint: <DeltaBadge delta={summary.new_24h} />,
                      onClick: () => onPostedWithin("24h"),
                      testId: "rail-posted-24h",
                    },
                    {
                      label: t("marketStats.tiles.new7d"),
                      value: summary.new_7d.count.toLocaleString(),
                      hint: <DeltaBadge delta={summary.new_7d} />,
                      onClick: () => onPostedWithin("7d"),
                      testId: "rail-posted-7d",
                    },
                    {
                      label: t("marketStats.tiles.new30d"),
                      value: summary.new_30d.count.toLocaleString(),
                      hint: <DeltaBadge delta={summary.new_30d} />,
                      onClick: () => onPostedWithin("30d"),
                      testId: "rail-posted-30d",
                    },
                    {
                      label: t("marketStats.tiles.openTotal"),
                      value: summary.open_total.toLocaleString(),
                    },
                  ]
                : []
            }
          />
          {summary ? <Sparkline points={summary.sparkline} testId="rail-sparkline" /> : null}
          <RailSection label={t("marketStats.skills.rising")}>
            <SkillTrendList
              rows={skills?.rising ?? []}
              max={5}
              testKey="rail-skill"
              onSelect={(row) => onSkill(row.key)}
            />
          </RailSection>
          <RailSection label={t("marketStats.rail.topSources")}>
            <SourceRows rows={sources} onSource={onSource} />
          </RailSection>
          <Link
            to="/postings/stats"
            className="mt-2 flex items-center gap-1 text-xs font-medium text-[var(--as-accent,var(--chart-1,#6172f3))] hover:underline"
            data-testid="rail-open-full"
          >
            {t("marketStats.rail.openFull")}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        </>
      )}
    </RailShell>
  );
}

function RailSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-3">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {label}
      </p>
      {children}
    </div>
  );
}

function SourceRows({
  rows,
  onSource,
}: {
  rows: BreakdownRow[];
  onSource: (key: string) => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--as-muted-fg)]">{t("marketStats.noData")}</p>;
  }
  return (
    <ul className="space-y-1">
      {rows.map((row) => (
        <li key={row.key}>
          <button
            type="button"
            onClick={() => onSource(row.key)}
            data-testid={`rail-source-${row.key}`}
            className="flex w-full items-baseline gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
          >
            <span className="min-w-0 flex-1 truncate text-left font-medium text-[var(--as-fg)]">
              {row.key}
            </span>
            <span className="tabular-nums text-[var(--as-muted-fg)]">
              {row.count.toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** The companies pulse: hiring tiles, new-in-window chip, top industries
 * and the busiest companies — all linking into the company pages' own
 * filter vocabulary. */
export function CompaniesStatsRail({
  onNewCompanies,
  onIndustry,
  onCompany,
}: {
  onNewCompanies: () => void;
  onIndustry: (key: string) => void;
  onCompany: (key: string) => void;
}) {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<CompanyStatsSummary | null>(null);
  const [overview, setOverview] = useState<CompanyStatsOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setFailed(false);
    const results = await Promise.allSettled([
      fetchCompanyStatsSummary({ window: RAIL_WINDOW, status_basis: "open" }),
      fetchCompanyStatsOverview({
        window: RAIL_WINDOW,
        status_basis: "open",
        limit: 3,
      }),
    ]);
    if (id !== requestId.current) return;
    const [rSummary, rOverview] = results;
    setSummary(rSummary.status === "fulfilled" ? rSummary.value : null);
    setOverview(rOverview.status === "fulfilled" ? rOverview.value : null);
    if (results.every((result) => result.status === "rejected")) setFailed(true);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <RailShell title={t("marketStats.rail.title")}>
      {failed ? (
        <OutOfService note={t("marketStats.rail.unavailable")} />
      ) : (
        <>
          <StatTiles
            testId="rail-companies"
            layout="auto"
            columns={2}
            tiles={
              summary
                ? [
                    {
                      label: t("marketStats.companies.hiring"),
                      value: summary.companies_hiring.toLocaleString(),
                    },
                    {
                      label: t("marketStats.companies.newCompanies"),
                      value: summary.new_companies.count.toLocaleString(),
                      hint: <DeltaBadge delta={summary.new_companies} />,
                      onClick: onNewCompanies,
                      testId: "rail-new-companies",
                    },
                  ]
                : []
            }
          />
          <RailSection label={t("marketStats.companies.topHiring")}>
            <ul className="space-y-1">
              {(overview?.top_hiring ?? []).slice(0, 3).map((company) => (
                <li key={company.key}>
                  <button
                    type="button"
                    onClick={() => onCompany(company.key)}
                    data-testid={`rail-company-${company.key}`}
                    className="flex w-full items-baseline gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
                  >
                    <span className="min-w-0 flex-1 truncate text-left font-medium text-[var(--as-fg)]">
                      {company.name}
                    </span>
                    <span className="tabular-nums text-[var(--as-muted-fg)]">
                      {company.open_postings.toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </RailSection>
          <RailSection label={t("marketStats.companies.industryMix")}>
            <ul className="space-y-1">
              {(overview?.industry_mix ?? []).slice(0, 3).map((industry) => (
                <li key={industry.key}>
                  <button
                    type="button"
                    onClick={() => onIndustry(industry.key)}
                    data-testid={`rail-industry-${industry.key}`}
                    className="flex w-full items-baseline gap-2 rounded-lg px-1.5 py-1 text-xs transition-colors hover:bg-[var(--as-muted)]"
                  >
                    <span className="min-w-0 flex-1 truncate text-left text-[var(--as-fg)]">
                      {industry.key}
                    </span>
                    <span className="tabular-nums text-[var(--as-muted-fg)]">
                      {industry.count.toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </RailSection>
          <Link
            to="/postings/stats"
            className="mt-2 flex items-center gap-1 text-xs font-medium text-[var(--as-accent,var(--chart-1,#6172f3))] hover:underline"
            data-testid="rail-open-full"
          >
            {t("marketStats.rail.openFull")}
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        </>
      )}
    </RailShell>
  );
}
