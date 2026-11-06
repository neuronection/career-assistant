import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarRange, RotateCw, SlidersHorizontal, X } from "lucide-react";

import { PanelModal, SegmentedTabs } from "@/components/ui";
import { useAuthStore } from "@/stores/authStore";
import {
  MARKET_WINDOWS,
  activeSegments,
  addIsoDays,
  compareRange,
  spanDays,
  type MarketSegments,
  type MarketStatsView,
} from "../marketStatsParams";
import type { ContainerBand } from "@/hooks/useContainerBand";

const EDUCATION_VALUES = [
  "no_formal",
  "middle_school",
  "high_school",
  "bachelor",
  "master",
  "doctorate",
] as const;

const LIST_FIELDS: { key: keyof MarketSegments; labelKey: string }[] = [
  { key: "source", labelKey: "marketStats.filters.source" },
  { key: "org", labelKey: "marketStats.filters.org" },
  { key: "mapped_family", labelKey: "marketStats.filters.family" },
  { key: "seniority", labelKey: "marketStats.filters.seniority" },
  { key: "remote_policy", labelKey: "marketStats.filters.workMode" },
  { key: "employment_type", labelKey: "marketStats.filters.employment" },
  { key: "contract", labelKey: "marketStats.filters.contract" },
];

function dateInputClass(): string {
  return "min-h-[44px] rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-sm text-[var(--as-fg)]";
}

function chipClass(): string {
  return "inline-flex min-h-[44px] items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2.5 text-xs text-[var(--as-fg)]";
}

