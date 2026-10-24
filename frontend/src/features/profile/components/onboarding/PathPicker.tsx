import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CapabilityChips } from "@neuronection/assistant-ui/capability-chips";
import {
  FILL_LABEL_KEYS,
  PATHS,
  PATH_LABEL_KEYS,
} from "@/config/onboardingPaths";
import type { OnboardingPath } from "@/types";

/** The /onboarding hero: brand panel + one tile per start
 * path. Tokens only; entrance motion via motion.css (reduced-motion
 * safe). Each tile is a real button with its title as accessible name. */
export function PathPicker({
  onChoose,
  busy,
}: {
  onChoose: (path: OnboardingPath) => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10"
      data-testid="path-picker"
    >
      <aside
        className="relative hidden overflow-hidden rounded-3xl border border-[var(--as-border)] p-8 lg:flex lg:flex-col lg:justify-between"
        style={{
          backgroundColor:
            "color-mix(in srgb, var(--as-accent) 10%, var(--as-surface))",
        }}
        data-testid="path-hero"
      >
        <JobGraphMotif />
        <div className="relative">
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--as-muted-fg)]">
            {t("app.name")}
          </p>
          <h1 className="mt-3 text-3xl font-bold leading-tight text-[var(--as-fg)]">
            {t("onboarding.heroTitleSide")}
          </h1>
          <p className="mt-3 max-w-xs text-sm text-[var(--as-muted-fg)]">
            {t("onboarding.heroBody")}
          </p>
        </div>
        <ol className="relative space-y-3 text-sm text-[var(--as-muted-fg)]">
          {(
            [
              t("onboarding.heroStep1"),
              t("onboarding.heroStep2"),
              t("onboarding.heroStep3"),
            ] as const
          ).map((step, i) => (
            <li key={step} className="flex items-center gap-3">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-[var(--as-accent)]"
                style={{
                  backgroundColor:
                    "color-mix(in srgb, var(--as-accent) 16%, transparent)",
                }}
              >
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </aside>

      <section className="flex min-h-0 flex-col justify-center py-2">
        <header className="lg:hidden">
          <p className="text-xs font-semibold uppercase tracking-widest text-[var(--as-muted-fg)]">
            {t("app.name")}
          </p>
          <h1 className="mt-1 text-2xl font-bold text-[var(--as-fg)]">
            {t("onboarding.heroTitleMobile")}
          </h1>
        </header>
        <h2 className="mt-4 text-lg font-semibold text-[var(--as-fg)] lg:mt-0">
          {t("onboarding.whatBrings")}
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {PATHS.map((path, i) => (
            <button
              key={path.key}
              type="button"
              disabled={busy}
              onClick={() => onChoose(path.key)}
              data-testid={`path-${path.key}`}
              className="path-card-in group flex h-full flex-col rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-5 text-left transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:border-[var(--as-accent)] hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] disabled:opacity-60"
              style={{ animationDelay: `${i * 70}ms` }}
            >
              <span className="flex items-center justify-between">
                <span
                  className="flex h-10 w-10 items-center justify-center rounded-xl text-[var(--as-accent)]"
                  style={{
                    backgroundColor:
                      "color-mix(in srgb, var(--as-accent) 14%, transparent)",
                  }}
                >
                  <path.icon className="h-5 w-5" aria-hidden />
                </span>
                <span
                  className="text-sm text-[var(--as-muted-fg)] transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-[var(--as-accent)]"
                  aria-hidden
                >
                  →
                </span>
              </span>
              <span className="mt-3 block font-semibold text-[var(--as-fg)]">
                {t(PATH_LABEL_KEYS[path.key].titleKey, {
                  defaultValue: path.title,
                })}
              </span>
              <span className="mt-1 block text-sm text-[var(--as-muted-fg)]">
                {t(PATH_LABEL_KEYS[path.key].taglineKey, {
                  defaultValue: path.tagline,
                })}
              </span>
              {path.fills.length > 0 && (
                <CapabilityChips
                  className="mt-4"
                  variant="badge"
                  ariaLabel={`${t(PATH_LABEL_KEYS[path.key].titleKey, { defaultValue: path.title })} ${t("onboarding.asksAbout")}`}
                  caps={path.fills.map((label) => ({
                    value: label,
                    label: t(FILL_LABEL_KEYS[label] ?? label, {
                      defaultValue: label,
                    }),
                  }))}
                  selected={path.fills}
                />
              )}
            </button>
          ))}
        </div>
        {busy && (
          <p className="mt-3 flex items-center gap-2 text-sm text-[var(--as-muted-fg)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
            {t("onboarding.settingUp")}
          </p>
        )}
      </section>
    </div>
  );
}

/** Static decorative job-graph motif — presentational only, strokes ride
 * currentColor so the panel's accent tint drives it. */
function JobGraphMotif() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 320 240"
      className="pointer-events-none absolute -right-10 -top-8 h-64 w-80 text-[var(--as-accent)] opacity-[0.16]"
      fill="none"
    >
      {(
        [
          [60, 60, 160, 110],
          [160, 110, 265, 70],
          [160, 110, 120, 190],
          [160, 110, 250, 175],
          [60, 60, 120, 190],
          [265, 70, 250, 175],
        ] as const
      ).map(([x1, y1, x2, y2]) => (
        <line
          key={`${x1}-${y1}-${x2}-${y2}`}
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke="currentColor"
          strokeWidth="2"
        />
      ))}
      {(
        [
          [60, 60, 14],
          [160, 110, 20],
          [265, 70, 12],
          [120, 190, 12],
          [250, 175, 16],
        ] as const
      ).map(([cx, cy, r]) => (
        <circle
          key={`${cx}-${cy}`}
          cx={cx}
          cy={cy}
          r={r}
          fill="currentColor"
        />
      ))}
    </svg>
  );
}
