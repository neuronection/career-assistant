import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Stepper } from "@neuronection/assistant-ui/wizard";
import { useProfileStore } from "@/stores/profileStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { apiDetail } from "@/api/client";
import { setOnboardingPath } from "@/api/onboarding";
import { STEP_LABEL_KEYS, stepsForPath } from "@/config/onboardingPaths";
import { PathPicker } from "@/components/onboarding/PathPicker";
import { CvIntakeFlow } from "@/components/intake/CvIntakeFlow";
import type { SectionCardHandle } from "@/components/profile/sections/shared";
import type { OnboardingPath } from "@/types";
import { AcademicsCard } from "@/components/profile/sections/AcademicsCard";
import { BasicsCard } from "@/components/profile/sections/BasicsCard";
import { EducationMiniCard } from "@/components/profile/sections/EducationMiniCard";
import { InterestsCard } from "@/components/profile/sections/InterestsCard";

/** Onboarding: the hero path picker resolves WHY the user came;
 * the chosen path's step list (from the onboardingPaths registry, filtered
 * by bootstrap flags) renders the shared profile section cards with
 * explicit per-step saves. The cards own their drafts; no wizard draft. */
export function Onboarding() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { bootstrap, loaded: bootstrapLoaded, apply } = useBootstrapStore();
  const path = bootstrap?.onboarding_path ?? null;
  const [choosing, setChoosing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  const { profile, load, loadTaxonomy, saveSection, analyze } = useProfileStore();
  const stepRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<SectionCardHandle>(null);

  useEffect(() => {
    void load();
    void loadTaxonomy();
  }, [load, loadTaxonomy]);

  useEffect(() => {
    if (path === "target") navigate("/onboarding/express", { replace: true });
  }, [path, navigate]);

  const educationStep = bootstrap?.features.education_step ?? false;
  const steps = useMemo(
    () => stepsForPath(path, { educationStep }),
    [path, educationStep]
  );

  useEffect(() => {
    stepRef.current?.scrollTo({ top: 0 });
  }, [step]);

  if (!bootstrapLoaded) {
    return (
      <p className="py-16 text-center text-sm text-[var(--as-muted-fg)]">
        {t("common.loading")}
      </p>
    );
  }

  const choose = async (next: OnboardingPath) => {
    setChoosing(true);
    setError("");
    try {
      apply(await setOnboardingPath(next));
      if (next === "target") navigate("/onboarding/express");
      else if (next === "browse") navigate("/");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setChoosing(false);
    }
  };

  const changeStart = async () => {
    setChoosing(true);
    setError("");
    setStep(0);
    try {
      apply(await setOnboardingPath(null));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setChoosing(false);
    }
  };

  if (!path || path === "browse") {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col">
        {error && <p className="mb-2 text-sm text-rose-600">{error}</p>}
        <PathPicker onChoose={(next) => void choose(next)} busy={choosing} />
      </div>
    );
  }

  if (path === "target" || steps.length === 0) return null;

  const next = async () => {
    setSaved(false);
    setError("");
    const ok = cardRef.current ? await cardRef.current.save() : true;
    if (!ok) {
      setError(t("onboarding.fixFields"));
      return;
    }
    setSaved(true);
    if (step < steps.length - 1) {
      setStep(step + 1);
      return;
    }
    if (path === "cv_import") {
      setFinished(true);
      return;
    }
    setAnalyzing(true);
    try {
      await analyze();
      navigate("/");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const finishAnalyze = async () => {
    setAnalyzing(true);
    setError("");
    try {
      await analyze();
      navigate("/");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setAnalyzing(false);
    }
  };

  if (finished) {
    return (
      <div
        className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center"
        data-testid="cv-import-finish"
      >
        <h1 className="text-2xl font-bold text-[var(--as-fg)]">
          {t("onboarding.finishTitle")}
        </h1>
        <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
          {t("onboarding.finishBody")}
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Link
            to="/cv?generate=1"
            className="rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-5 hover:border-[var(--as-accent)]"
            data-testid="finish-generate-cv"
          >
            <p className="font-semibold text-[var(--as-fg)]">{t("onboarding.finishGenerateTitle")}</p>
            <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
              {t("onboarding.finishGenerateBody")}
            </p>
          </Link>
          <Link
            to="/cv"
            className="rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-5 hover:border-[var(--as-accent)]"
            data-testid="finish-cv"
          >
            <p className="font-semibold text-[var(--as-fg)]">{t("onboarding.finishCvTitle")}</p>
            <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
              {t("onboarding.finishCvBody")}
            </p>
          </Link>
          <Link
            to="/postings/search"
            className="rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-5 hover:border-[var(--as-accent)]"
            data-testid="finish-explore"
          >
            <p className="font-semibold text-[var(--as-fg)]">{t("onboarding.finishExploreTitle")}</p>
            <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
              {t("onboarding.finishExploreBody")}
            </p>
          </Link>
          <button
            type="button"
            onClick={() => void finishAnalyze()}
            disabled={analyzing}
            className="rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-5 text-left hover:border-[var(--as-accent)] disabled:opacity-50"
            data-testid="finish-analyze"
          >
            <p className="font-semibold text-[var(--as-fg)]">
              {analyzing ? t("onboarding.analyzing") : t("onboarding.finishAnalyzeTitle")}
            </p>
            <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
              {t("onboarding.finishAnalyzeBody")}
            </p>
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
      </div>
    );
  }

  return (
    <div
      className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col"
      data-testid="onboarding"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <Stepper
          className="min-w-0 flex-1"
          steps={steps.map((s) => ({
            id: s.name,
            label: t(STEP_LABEL_KEYS[s.name], { defaultValue: s.name }),
          }))}
          current={step}
          variant="labels"
          onStepClick={(i) => {
            if (i >= step) return;
            setSaved(false);
            setError("");
            setStep(i);
          }}
        />
        <button
          type="button"
          onClick={() => void changeStart()}
          disabled={choosing}
          className="shrink-0 text-xs text-[var(--as-muted-fg)] underline-offset-2 hover:text-[var(--as-accent)] hover:underline"
          data-testid="change-start"
        >
          {t("onboarding.differentStart")}
        </button>
      </div>

      <div className="mt-4 flex min-h-0 flex-1 flex-col rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:p-6 md:p-8">
        <div
          ref={stepRef}
          className="flex min-h-0 flex-1 flex-col overflow-y-auto pr-1"
          data-testid="step-content"
        >
          {!profile ? (
            <p className="text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
          ) : (
            <>
              {steps[step].name === "Import CV" && (
                <CvIntakeFlow ref={cardRef} onApplied={() => void load()} />
              )}
              {steps[step].name === "Basics" && (
                <BasicsCard
                  ref={cardRef}
                  initial={profile.basics}
                  onSave={saveSection}
                  mode="manual"
                  variant="onboarding"
                />
              )}
              {steps[step].name === "Study preferences" && (
                <AcademicsCard
                  ref={cardRef}
                  initial={profile.academics}
                  onSave={saveSection}
                  mode="manual"
                  variant="onboarding"
                />
              )}
              {steps[step].name === "Education" && (
                <EducationMiniCard ref={cardRef} />
              )}
              {steps[step].name === "Interests" && (
                <InterestsCard
                  ref={cardRef}
                  initial={profile.interests}
                  onSave={saveSection}
                  mode="manual"
                  variant="onboarding"
                />
              )}
            </>
          )}
        </div>

        <div className="sticky bottom-0 -mx-4 -mb-4 mt-3 border-t border-[var(--as-border)] bg-[var(--as-surface)] px-4 py-3 backdrop-blur sm:-mx-6 sm:-mb-6 sm:px-6 sm:py-4 md:-mx-8 md:-mb-8 md:px-8">
          {error && <p className="text-sm text-rose-600">{error}</p>}
          {saved && step < steps.length - 1 && !error && (
            <p className="text-sm text-emerald-600">{t("onboarding.savedCheck")}</p>
          )}
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(Math.max(0, step - 1))}
              disabled={step === 0}
              className="rounded-lg border border-[var(--as-border)] px-4 py-2 text-sm disabled:opacity-40"
            >
              {t("onboarding.back")}
            </button>
            <button
              type="button"
              onClick={() => void next()}
              disabled={analyzing}
              className="flex items-center gap-1 rounded-lg bg-primary-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {step === steps.length - 1 ? (
                path === "cv_import" ? (
                  t("onboarding.finish")
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />{" "}
                    {analyzing ? t("onboarding.analyzing") : t("onboarding.finishAnalyze")}
                  </>
                )
              ) : (
                t("onboarding.saveContinue")
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
