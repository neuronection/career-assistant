import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CheckCircle2, RefreshCw, Sparkles } from "lucide-react";

import * as aiApi from "@/api/ai";
import type { AIProvider, AIModel } from "@/api/ai";
import { apiDetail } from "@/api/client";
import { setAiSetupDismissed } from "@/api/stages";
import { Button, ConnectionTestRow, Spinner } from "@/components/ui";
import { AiMockChip } from "@/components/ai/AiSetupPrompt";
import { ProviderModal } from "@/components/settings/ProviderModal";
import { ProviderSetupWizard } from "@/components/settings/ProviderSetupWizard";
import { TasksTab } from "@/components/settings/TasksTab";
import { errorLabel } from "@/components/settings/setupErrors";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";

type Step = "connect" | "verify";
type TestStatus = "idle" | "testing" | "ok" | "fail";

/** First-run system setup (plan 118.2): a skippable page that composes the
 * assistant-ui AI-settings kit — provider tiles → guided form → review →
 * connection test → task assignments. Skipping persists on the profile;
 * the setup prompt keeps pointing here until a provider is configured. */
export function OnboardingSetup() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { bootstrap, load, apply } = useBootstrapStore();
  const user = useAuthStore((state) => state.user);
  const ai = bootstrap?.ai ?? null;

  const [step, setStep] = useState<Step>("connect");
  const [provider, setProvider] = useState<AIProvider | null>(null);
  const [models, setModels] = useState<AIModel[]>([]);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [manualOpen, setManualOpen] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testCode, setTestCode] = useState("");
  const [testError, setTestError] = useState<string | null>(null);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const [skipping, setSkipping] = useState(false);
  const [mockAllowed, setMockAllowed] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    aiApi
      .fetchConfigSummary()
      .then((summary) => setMockAllowed(summary.mock_allowed))
      .catch(() => setMockAllowed(false));
  }, []);

  const refreshProviders = useCallback(async () => {
    try {
      setProviders(await aiApi.fetchProviders());
    } catch {
      setProviders([]);
    }
  }, []);

  useEffect(() => {
    void refreshProviders();
  }, [refreshProviders]);

  useEffect(() => {
    if (step !== "verify" || provider === null) return;
    let cancelled = false;
    aiApi
      .fetchModels(provider.id)
      .then((rows) => {
        if (!cancelled) setModels(rows);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [step, provider, refreshEpoch]);

  const runTest = useCallback(
    async (target: AIProvider, modelId: string) => {
      setTestStatus("testing");
      setTestError(null);
      setTestCode("");
      try {
        const result = await aiApi.testConnection(target.id, modelId);
        if (result.ok) {
          setTestStatus("ok");
        } else {
          setTestStatus("fail");
          setTestCode(result.code ?? "unknown");
          setTestError(result.error ?? null);
        }
      } catch (err) {
        setTestStatus("fail");
        setTestCode("unknown");
        setTestError(apiDetail(err));
      }
    },
    []
  );

  useEffect(() => {
    if (step !== "verify" || provider === null || models.length === 0) return;
    if (testStatus !== "idle") return;
    void runTest(provider, models[0].id);
  }, [step, provider, models, testStatus, runTest]);

  const skip = async () => {
    setSkipping(true);
    setError("");
    try {
      apply(await setAiSetupDismissed(true));
      navigate("/onboarding");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSkipping(false);
    }
  };

  const finish = () => {
    navigate("/onboarding");
  };

  const configured = ai?.configured ?? false;
  const showReady = configured && step === "connect";

  if (!bootstrap) {
    return (
      <div className="flex flex-1 items-center justify-center py-24">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div
      className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-4"
      data-testid="ai-setup-page"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-[var(--as-fg)]">
            <Sparkles className="size-5 text-[var(--as-accent)]" aria-hidden />
            {showReady ? t("aiSetup.page.readyTitle") : t("aiSetup.page.title")}
          </h1>
          <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
            {showReady ? t("aiSetup.page.readyBody") : t("aiSetup.page.body")}
          </p>
          <AiMockChip className="mt-2" />
        </div>
        <button
          type="button"
          onClick={() => void skip()}
          disabled={skipping}
          className="shrink-0 text-xs text-[var(--as-muted-fg)] underline-offset-2 hover:text-[var(--as-accent)] hover:underline disabled:opacity-50"
          data-testid="ai-setup-skip"
        >
          {t("aiSetup.page.skip")}
        </button>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4 sm:p-6">
        {showReady ? (
          <div className="flex flex-col gap-3" data-testid="ai-setup-ready">
            <p className="flex items-center gap-2 text-sm font-medium text-[var(--as-fg)]">
              <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />
              {t("aiSetup.page.readyProvider", {
                model: ai?.default_model ?? "",
                count: ai?.task_coverage.assigned ?? 0,
                total: ai?.task_coverage.total ?? 0,
              })}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={finish} data-testid="ai-setup-continue">
                {t("aiSetup.page.continue")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => navigate("/settings/ai")}>
                {t("aiSetup.page.settings")}
              </Button>
            </div>
          </div>
        ) : step === "connect" ? (
          <ProviderSetupWizard
            frame="page"
            canUseSystemScope={Boolean(user?.is_admin)}
            configuredKeys={providers
              .map((row) => row.preset_key)
              .filter((key): key is string => Boolean(key))}
            onManual={() => setManualOpen(true)}
            onSaved={() => void refreshProviders()}
            onConfigured={(result) => {
              setProvider(result.provider);
              setTestStatus("idle");
              setStep("verify");
              void refreshProviders();
              void load();
            }}
          />
        ) : (
          <div className="space-y-4" data-testid="ai-setup-verify">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-[var(--as-fg)]">
                  {t("aiSetup.page.verifyTitle")}
                </h2>
                <p className="text-sm text-[var(--as-muted-fg)]">
                  {t("aiSetup.page.verifyBody")}
                </p>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setRefreshEpoch((epoch) => epoch + 1);
                  void refreshProviders();
                  void load();
                }}
                data-testid="ai-setup-refresh"
              >
                <RefreshCw className="mr-1 size-3.5" aria-hidden />
                {t("aiSetup.page.refresh")}
              </Button>
            </div>

            {models.length === 0 ? (
              <p className="text-sm text-[var(--as-muted-fg)]" data-testid="ai-setup-no-models">
                {t("aiSetup.page.noModels")}
              </p>
            ) : (
              <div data-testid="ai-setup-connection">
                <ConnectionTestRow
                  status={testStatus}
                  label={t("aiSetup.page.connection")}
                  testLabel={t("aiSettings.providers.test")}
                  okLabel={t("aiSettings.providers.testOk")}
                  failLabel={t("aiSettings.providers.testFail")}
                  idleLabel={t("aiSetup.page.notTested")}
                  errorMessage={
                    testStatus === "fail"
                      ? t(`aiSettings.setup.errors.${errorLabel(testCode)}`)
                      : testError
                  }
                  onTest={() => {
                    if (models[0]) void runTest(provider as AIProvider, models[0].id);
                  }}
                />
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-[var(--as-fg)]">
                {t("aiSetup.page.assignTitle")}
              </h3>
              <p className="text-sm text-[var(--as-muted-fg)]">
                {t("aiSetup.page.assignBody")}
              </p>
            </div>
            <TasksTab
              key={`${refreshEpoch}-${provider?.scope ?? "user"}`}
              canManageGlobal={Boolean(user?.is_admin)}
              initialScope={provider?.scope}
              onChanged={() => void load()}
            />

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--as-border)] pt-3">
              <p className="text-xs text-[var(--as-muted-fg)]">
                {configured
                  ? t("aiSetup.page.configuredHint")
                  : t("aiSetup.page.assignHint")}
              </p>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setStep("connect")}>
                  {t("common.back")}
                </Button>
                <Button
                  size="sm"
                  disabled={!configured}
                  onClick={finish}
                  data-testid="ai-setup-finish"
                >
                  {t("aiSetup.page.finish")}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {!configured && step === "connect" && (
        <p className="text-center text-xs text-[var(--as-muted-fg)]">
          {t("aiSetup.page.settingsHint")}{" "}
          <Link to="/settings/ai" className="underline underline-offset-2">
            {t("aiSetup.page.settings")}
          </Link>
        </p>
      )}

      {manualOpen && (
        <ProviderModal
          provider={null}
          canUseSystemScope={Boolean(user?.is_admin)}
          mockAllowed={mockAllowed}
          onClose={() => setManualOpen(false)}
          onSaved={(saved) => {
            setManualOpen(false);
            if (saved) {
              setProvider(saved);
              setTestStatus("idle");
              setStep("verify");
            }
            void refreshProviders();
            void load();
          }}
        />
      )}
    </div>
  );
}
