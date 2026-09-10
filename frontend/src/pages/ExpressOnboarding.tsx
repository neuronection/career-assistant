import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Rocket, Search } from "lucide-react";
import { expressStart, resolveTarget } from "@/api/onboarding";
import { SearchableDropdown } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type { ResolveResponse } from "@/types";

const STAGES = [
  { value: "student", labelKey: "express.stage.student" },
  { value: "early_career", labelKey: "express.stage.early_career" },
  { value: "experienced", labelKey: "express.stage.experienced" },
  { value: "switching", labelKey: "express.stage.switching" },
  { value: "returning", labelKey: "express.stage.returning" },
];

export function ExpressOnboarding() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [resolution, setResolution] = useState<ResolveResponse | null>(null);
  const [targets, setTargets] = useState<string[]>([]);
  const [location, setLocation] = useState("");
  const [remote, setRemote] = useState(true);
  const [stage, setStage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (query.trim().length < 2) {
      setResolution(null);
      return;
    }
    timer.current = setTimeout(() => {
      void resolveTarget(query)
        .then(setResolution)
        .catch(() => setResolution(null));
    }, 350);
  }, [query]);

  const toggleTarget = (value: string) => {
    setTargets((prev) =>
      prev.includes(value)
        ? prev.filter((t) => t !== value)
        : prev.length >= 3
          ? prev
          : [...prev, value]
    );
  };

  const start = async () => {
    if (targets.length === 0) {
      setError(t("express.pickTarget"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await expressStart({ targets, location: location || undefined, remote, stage: stage || undefined });
      navigate("/");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const archetypes = resolution?.archetypes ?? [];
  const families = resolution?.families ?? [];
  const options = [
    ...archetypes.map((a) => ({
      value: a.code,
      label: `${a.title} · ${t(`families.${a.family_key}`, { defaultValue: a.family_key })}`,
    })),
    ...families
      .filter((f) => !archetypes.some((a) => a.family_key === f.key))
      .map((f) => ({
        value: f.key,
        label: `${f.label} (${t("express.wholeFamily")})`,
      })),
  ];

  return (
    <div className="max-w-2xl mx-auto space-y-6" data-testid="express-onboarding">
      <div>
        <Link
          to="/onboarding"
          className="text-xs text-slate-400 underline-offset-2 hover:text-primary-600 hover:underline"
          data-testid="express-back"
        >
          {t("express.back")}
        </Link>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2 mt-2">
          <Rocket className="w-6 h-6 text-primary-600" /> {t("express.title")}
        </h1>
        <p className="text-slate-500 mt-1">
          {t("express.subtitle")}
        </p>
      </div>

      <section className="bg-white border border-slate-200 rounded-xl p-4 space-y-3">
        <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
          <Search className="w-4 h-4 text-slate-400" /> {t("express.queryLabel")}
        </label>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("express.queryPlaceholder")}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          data-testid="express-query"
        />
        {resolution && archetypes.length === 0 && families.length === 0 && (
          <p className="text-xs text-slate-400">
            {t("express.noMatch")}
          </p>
        )}
        {options.length > 0 && (
          <div className="space-y-1" data-testid="express-suggestions">
            <p className="text-xs font-medium text-slate-400 uppercase">{t("express.pickTargets")}</p>
            {options.slice(0, 8).map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => toggleTarget(option.value)}
                className={`w-full text-left text-sm px-3 py-2 rounded-lg border ${
                  targets.includes(option.value)
                    ? "bg-primary-50 border-primary-400 text-primary-800"
                    : "border-slate-200 hover:border-primary-300"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="bg-white border border-slate-200 rounded-xl p-4 grid md:grid-cols-3 gap-4">
        <label className="text-sm">
          {t("express.city")}
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="Athens"
            className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
        </label>
        <label className="text-sm flex items-end gap-2">
          <input
            type="checkbox"
            checked={remote}
            onChange={(e) => setRemote(e.target.checked)}
            className="accent-primary-600"
          />
          {t("express.remote")}
        </label>
        <div className="text-sm">
          {t("express.stageLabel")}
          <div className="mt-1">
            <SearchableDropdown
              options={STAGES.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
              value={stage}
              onChange={(v) => setStage(v)}
              placeholder={t("express.stagePlaceholder")}
            />
          </div>
        </div>
      </section>

      {error && <p className="text-sm text-rose-600">{error}</p>}
      <button
        onClick={() => void start()}
        disabled={busy || targets.length === 0}
        className="bg-primary-600 text-white font-medium rounded-lg px-5 py-2.5 disabled:opacity-50"
        data-testid="express-start"
      >
        {busy
          ? t("express.settingUp")
          : t("express.start", { suffix: targets.length ? ` (${targets.length})` : "" })}
      </button>
    </div>
  );
}
