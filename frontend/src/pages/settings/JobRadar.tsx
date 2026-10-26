import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus, Radar, Trash2 } from "lucide-react";
import {
  fetchRadar,
  previewRadar,
  updateRadar,
  type RadarInput,
} from "@/api/radar";
import { apiDetail } from "@/api/client";
import { Button, EmptyState } from "@/components/ui";
import type { ExploreResponse } from "@/types/wire";

const SENIORITY_BANDS = ["intern", "junior", "mid", "senior", "lead", "principal"];
const CADENCES = ["off", "instant", "daily", "weekly"] as const;
const MAX_LOCATIONS = 12;

type LocationRow = { city: string; country: string; remote: boolean };

export function JobRadarSettings() {
  const { t } = useTranslation();
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordDraft, setKeywordDraft] = useState("");
  const [locations, setLocations] = useState<LocationRow[]>([]);
  const [seniority, setSeniority] = useState<string[]>([]);
  const [onsitePolicy, setOnsitePolicy] = useState<"" | "onsite" | "hybrid" | "remote">("");
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryCurrency, setSalaryCurrency] = useState("");
  const [cadence, setCadence] = useState<(typeof CADENCES)[number]>("off");
  const [enabled, setEnabled] = useState(false);
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const [preview, setPreview] = useState<ExploreResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    void fetchRadar()
      .then((radar) => {
        setKeywords(radar.keywords ?? []);
        setLocations(
          (radar.locations ?? []).map((loc) => ({
            city: loc.city ?? "",
            country: loc.country ?? "",
            remote: loc.remote ?? false,
          })),
        );
        setSeniority(radar.seniority ?? []);
        setOnsitePolicy((radar.onsite_policy ?? "") as typeof onsitePolicy);
        setSalaryMin(radar.salary_min_annual != null ? String(radar.salary_min_annual) : "");
        setSalaryCurrency(radar.salary_currency ?? "");
        setCadence(radar.cadence ?? "off");
        setEnabled(radar.enabled ?? false);
      })
      .catch((err) => {
        setError(apiDetail(err) || t("jobRadar.loadError"));
      });
  }, []);

  const toPayload = (): RadarInput => ({
    keywords,
    locations: locations
      .filter((row) => row.city || row.country || row.remote)
      .map((row) => ({
        city: row.city || null,
        country: row.country || null,
        remote: row.remote,
      })),
    seniority,
    onsite_policy: onsitePolicy || null,
    salary_min_annual: salaryMin ? Number(salaryMin) : null,
    salary_currency: salaryMin ? salaryCurrency.toUpperCase() : null,
    source_keys: [],
    cadence,
    enabled,
  });

  const save = async () => {
    setError("");
    setSavedNote("");
    try {
      await updateRadar(toPayload());
      setSavedNote(t("jobRadar.saved"));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const test = async () => {
    setError("");
    setSavedNote("");
    setPreviewing(true);
    try {
      setPreview(await previewRadar(toPayload()));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setPreviewing(false);
    }
  };

  const addKeyword = () => {
    const value = keywordDraft.trim();
    if (value && !keywords.includes(value) && keywords.length < 24) {
      setKeywords([...keywords, value]);
    }
    setKeywordDraft("");
  };

  const addLocation = () => {
    if (locations.length < MAX_LOCATIONS) {
      setLocations([...locations, { city: "", country: "", remote: false }]);
    }
  };

  const updateLocation = (index: number, patch: Partial<LocationRow>) => {
    setLocations(locations.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="job-radar">
      <p className="text-slate-500">{t("jobRadar.subtitle")}</p>
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {savedNote && <p className="text-sm text-emerald-600">{savedNote}</p>}

      <section className="space-y-2">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            data-testid="radar-enabled"
          />
          {t("jobRadar.enabled")}
        </label>
        <p className="text-xs text-slate-400">{t("jobRadar.enabledHint")}</p>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold text-sm">{t("jobRadar.keywordsHeading")}</h2>
        <p className="text-xs text-slate-400">{t("jobRadar.keywordsHint")}</p>
        <div className="flex gap-2">
          <input
            value={keywordDraft}
            onChange={(e) => setKeywordDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addKeyword())}
            placeholder={t("jobRadar.keywordPlaceholder")}
            className="flex-1 border border-slate-200 rounded-lg px-3 py-1.5 text-sm"
            data-testid="radar-keyword-input"
          />
          <Button variant="outline" onClick={addKeyword}>
            <Plus className="w-4 h-4" />
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {keywords.map((keyword) => (
            <span
              key={keyword}
              className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded-full inline-flex items-center gap-1"
            >
              {keyword}
              <button
                onClick={() => setKeywords(keywords.filter((k) => k !== keyword))}
                aria-label={`${t("jobRadar.removeKeyword")} ${keyword}`}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold text-sm">{t("jobRadar.locationsHeading")}</h2>
        {locations.length === 0 && (
          <EmptyState icon={Radar} compact title={t("jobRadar.noLocations")} />
        )}
        {locations.map((row, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              value={row.city}
              onChange={(e) => updateLocation(index, { city: e.target.value })}
              placeholder={t("jobRadar.cityPlaceholder")}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm flex-1"
              aria-label={t("jobRadar.cityPlaceholder")}
            />
            <input
              value={row.country}
              onChange={(e) => updateLocation(index, { country: e.target.value })}
              placeholder={t("jobRadar.countryPlaceholder")}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm flex-1"
              aria-label={t("jobRadar.countryPlaceholder")}
            />
            <label className="flex items-center gap-1 text-xs text-slate-500 whitespace-nowrap">
              <input
                type="checkbox"
                checked={row.remote}
                onChange={(e) => updateLocation(index, { remote: e.target.checked })}
              />
              {t("jobRadar.remote")}
            </label>
            <button
              onClick={() => setLocations(locations.filter((_, i) => i !== index))}
              aria-label={t("jobRadar.removeLocation")}
            >
              <Trash2 className="w-4 h-4 text-slate-400" />
            </button>
          </div>
        ))}
        <Button variant="outline" onClick={addLocation} className="text-sm">
          <Plus className="w-4 h-4" /> {t("jobRadar.addLocation")}
        </Button>
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold text-sm">{t("jobRadar.filtersHeading")}</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="text-sm">
            <span className="block text-xs text-slate-400 mb-1">{t("jobRadar.onsitePolicy")}</span>
            <select
              value={onsitePolicy}
              onChange={(e) => setOnsitePolicy(e.target.value as typeof onsitePolicy)}
              className="w-full border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="radar-onsite"
            >
              <option value="">{t("jobRadar.any")}</option>
              {["onsite", "hybrid", "remote"].map((policy) => (
                <option key={policy} value={policy}>
                  {t(`jobRadar.onsite.${policy}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-xs text-slate-400 mb-1">{t("jobRadar.cadenceLabel")}</span>
            <select
              value={cadence}
              onChange={(e) => setCadence(e.target.value as typeof cadence)}
              className="w-full border border-slate-200 rounded-lg px-2 py-1.5"
              data-testid="radar-cadence"
            >
              {CADENCES.map((option) => (
                <option key={option} value={option}>
                  {t(`jobRadar.cadenceOptions.${option}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-xs text-slate-400 mb-1">
              {t("jobRadar.salaryMinAnnual")}
            </span>
            <div className="flex gap-2">
              <input
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value.replace(/[^0-9]/g, ""))}
                className="flex-1 border border-slate-200 rounded-lg px-2 py-1.5"
                inputMode="numeric"
                data-testid="radar-salary"
              />
              <input
                value={salaryCurrency}
                onChange={(e) => setSalaryCurrency(e.target.value.toUpperCase().slice(0, 3))}
                placeholder={t("jobRadar.currencyPlaceholder")}
                className="w-16 border border-slate-200 rounded-lg px-2 py-1.5"
                aria-label={t("jobRadar.currency")}
              />
            </div>
            <span className="block text-xs text-slate-400 mt-1">
              {t("jobRadar.salaryAnnualHint")}
            </span>
          </label>
          <div className="text-sm">
            <span className="block text-xs text-slate-400 mb-1">{t("jobRadar.seniority")}</span>
            <div className="flex flex-wrap gap-2">
              {SENIORITY_BANDS.map((band) => (
                <label key={band} className="flex items-center gap-1 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={seniority.includes(band)}
                    onChange={(e) =>
                      setSeniority(
                        e.target.checked
                          ? [...seniority, band]
                          : seniority.filter((s) => s !== band),
                      )
                    }
                  />
                  {band}
                </label>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="flex items-center gap-3">
        <Button onClick={() => void save()} data-testid="radar-save">
          {t("jobRadar.save")}
        </Button>
        <Button variant="outline" onClick={() => void test()} disabled={previewing}>
          {previewing ? t("jobRadar.testing") : t("jobRadar.test")}
        </Button>
      </div>

      {preview && (
        <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-2" data-testid="radar-preview">
          <h2 className="font-semibold text-sm">
            {t("jobRadar.previewTitle", { count: preview.total })}
          </h2>
          {(preview.items ?? []).length === 0 ? (
            <p className="text-sm text-slate-400">{t("jobRadar.previewEmpty")}</p>
          ) : (
            <ul className="space-y-1">
              {(preview.items ?? []).map((item) => (
                <li key={item.id} className="text-sm text-slate-600">
                  {item.title}
                  <span className="text-xs text-slate-400">
                    {item.org ? ` · ${item.org}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link to="/postings/search" className="text-sm text-primary-700 inline-block">
            {t("jobRadar.openExplore")}
          </Link>
        </section>
      )}
    </div>
  );
}
