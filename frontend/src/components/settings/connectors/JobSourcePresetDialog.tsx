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
import { OrgAvatar } from "@/components/company/OrgAvatar";
import {
  JOB_SOURCE_PRESETS,
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

function PresetLogo({ preset }: { preset: JobSourcePreset }) {
  const [failed, setFailed] = useState(false);
  if (preset.logo && !failed) {
    return (
      <img
        src={preset.logo}
        alt=""
        loading="lazy"
        className="size-10 shrink-0 rounded-lg object-contain"
        onError={() => setFailed(true)}
      />
    );
  }
  return <OrgAvatar name={preset.name} size={40} className="rounded-lg" />;
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
  onAddPresets: (presets: JobSourcePreset[]) => void;
  onCustom: () => void;
  existingKeys?: string[];
  busy?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const language = (i18n as { language?: string } | undefined)?.language ?? "en";
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (open) setSelected(new Set());
  }, [open]);

  const countryName = (code?: string) =>
    code ? countryDisplayName(code, language) : t("toolsSettings.connectors.presets.worldwide");

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return JOB_SOURCE_PRESETS.filter((preset) => {
      if (filter !== "all" && preset.category !== filter) return false;
      if (!needle) return true;
      const haystack = [preset.name, preset.provider, countryName(preset.country)]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, filter, language, t]);

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

        <div className="mt-4 max-h-[60vh] space-y-5 overflow-y-auto pr-1">
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
              onClick={() => onAddPresets(selectedPresets)}
              disabled={selectedPresets.length === 0 || busy}
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
