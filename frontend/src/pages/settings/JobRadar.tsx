import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Globe, Play, Plus, Radar, SlidersHorizontal, Trash2 } from "lucide-react";
import { Badge, ChipInput, Combobox, EmptyState, Input, SwitchRow } from "@neuronection/assistant-ui";
import { COUNTRIES } from "@neuronection/assistant-ui/countries";
import {
  fetchRadar,
  previewRadar,
  updateRadar,
  type RadarInput,
  type RadarLocationInput,
} from "@/api/radar";
import { fetchUserSources } from "@/api/sources";
import {
  fetchMySchedules,
  runMyScheduleNow,
  setMyScheduleEnabled,
} from "@/api/scheduler";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";
import { SelectField, ChipTogglesRow } from "@/features/cv/components/cv/formPrimitives";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { SaveStateIndicator } from "@/components/settings/saveState";
import { useSettingsDraft } from "@/components/settings/useSettingsDraft";
import type { ExploreResponse } from "@/types/wire";

const SENIORITY_BANDS = ["intern", "junior", "mid", "senior", "lead", "principal"] as const;
const CADENCES = ["off", "instant", "daily", "weekly"] as const;
const MAX_LOCATIONS = 12;
const MAX_KEYWORDS = 24;
const CURRENCIES = ["USD", "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "AUD", "CAD"];

interface RadarDraft {
  keywords: string[];
  locations: RadarLocationInput[];
  seniority: string[];
  onsite_policy: "" | "onsite" | "hybrid" | "remote";
  salary_min_annual: string;
  salary_currency: string;
  source_keys: string[];
  cadence: (typeof CADENCES)[number];
  enabled: boolean;
}

interface UserSourceRow {
  key: string;
  connector_key: string;
  open_postings: number;
}

interface RadarScheduleFacts {
  id: string;
  enabled: boolean;
  next_run_at: string | null | undefined;
  last_run_at: string | null | undefined;
  last_status: string | null | undefined;
}

const EMPTY_DRAFT: RadarDraft = {
  keywords: [],
  locations: [],
  seniority: [],
  onsite_policy: "",
  salary_min_annual: "",
  salary_currency: "",
  source_keys: [],
  cadence: "off",
  enabled: false,
};

function toDraft(radar: {
  keywords?: string[] | null;
  locations?: RadarLocationInput[] | null;
  seniority?: string[] | null;
  onsite_policy?: string | null;
  salary_min_annual?: number | string | null;
  salary_currency?: string | null;
  source_keys?: string[] | null;
  cadence?: string | null;
  enabled?: boolean | null;
}): RadarDraft {
  return {
    keywords: radar.keywords ?? [],
    locations: radar.locations ?? [],
    seniority: radar.seniority ?? [],
    onsite_policy: (radar.onsite_policy ?? "") as RadarDraft["onsite_policy"],
    salary_min_annual:
      radar.salary_min_annual != null ? String(radar.salary_min_annual) : "",
    salary_currency: radar.salary_currency ?? "",
    source_keys: radar.source_keys ?? [],
    cadence: (radar.cadence ?? "off") as RadarDraft["cadence"],
    enabled: radar.enabled ?? false,
  };
}

function toPayload(draft: RadarDraft): RadarInput {
  return {
    keywords: draft.keywords,
    locations: draft.locations.filter((row) => row.city || row.country || row.remote),
    seniority: draft.seniority,
    onsite_policy: draft.onsite_policy || null,
    salary_min_annual: draft.salary_min_annual ? Number(draft.salary_min_annual) : null,
    salary_currency: draft.salary_min_annual
      ? draft.salary_currency.toUpperCase()
      : null,
    source_keys: draft.source_keys,
    cadence: draft.cadence,
    enabled: draft.enabled,
  };
}

/** Settings → Job radar (plan 148 phase 3): a status hero that composes
 * the scan schedule (last/next scan, pause, scan-now over the user
 * schedule endpoints), criteria cards (keyword chips, country-combobox
 * locations, seniority/salary filters), the connector source picker and
 * a live preview. One replace-all payload: explicit Save with a dirty
 * guard; the preview runs against the current draft without saving. */
export function JobRadarSettings() {
  const { t } = useTranslation();
  const [loadError, setLoadError] = useState("");
  const [preview, setPreview] = useState<ExploreResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [schedule, setSchedule] = useState<RadarScheduleFacts | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [sources, setSources] = useState<UserSourceRow[]>([]);
  const [updated_at, setUpdatedAt] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<RadarDraft | null>(null);

  const loadSchedule = useCallback(async () => {
    try {
      const rows = await fetchMySchedules();
      const radar = rows.find((row) => row.kind === "user_radar_digest");
      setSchedule(
        radar
          ? {
              id: radar.id,
              enabled: radar.enabled,
              next_run_at: radar.next_run_at,
              last_run_at: radar.last_run_at,
              last_status: radar.last_status,
            }
          : null
      );
    } catch {
      setSchedule(null);
    }
  }, []);

  const draft = useSettingsDraft<RadarDraft, RadarInput>({
    initial: loaded ?? EMPTY_DRAFT,
    buildPayload: toPayload,
    onSave: async (payload) => {
      const saved = await updateRadar(payload);
      setUpdatedAt(saved.updated_at ?? null);
      setLoaded(toDraft(saved));
      await loadSchedule();
    },
  });

  useEffect(() => {
    void fetchRadar()
      .then((radar) => {
        setLoaded(toDraft(radar));
        setUpdatedAt(radar.updated_at ?? null);
        setLoadError("");
      })
      .catch((err) => setLoadError(apiDetail(err) || t("jobRadar.loadError")));
    void loadSchedule();
    void fetchUserSources()
      .then(setSources)
      .catch(() => setSources([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!draft.dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [draft.dirty]);

  const setDraft = draft.setDraft;
  const patch = useCallback(
    (part: Partial<RadarDraft>) => setDraft((prev) => ({ ...prev, ...part })),
    [setDraft]
  );

  const runPreview = async () => {
    setPreviewing(true);
    setPreviewError("");
    try {
      setPreview(await previewRadar(toPayload(draft.draft)));
    } catch (err) {
      setPreviewError(apiDetail(err));
    } finally {
      setPreviewing(false);
    }
  };

  const scanNow = async () => {
    if (!schedule) return;
    setScheduleBusy(true);
    try {
      await runMyScheduleNow(schedule.id);
      await loadSchedule();
    } catch (err) {
      setLoadError(apiDetail(err));
    } finally {
      setScheduleBusy(false);
    }
  };

  const pauseScan = async (paused: boolean) => {
    if (!schedule) return;
    setScheduleBusy(true);
    try {
      const updated = await setMyScheduleEnabled(schedule.id, !paused);
      setSchedule({ ...schedule, enabled: updated.enabled });
    } catch (err) {
      setLoadError(apiDetail(err));
    } finally {
      setScheduleBusy(false);
    }
  };

  const cadenceActive = draft.draft.enabled && draft.draft.cadence !== "off";
  const radarOn = draft.draft.enabled;

  const statusChips = (
    <>
      <Badge variant={radarOn ? "success" : "outline"} data-testid="radar-status-chip">
        {radarOn
          ? t("jobRadar.statusOn", { cadence: t(`jobRadar.cadenceOptions.${draft.draft.cadence}`) })
          : t("jobRadar.statusOff")}
      </Badge>
      {schedule?.last_run_at ? (
        <Badge variant="secondary" data-testid="radar-last-scan-chip">
          {t("jobRadar.lastScan", {
            date: new Date(schedule.last_run_at).toLocaleString(),
          })}
        </Badge>
      ) : null}
    </>
  );

  const sections = useMemo(
    () => [
      { id: "s-status", label: t("jobRadar.statusTitle") },
      { id: "s-criteria", label: t("jobRadar.criteriaTitle") },
      { id: "s-filters", label: t("jobRadar.filtersHeading") },
      ...(sources.length > 0
        ? [{ id: "s-sources", label: t("jobRadar.sourcesTitle") }]
        : []),
      { id: "s-preview", label: t("jobRadar.previewTitle", { count: preview?.total ?? 0 }) },
    ],
    [t, sources.length, preview?.total]
  );

  return (
    <SettingsPage
      icon={Radar}
      title={t("settingsNav.radar.label")}
      description={t("settingsNav.radar.description")}
      statusChips={statusChips}
      sections={sections}
    >
      {loadError ? (
        <p className="mb-3 text-sm text-[var(--as-danger)]" role="alert">
          {loadError}
        </p>
      ) : null}

      <section id="s-status" className="scroll-mt-4">
        <SettingsSectionCard
          name="status"
          title={t("jobRadar.statusTitle")}
          description={t("jobRadar.enabledHint")}
          icon={Radar}
          badges={
            updated_at ? (
              <Badge variant="outline" data-testid="radar-updated">
                {t("jobRadar.savedAt", { date: new Date(updated_at).toLocaleDateString() })}
              </Badge>
            ) : null
          }
        >
          <div className="space-y-3">
            <SwitchRow
              label={t("jobRadar.enabled")}
              checked={draft.draft.enabled}
              onCheckedChange={(enabled) => patch({ enabled })}
              data-testid="radar-enabled"
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("jobRadar.cadenceLabel")}
              </span>
              <div
                className="flex flex-wrap gap-1"
                role="radiogroup"
                aria-label={t("jobRadar.cadenceLabel")}
              >
                {CADENCES.map((cadence) => (
                  <button
                    key={cadence}
                    type="button"
                    role="radio"
                    aria-checked={draft.draft.cadence === cadence}
                    data-testid={`radar-cadence-${cadence}`}
                    onClick={() => patch({ cadence })}
                    className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--as-focus-ring)] ${
                      draft.draft.cadence === cadence
                        ? "border-[var(--as-primary)] bg-[color-mix(in_srgb,var(--as-primary)_10%,transparent)] text-[var(--as-primary)]"
                        : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)]"
                    }`}
                  >
                    {t(`jobRadar.cadenceOptions.${cadence}`)}
                  </button>
                ))}
              </div>
            </div>
            {schedule ? (
              <div
                className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-3 py-2 text-xs text-[var(--as-muted-fg)]"
                data-testid="radar-schedule"
              >
                <span>
                  {t("jobRadar.lastScanShort", {
                    date: schedule.last_run_at
                      ? new Date(schedule.last_run_at).toLocaleString()
                      : "—",
                  })}
                </span>
                {schedule.last_status ? (
                  <Badge
                    variant={schedule.last_status === "ok" ? "success" : "warning"}
                    data-testid="radar-scan-status"
                  >
                    {t(`jobRadar.scanStatus.${schedule.last_status}`, {
                      defaultValue: schedule.last_status,
                    })}
                  </Badge>
                ) : null}
                <span>
                  {t("jobRadar.nextScanShort", {
                    date: schedule.next_run_at
                      ? new Date(schedule.next_run_at).toLocaleString()
                      : "—",
                  })}
                </span>
                <span className="ml-auto flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!cadenceActive || scheduleBusy}
                    onClick={() => void scanNow()}
                    data-testid="radar-scan-now"
                  >
                    <Play className="h-3.5 w-3.5" /> {t("jobRadar.scanNow")}
                  </Button>
                  <SwitchRow
                    label={t("jobRadar.scanPaused")}
                    checked={!schedule.enabled}
                    disabled={!cadenceActive || scheduleBusy}
                    hideLabel
                    onCheckedChange={(paused) => void pauseScan(paused)}
                    className="w-auto border-none bg-transparent px-1 py-0 hover:bg-transparent"
                    data-testid="radar-scan-paused"
                  />
                </span>
              </div>
            ) : (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("jobRadar.noScheduleYet")}
              </p>
            )}
          </div>
        </SettingsSectionCard>
      </section>

      <section id="s-criteria" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="criteria"
          title={t("jobRadar.criteriaTitle")}
          description={t("jobRadar.criteriaBody")}
          icon={Globe}
        >
          <div className="space-y-4">
            <div>
              <ChipInput
                value={draft.draft.keywords}
                onChange={(keywords) => patch({ keywords })}
                placeholder={t("jobRadar.keywordPlaceholder")}
                inputLabel={t("jobRadar.keywordsHeading")}
                removeLabel={t("jobRadar.removeKeyword")}
                addLabel={t("jobRadar.addKeyword")}
                hint={t("jobRadar.keywordsHint", { max: MAX_KEYWORDS })}
                data-testid="radar-keywords"
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[var(--as-muted-fg)]">
                  {t("jobRadar.locationsHeading")}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={draft.draft.locations.length >= MAX_LOCATIONS}
                  onClick={() =>
                    patch({
                      locations: [
                        ...draft.draft.locations,
                        { city: "", country: "", remote: false },
                      ],
                    })
                  }
                  data-testid="radar-add-location"
                >
                  <Plus className="h-3.5 w-3.5" /> {t("jobRadar.addLocation")}
                </Button>
              </div>
              {draft.draft.locations.length === 0 ? (
                <EmptyState
                  icon={Radar}
                  compact
                  title={t("jobRadar.noLocations")}
                  description={t("jobRadar.locationsHint")}
                />
              ) : null}
              {draft.draft.locations.map((row, index) => (
                <div
                  key={index}
                  className="flex flex-wrap items-center gap-2"
                  data-testid={`radar-location-${index}`}
                >
                  <div className="min-w-40 flex-1">
                    <Combobox
                      options={COUNTRY_OPTIONS}
                      value={row.country ?? ""}
                      onChange={(country) =>
                        patch({
                          locations: draft.draft.locations.map((r, i) =>
                            i === index ? { ...r, country } : r
                          ),
                        })
                      }
                      placeholder={t("jobRadar.countryPlaceholder")}
                      searchLabel={t("jobRadar.countryPlaceholder")}
                      clearable
                      clearLabel={t("common.remove")}
                      label={t("jobRadar.countryPlaceholder")}
                      hideLabel
                      data-testid={`radar-country-${index}`}
                    />
                  </div>
                  <Input
                    value={row.city ?? ""}
                    placeholder={t("jobRadar.cityPlaceholder")}
                    aria-label={t("jobRadar.cityPlaceholder")}
                    onChange={(event) =>
                      patch({
                        locations: draft.draft.locations.map((r, i) =>
                          i === index ? { ...r, city: event.target.value } : r
                        ),
                      })
                    }
                    className="w-40 flex-1"
                    data-testid={`radar-city-${index}`}
                  />
                  <label className="flex shrink-0 items-center gap-1.5 text-xs text-[var(--as-muted-fg)]">
                    <input
                      type="checkbox"
                      checked={row.remote}
                      aria-label={t("jobRadar.remote")}
                      onChange={(event) =>
                        patch({
                          locations: draft.draft.locations.map((r, i) =>
                            i === index ? { ...r, remote: event.target.checked } : r
                          ),
                        })
                      }
                    />
                    {t("jobRadar.remote")}
                  </label>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("jobRadar.removeLocation")}
                    onClick={() =>
                      patch({
                        locations: draft.draft.locations.filter((_, i) => i !== index),
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </SettingsSectionCard>
      </section>

      <section id="s-filters" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="filters"
          title={t("jobRadar.filtersHeading")}
          icon={SlidersHorizontal}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label={t("jobRadar.onsitePolicy")}
              value={draft.draft.onsite_policy}
              onChange={(onsite_policy) =>
                patch({ onsite_policy: onsite_policy as RadarDraft["onsite_policy"] })
              }
              options={[
                { value: "", label: t("jobRadar.any") },
                ...(["onsite", "hybrid", "remote"] as const).map((policy) => ({
                  value: policy,
                  label: t(`jobRadar.onsite.${policy}`),
                })),
              ]}
              testId="radar-onsite"
            />
            <div>
              <span className="mb-1 block text-xs font-medium text-[var(--as-muted-fg)]">
                {t("jobRadar.seniority")}
              </span>
              <ChipTogglesRow
                label={t("jobRadar.seniority")}
                values={draft.draft.seniority}
                options={SENIORITY_BANDS.map((band) => ({ value: band, label: band }))}
                onChange={(seniority) => patch({ seniority })}
              />
            </div>
            <div>
              <span className="mb-1 block text-xs font-medium text-[var(--as-muted-fg)]">
                {t("jobRadar.salaryMinAnnual")}
              </span>
              <div className="flex gap-2">
                <Input
                  value={draft.draft.salary_min_annual}
                  inputMode="numeric"
                  aria-label={t("jobRadar.salaryMinAnnual")}
                  onChange={(event) =>
                    patch({
                      salary_min_annual: event.target.value.replace(/[^0-9]/g, ""),
                    })
                  }
                  className="flex-1"
                  data-testid="radar-salary"
                />
                <div className="w-28">
                  <Combobox
                    options={CURRENCY_OPTIONS}
                    value={draft.draft.salary_currency}
                    onChange={(salary_currency) => patch({ salary_currency })}
                    placeholder={t("jobRadar.currencyPlaceholder")}
                    searchLabel={t("jobRadar.currency")}
                    allowCreate
                    createLabel={(term) => term.toUpperCase().slice(0, 3)}
                    label={t("jobRadar.currency")}
                    hideLabel
                    data-testid="radar-currency"
                  />
                </div>
              </div>
              <span className="mt-1 block text-xs text-[var(--as-muted-fg)]">
                {t("jobRadar.salaryAnnualHint")}
              </span>
            </div>
          </div>
        </SettingsSectionCard>
      </section>

      {sources.length > 0 ? (
        <section id="s-sources" className="mt-4 scroll-mt-4">
          <SettingsSectionCard
            name="sources"
            title={t("jobRadar.sourcesTitle")}
            description={t("jobRadar.sourcesHint")}
          >
            <ChipTogglesRow
              label={t("jobRadar.sourcesTitle")}
              values={draft.draft.source_keys}
              options={sources.map((source) => ({
                value: source.key,
                label: `${source.key} (${source.open_postings})`,
              }))}
              onChange={(source_keys) => patch({ source_keys })}
            />
            <p className="mt-2 text-xs text-[var(--as-muted-fg)]">
              {t("jobRadar.sourcesHintAll")}
            </p>
          </SettingsSectionCard>
        </section>
      ) : null}

      <section id="s-preview" className="mt-4 scroll-mt-4">
        <SettingsSectionCard
          name="preview"
          title={t("jobRadar.previewTitle", { count: preview?.total ?? 0 })}
          description={t("jobRadar.previewHint")}
        >
          {previewError ? (
            <p className="mb-2 text-xs text-[var(--as-danger)]">{previewError}</p>
          ) : null}
          {preview ? (
            <div data-testid="radar-preview">
              {(preview.items ?? []).length === 0 ? (
                <EmptyState
                  icon={Radar}
                  compact
                  title={t("jobRadar.previewEmpty")}
                  description={t("jobRadar.previewEmptyHint")}
                />
              ) : (
                <ul className="divide-y divide-[var(--as-border)]">
                  {(preview.items ?? []).map((item) => (
                    <li key={item.id} className="py-1.5 text-sm text-[var(--as-fg)]">
                      {item.title}
                      <span className="text-xs text-[var(--as-muted-fg)]">
                        {item.org ? ` · ${item.org}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <Link
                to="/postings/search"
                className="mt-2 inline-block text-sm text-[var(--as-primary)] underline decoration-transparent transition-colors hover:decoration-current"
              >
                {t("jobRadar.openExplore")}
              </Link>
            </div>
          ) : (
            <p className="text-xs text-[var(--as-muted-fg)]">{t("jobRadar.previewIdle")}</p>
          )}
        </SettingsSectionCard>
      </section>

      <div
        className="sticky bottom-0 mt-4 flex flex-wrap items-center gap-3 border-t border-[var(--as-border)] bg-[var(--surface,var(--as-surface))] py-3"
        data-testid="radar-actions"
      >
        <Button onClick={() => void draft.save()} disabled={!draft.dirty} data-testid="radar-save">
          {t("jobRadar.save")}
        </Button>
        <Button
          variant="outline"
          onClick={() => void runPreview()}
          disabled={previewing}
          data-testid="radar-test"
        >
          {previewing ? t("jobRadar.testing") : t("jobRadar.test")}
        </Button>
        <SaveStateIndicator state={draft.state} error={draft.error} onRetry={() => void draft.save()} />
        {draft.dirty ? (
          <span className="text-xs text-[var(--as-muted-fg)]">
            {t("jobRadar.unsavedNote")}
          </span>
        ) : null}
      </div>
    </SettingsPage>
  );
}

const COUNTRY_OPTIONS = COUNTRIES.map((country) => ({
  value: country.name,
  label: `${country.flag} ${country.name}`,
}));

const CURRENCY_OPTIONS = CURRENCIES.map((code) => ({ value: code, label: code }));