export function StatsFilterBar({
  view,
  band,
  loading,
  onPatch,
  onRefresh,
}: {
  view: MarketStatsView;
  band: ContainerBand;
  loading: boolean;
  onPatch: (update: Partial<MarketStatsView>) => void;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const [sheetOpen, setSheetOpen] = useState(false);
  const isAdmin = useAuthStore((state) => Boolean(state.user?.is_admin));
  const chips = activeSegments(view.segments);
  const segments = view.segments;
  const patchSegments = (update: Partial<MarketSegments>) =>
    onPatch({ segments: { ...segments, ...update } });

  const removeChip = (axis: string, value: string) => {
    if (axis === "education_min" || axis === "city" || axis === "country" || axis === "q") {
      patchSegments({ [axis]: "" } as Partial<MarketSegments>);
    } else if (axis === "salary_min") {
      patchSegments({ salary_min: "" });
    } else if (axis === "skill_mode") {
      patchSegments({ skill_mode: "" });
    } else if (axis === "hidden_include") {
      patchSegments({ hidden_include: false });
    } else if (axis === "skills") {
      const remaining = segments.skills
        .split(",")
        .filter((entry) => entry.trim() !== value);
      patchSegments({ skills: remaining.join(",") });
    } else {
      const key = axis as keyof MarketSegments;
      const values = (segments[key] as string[]).filter((entry) => entry !== value);
      patchSegments({ [key]: values } as Partial<MarketSegments>);
    }
  };

  const fields = (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="market-stats-filter-fields">
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.q")}
        <input
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.q}
          onChange={(event) => patchSegments({ q: event.target.value })}
          data-testid="market-stats-filter-q"
        />
      </label>
      {LIST_FIELDS.map((field) => (
        <label key={field.key} className="text-xs text-[var(--as-muted-fg)]">
          {t(field.labelKey)}{" "}
          <span className="text-[10px]">{t("marketStats.filters.commaHint")}</span>
          <input
            className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
            value={(segments[field.key] as string[]).join(",")}
            onChange={(event) =>
              patchSegments({
                [field.key]: event.target.value
                  .split(",")
                  .map((part) => part.trim())
                  .filter(Boolean),
              } as Partial<MarketSegments>)
            }
            data-testid={`market-stats-filter-${field.key}`}
          />
        </label>
      ))}
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.education")}
        <select
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.education_min}
          onChange={(event) => patchSegments({ education_min: event.target.value })}
          data-testid="market-stats-filter-education_min"
        >
          <option value="">{t("marketStats.filters.any")}</option>
          {EDUCATION_VALUES.map((value) => (
            <option key={value} value={value}>
              {t(`marketStats.value.${value}`, { defaultValue: value.replace(/_/g, " ") })}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.city")}
        <input
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.city}
          onChange={(event) => patchSegments({ city: event.target.value })}
          data-testid="market-stats-filter-city"
        />
      </label>
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.country")}
        <input
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.country}
          onChange={(event) => patchSegments({ country: event.target.value })}
          data-testid="market-stats-filter-country"
        />
      </label>
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.skills")}
        <input
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.skills}
          placeholder={t("marketStats.filters.skillsPlaceholder")}
          onChange={(event) => patchSegments({ skills: event.target.value })}
          data-testid="market-stats-filter-skills"
        />
      </label>
      <label className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.salaryMin")}
        <input
          type="number"
          min={0}
          className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-2 text-sm text-[var(--as-fg)]"
          value={segments.salary_min}
          onChange={(event) => patchSegments({ salary_min: event.target.value })}
          data-testid="market-stats-filter-salary_min"
        />
      </label>
      <div className="text-xs text-[var(--as-muted-fg)]">
        {t("marketStats.filters.skillMode")}
        <SegmentedTabs
          items={[
            { value: "all", label: t("marketStats.filters.skillModeAll") },
            { value: "any", label: t("marketStats.filters.skillModeAny") },
          ]}
          value={segments.skill_mode || "all"}
          onValueChange={(value) => patchSegments({ skill_mode: value as "all" | "any" })}
          ariaLabel={t("marketStats.filters.skillMode")}
        />
      </div>
      {isAdmin ? (
        <label className="flex min-h-[44px] items-center gap-2 text-xs text-[var(--as-muted-fg)]">
          <input
            type="checkbox"
            checked={segments.hidden_include}
            onChange={(event) => patchSegments({ hidden_include: event.target.checked })}
            data-testid="market-stats-filter-hidden_include"
          />
          {t("marketStats.filters.hiddenInclude")}
        </label>
      ) : null}
    </div>
  );

  return (
    <div className="space-y-2" data-testid="market-stats-filter-bar">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 overflow-x-auto">
          <SegmentedTabs
            className="min-w-max whitespace-nowrap"
            items={[...MARKET_WINDOWS, "custom"].map((value) => ({
              value,
              label: t(`marketStats.window.${value}`),
            }))}
            value={view.window}
            onValueChange={(next) => {
              if (next === "custom") {
                const today = new Date();
                const start = new Date(today);
                start.setDate(start.getDate() - 29);
                onPatch({
                  window: "custom",
                  from: start.toISOString().slice(0, 10),
                  to: today.toISOString().slice(0, 10),
                });
              } else {
                onPatch({ window: next as MarketStatsView["window"] });
              }
            }}
            ariaLabel={t("marketStats.window.title")}
          />
        </div>
        {view.window === "custom" ? (
          <span className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              className={dateInputClass()}
              value={view.from}
              max={view.to || undefined}
              onChange={(event) => onPatch({ from: event.target.value })}
              aria-label={t("marketStats.window.fromLabel")}
              data-testid="market-stats-from"
            />
            <span aria-hidden className="text-xs text-[var(--as-muted-fg)]">→</span>
            <input
              type="date"
              className={dateInputClass()}
              value={view.to}
              min={view.from || undefined}
              onChange={(event) => onPatch({ to: event.target.value })}
              aria-label={t("marketStats.window.toLabel")}
              data-testid="market-stats-to"
            />
          </span>
        ) : null}
        <div
          className="flex items-center gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
          role="group"
          aria-label={t("marketStats.basis.title")}
        >
          {(["open", "all"] as const).map((basis) => (
            <button
              key={basis}
              type="button"
              aria-pressed={view.basis === basis}
              onClick={() => onPatch({ basis })}
              className={`min-h-[44px] rounded-[calc(var(--as-radius,0.75rem)-0.2rem)] px-3 text-xs ${
                view.basis === basis
                  ? "bg-[var(--as-surface-raised)] font-medium text-[var(--as-fg)]"
                  : "text-[var(--as-muted-fg)]"
              }`}
              data-testid={`market-stats-basis-${basis}`}
              title={t("marketStats.basisHint")}
            >
              {t(`marketStats.basis.${basis}`)}
            </button>
          ))}
        </div>
        <div
          className="flex items-center gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
          role="group"
          aria-label={t("marketStats.compare.groupAria")}
          data-testid="market-stats-compare"
        >
          {(["off", "previous", "custom"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={view.compare === mode}
              onClick={() => onPatch({ compare: mode, compare_from: "", compare_to: "" })}
              className={`min-h-[44px] rounded-[calc(var(--as-radius,0.75rem)-0.2rem)] px-3 text-xs ${
                view.compare === mode
                  ? "bg-[var(--as-surface-raised)] font-medium text-[var(--as-fg)]"
                  : "text-[var(--as-muted-fg)]"
              }`}
              data-testid={`market-stats-compare-${mode}`}
            >
              {t(`marketStats.compare.${mode}`)}
            </button>
          ))}
        </div>
        {view.compare === "custom" ? (
          <span className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              className={dateInputClass()}
              value={view.compare_from}
              max={view.compare_to || undefined}
              onChange={(event) =>
                onPatch({ compare: "custom", compare_from: event.target.value })
              }
              aria-label={t("marketStats.compare.fromLabel")}
              data-testid="market-stats-compare-from"
            />
            <span aria-hidden className="text-xs text-[var(--as-muted-fg)]">→</span>
            <input
              type="date"
              className={dateInputClass()}
              value={view.compare_to}
              min={view.compare_from || undefined}
              onChange={(event) => onPatch({ compare: "custom", compare_to: event.target.value })}
              aria-label={t("marketStats.compare.toLabel")}
              data-testid="market-stats-compare-to"
            />
          </span>
        ) : null}
        {view.compare === "custom" && !compareRange(view) ? (
          <button
            type="button"
            className="inline-flex min-h-[44px] items-center gap-1 rounded-full border border-[var(--as-border)] px-2.5 text-xs text-[var(--as-muted-fg)]"
            onClick={() => {
              const span = spanDays(view);
              if (span === null) return;
              const today = new Date().toISOString().slice(0, 10);
              onPatch({
                compare: "custom",
                compare_from: addIsoDays(today, -(2 * span - 1)),
              });
            }}
            data-testid="market-stats-compare-seed"
          >
            <CalendarRange className="size-3" aria-hidden />
            {t("marketStats.compare.pickDates")}
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {band === "wide" ? null : (
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className={chipClass()}
            data-testid="market-stats-filters-button"
            aria-expanded={sheetOpen}
          >
            <SlidersHorizontal className="size-3" aria-hidden />
            {t("marketStats.filters.title")}
            {chips.length > 0 ? (
              <span
                className="rounded-full bg-[var(--as-accent)] px-1.5 text-[10px] font-semibold text-[var(--as-accent-fg)]"
                data-testid="market-stats-filters-count"
              >
                {chips.length}
              </span>
            ) : null}
          </button>
        )}
        {chips.map((chip) => (
          <span
            key={`${chip.axis}-${chip.value}`}
            className={chipClass()}
            data-testid={`market-stats-chip-${chip.axis}`}
          >
            <span className="text-[var(--as-muted-fg)]">
              {t(`marketStats.filters.${chip.axis}`, { defaultValue: chip.axis })}
              :
            </span>
            {chip.value}
            <button
              type="button"
              onClick={() => removeChip(chip.axis, chip.value)}
              className="rounded-full p-1 text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              aria-label={t("marketStats.filters.removeChip", { value: chip.value })}
              data-testid={`market-stats-chip-remove-${chip.axis}`}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
        {chips.length > 0 ? (
          <button
            type="button"
            className={chipClass()}
            onClick={() => onPatch({ segments: { ...segments, ...emptySegments() } })}
            data-testid="market-stats-clear-filters"
          >
            {t("marketStats.filters.clearAll")}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className={chipClass()}
          data-testid="market-stats-refresh"
          title={t("marketStats.filters.refresh")}
        >
          <RotateCw className={`size-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          {t("marketStats.filters.refresh")}
        </button>
      </div>

      {band === "wide" ? (
        <div className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3">
          {fields}
        </div>
      ) : null}

      <PanelModal
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title={t("marketStats.filters.title")}
        closeLabel={t("marketStats.filters.close")}
        size="md"
        footer={
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              className="min-h-[44px] rounded-lg border border-[var(--as-border)] px-3 text-sm text-[var(--as-fg)]"
              onClick={() => onPatch({ segments: { ...segments, ...emptySegments() } })}
              data-testid="market-stats-sheet-clear"
            >
              {t("marketStats.filters.clearAll")}
            </button>
            <button
              type="button"
              className="min-h-[44px] rounded-lg bg-[var(--as-accent)] px-4 text-sm font-medium text-[var(--as-accent-fg)]"
              onClick={() => setSheetOpen(false)}
              data-testid="market-stats-sheet-apply"
            >
              {t("marketStats.filters.apply")}
            </button>
          </div>
        }
      >
        {fields}
      </PanelModal>
    </div>
  );
}

function emptySegments(): Partial<MarketSegments> {
  return {
    source: [],
    org: [],
    mapped_family: [],
    seniority: [],
    remote_policy: [],
    employment_type: [],
    contract: [],
    education_min: "",
    city: "",
    country: "",
    skills: "",
    skill_mode: "",
    salary_min: "",
    q: "",
    hidden_include: false,
  };
}
