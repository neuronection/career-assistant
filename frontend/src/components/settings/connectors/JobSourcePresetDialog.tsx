import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Plus, Sparkles } from "lucide-react";
import { countryDisplayName, findCountry } from "@neuronection/assistant-ui/countries";

import {
  Badge,
  Button,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  SearchInput,
  SegmentedTabs,
} from "@/components/ui";
import { PresetLogo } from "@/components/settings/connectors/PresetLogo";
import {
  JOB_SOURCE_PRESETS,
  WORLDWIDE_KEY,
  preselectCountries,
  presetCountryLenses,
  presetGroups,
  type JobSourcePreset,
  type JobSourcePresetCategory,
} from "@/config/jobSourcePresets";

/**
 * Preset gallery for adding job sources (plan 176/178): curated connector
 * instances as selectable cards (logo, company, provider, country) — the
 * LLM-provider tile pattern. Selection is multi (aria-pressed toggles);
 * the footer bulk-adds everything selected; "Custom source" falls back to
 * the generic connector wizard. Presets whose source key already exists
 * render added and inert.
 */

type Filter = "all" | JobSourcePresetCategory;

export interface PresetAddOutcome {
  preset: JobSourcePreset;
  ok: boolean;
  detail?: string;
}

export function JobSourcePresetDialog({
  open,
  onOpenChange,
  onAddPresets,
  onCustom,
  existingKeys = [],
  busy = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAddPresets: (
    presets: JobSourcePreset[],
  ) => Promise<PresetAddOutcome[]> | Promise<never[]>;
  onCustom: () => void;
  existingKeys?: string[];
  busy?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const language = (i18n as { language?: string } | undefined)?.language ?? "en";
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [countries, setCountries] = useState<Set<string> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [report, setReport] = useState<PresetAddOutcome[] | null>(null);

  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setReport(null);
      const preselect = preselectCountries(language);
      setCountries(preselect.length > 0 ? new Set(preselect) : null);
    }
  }, [open, language]);

  const countryName = (code?: string) =>
    code ? countryDisplayName(code, language) : t("toolsSettings.connectors.presets.worldwide");

  const lenses = useMemo(
    () => presetCountryLenses(JOB_SOURCE_PRESETS, (key) => countryName(key === WORLDWIDE_KEY ? undefined : key)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [language, t],
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return JOB_SOURCE_PRESETS.filter((preset) => {
      if (filter !== "all" && preset.category !== filter) return false;
      if (countries && countries.size > 0 && !countries.has(preset.country ?? WORLDWIDE_KEY)) {
        return false;
      }
      if (!needle) return true;
      const haystack = [preset.name, preset.provider, countryName(preset.country)]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, filter, countries, language, t]);

  const toggleCountry = (key: string) => {
    setCountries((current) => {
      const base = current ?? new Set<string>();
      const next = new Set(base);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next.size > 0 ? next : null;
    });
  };

  const groups = useMemo(() => presetGroups(visible), [visible]);
  const selectedPresets = JOB_SOURCE_PRESETS.filter((preset) => selected.has(preset.slug));

  const toggle = (slug: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalContent
        size="lg"
        className="max-w-5xl"
        data-testid="job-source-presets"
        aria-describedby="job-source-presets-hint"
      >
        <ModalHeader>
          <ModalTitle>
            <span className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
              {t("toolsSettings.connectors.presets.title")}
            </span>
          </ModalTitle>
        </ModalHeader>

        <p id="job-source-presets-hint" className="text-sm text-[var(--as-muted-fg)]">
          {t("toolsSettings.connectors.presets.subtitle")}
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="min-w-0 flex-1 basis-56" data-testid="preset-search">
            <SearchInput
              value={query}
              onChange={setQuery}
              placeholder={t("toolsSettings.connectors.presets.searchPlaceholder")}
              ariaLabel={t("toolsSettings.connectors.presets.searchPlaceholder")}
              clearLabel={t("common.clear")}
            />
          </div>
          <SegmentedTabs
            ariaLabel={t("toolsSettings.connectors.presets.filterAria")}
            items={[
              { value: "all", label: t("toolsSettings.connectors.presets.filterAll") },
              { value: "ats", label: t("toolsSettings.connectors.presets.filterAts") },
              { value: "remote", label: t("toolsSettings.connectors.presets.filterRemote") },
            ]}
            value={filter}
            onValueChange={(next) => setFilter(next as Filter)}
          />
        </div>

        <div
          className="mt-2 flex flex-wrap items-center gap-1.5"
          role="group"
          aria-label={t("toolsSettings.connectors.presets.countryFilterAria")}
          data-testid="preset-country-filter"
        >
          <button
            type="button"
            aria-pressed={!countries || countries.size === 0}
            onClick={() => setCountries(null)}
            data-testid="preset-country-all"
            className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
              !countries || countries.size === 0
                ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))] font-medium text-[var(--as-accent)]"
                : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-muted-fg)] hover:border-[var(--as-accent)]"
            }`}
          >
            {t("toolsSettings.connectors.presets.countryAll")}
          </button>
          {lenses.map((lens) => {
            const active = countries?.has(lens.key) ?? false;
            const country = lens.key === WORLDWIDE_KEY ? null : findCountry(lens.key);
            return (
              <button
                key={lens.key}
                type="button"
                aria-pressed={active}
                onClick={() => toggleCountry(lens.key)}
                data-testid={`preset-country-${lens.key}`}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                  active
                    ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))] font-medium text-[var(--as-accent)]"
                    : "border-[var(--as-border)] bg-[var(--as-surface)] text-[var(--as-fg)] hover:border-[var(--as-accent)]"
                }`}
              >
                {country ? `${country.flag} ` : "🌍 "}
                {lens.label}
                <span className={active ? "ml-1 opacity-80" : "ml-1 text-[var(--as-muted-fg)]"}>
                  {lens.count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="mt-4 max-h-[60vh] space-y-5 overflow-y-auto pr-1">
          {report ? (
            <div
              className="space-y-1 rounded-[var(--as-radius-md)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid="preset-report"
            >
              {report.map(({ preset, ok, detail }) => (
                <p key={preset.slug} className="flex items-center gap-2 text-xs">
                  {ok ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-[var(--as-success)]" aria-hidden />
                  ) : (
                    <span
                      className="text-[var(--as-danger)]"
                      aria-hidden
                      data-testid={`preset-report-failed-${preset.slug}`}
                    >
                      ✕
                    </span>
                  )}
                  <span className="font-medium text-[var(--as-fg)]">{preset.name}</span>
                  {detail ? (
                    <span className="truncate text-[var(--as-muted-fg)]">{detail}</span>
                  ) : null}
                </p>
              ))}
            </div>
          ) : null}
          {groups.length === 0 ? (
            <p className="py-6 text-center text-sm text-[var(--as-muted-fg)]">
              {t("toolsSettings.connectors.presets.noMatches")}
            </p>
          ) : (
            groups.map((group) => (
              <section
                key={group.provider}
                aria-label={group.provider}
                data-testid={`preset-group-${group.provider}`}
                className="space-y-2"
              >
                <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {group.provider}
                </p>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {group.presets.map((preset) => {
                    const added = existingKeys.includes(preset.slug);
                    const isSelected = selected.has(preset.slug);
                    const country = findCountry(preset.country);
                    return (
                      <button
                        key={preset.slug}
                        type="button"
                        disabled={added || busy}
                        aria-pressed={isSelected}
                        onClick={() => toggle(preset.slug)}
                        data-testid={`preset-${preset.slug}`}
                        className={`flex items-center gap-3 rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                          added
                            ? "cursor-default border-[var(--as-border)] bg-[var(--as-muted)] opacity-70"
                            : isSelected
                              ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,var(--as-surface))]"
                              : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)] hover:bg-[var(--as-surface-raised)]"
                        }`}
                      >
                        <PresetLogo preset={preset} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
                            {preset.name}
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
                            {preset.provider} · {country ? `${country.flag} ${countryName(preset.country)}` : countryName()}
                          </span>
                          <span className="mt-0.5 block truncate text-[11px] text-[var(--as-muted-fg)]">
                            {typeof preset.openings === "number"
                              ? t("toolsSettings.connectors.presets.openings", {
                                  count: preset.openings,
                                })
                              : null}
                            {preset.verifiedAt
                              ? ` · ${t("toolsSettings.connectors.presets.verified", {
                                  date: new Date(preset.verifiedAt).toLocaleDateString(language, {
                                    month: "short",
                                    year: "numeric",
                                  }),
                                })}`
                              : null}
                          </span>
                        </span>
                        {added ? (
                          <Badge variant="secondary" data-testid={`preset-added-${preset.slug}`}>
                            {t("toolsSettings.connectors.presets.addedBadge")}
                          </Badge>
                        ) : isSelected ? (
                          <span
                            className="grid size-6 shrink-0 place-items-center rounded-full bg-[var(--as-accent)] text-white"
                            aria-hidden
                          >
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <Plus
                            className="h-4 w-4 shrink-0 text-[var(--as-muted-fg)]"
                            aria-hidden
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </section>
            ))
          )}
        </div>

        <ModalFooter className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--as-border)] pt-3">
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("toolsSettings.connectors.presets.footerHint")}
          </p>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={onCustom} data-testid="preset-custom">
              <Plus className="h-3.5 w-3.5" /> {t("toolsSettings.connectors.presets.custom")}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                if (adding) return;
                setAdding(true);
                void (async () => {
                  const outcomes = await onAddPresets(selectedPresets);
                  setAdding(false);
                  setReport(outcomes);
                  setSelected(
                    new Set(outcomes.filter((o) => !o.ok).map((o) => o.preset.slug)),
                  );
                })();
              }}
              disabled={selectedPresets.length === 0 || busy || adding}
              data-testid="presets-add"
            >
              {t("toolsSettings.connectors.presets.addSelected", {
                count: selectedPresets.length,
              })}
            </Button>
          </div>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
