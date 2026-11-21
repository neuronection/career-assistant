import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import * as aiApi from "@/api/ai";
import type { AIProvider, ConfigSummary, EffectiveAssignment } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";
import { SegmentedTabs, SetupFirstRunCard, Spinner } from "@/components/ui";
import { ProvidersTab } from "@/components/settings/ProvidersTab";
import { ModelsTab } from "@/components/settings/ModelsTab";
import { TasksTab } from "@/components/settings/TasksTab";
import { ProviderModal } from "@/components/settings/ProviderModal";
import { ProviderSetupModal } from "@/components/settings/ProviderSetupModal";
import { ReRunSetupDialog } from "@/components/settings/ReRunSetupDialog";
import { resetConfigSummaryCache } from "@/hooks/useConfigSummary";

type AITab = "providers" | "models" | "tasks";
export type AIScope = "user" | "system";

// The AI tab hosts exactly ai.* domains (ADR-0033): providers, models and
// task assignments. The former `web` tab moved to /settings/tools in plan 27
// Phase 3; its deep link redirects there. Exported for the settings-map
// conformance test.
export const AI_TABS: readonly AITab[] = ["providers", "models", "tasks"];

export function parseAITab(raw: string | null): AITab {
  return (AI_TABS as readonly string[]).includes(raw ?? "") ? (raw as AITab) : "providers";
}

/** AI configuration with URL-synced tabs (?tab=providers|models|tasks).
 * Scope is fixed by the route: `/settings/ai` is the personal (user)
 * surface, `/settings/ai-admin` the instance (system) surface. */
export function AIConfig({ scope = "user" }: { scope?: AIScope }) {
  const user = useAuthStore((s) => s.user);
  if (scope === "system" && !user?.is_admin) {
    return <Navigate to="/settings/ai" replace />;
  }
  return <AIConfigPage scope={scope} />;
}

function AIConfigPage({ scope }: { scope: AIScope }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab");
  const activeTab = parseAITab(tabFromUrl);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [summary, setSummary] = useState<ConfigSummary | null>(null);
  const [canManageGlobal, setCanManageGlobal] = useState(false);
  const [mockAllowed, setMockAllowed] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editProvider, setEditProvider] = useState<AIProvider | "new" | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [rerunProvider, setRerunProvider] = useState<AIProvider | null>(null);

  useEffect(() => {
    // Legacy deep link (INV-6): ?tab=web moved to the tools tab.
    if (tabFromUrl === "web") {
      navigate("/settings/tools", { replace: true });
      return;
    }
    const expected = activeTab === "providers" ? null : activeTab;
    if (tabFromUrl === expected) return;
    const next = new URLSearchParams(searchParams);
    if (expected) next.set("tab", expected);
    else next.delete("tab");
    setSearchParams(next, { replace: true });
  }, [tabFromUrl, activeTab, searchParams, setSearchParams, navigate]);

  const setActive = (tab: AITab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "providers") next.delete("tab");
    else next.set("tab", tab);
    setSearchParams(next, { replace: true });
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summaryData, providerData] = await Promise.all([
        aiApi.fetchConfigSummary(),
        aiApi.fetchProviders(),
      ]);
      setSummary(summaryData);
      setCanManageGlobal(summaryData.can_manage_global);
      setMockAllowed(summaryData.mock_allowed);
      setProviders(providerData);
      resetConfigSummaryCache();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading && providers.length === 0) {
    return (
      <div className="flex w-full flex-col items-center justify-center py-24">
        <Spinner size="lg" />
        <p className="mt-3 text-sm text-slate-400">{t("aiSettings.loading")}</p>
      </div>
    );
  }

  const pageProviders = providers.filter((provider) => provider.scope === scope);
  const hasScopeProviders = pageProviders.length > 0;
  const hasSystemProviders = providers.some((provider) => provider.scope === "system");
  const showFirstRun =
    scope === "system" ? !hasScopeProviders : !hasScopeProviders && !hasSystemProviders;
  const showInstanceNote = scope === "user" && !hasScopeProviders && hasSystemProviders;
  const effectiveByTask: Record<string, EffectiveAssignment> = Object.fromEntries(
    (summary?.tasks ?? []).map((task) => [task.task_type, task]),
  );
  const titleKey = scope === "system" ? "aiSettings.titleInstance" : "aiSettings.title";
  const subtitleKey =
    scope === "system" ? "aiSettings.subtitleInstance" : "aiSettings.subtitle";

  return (
    <div className="space-y-6" data-testid="ai-config" data-scope={scope}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">{t(titleKey)}</h1>
          <p className="text-sm text-slate-500">{t(subtitleKey)}</p>
        </div>
        {user?.is_admin ? (
          <Link
            to={scope === "system" ? "/settings/ai" : "/settings/ai-admin"}
            className="shrink-0 text-sm font-medium text-[var(--as-primary)] hover:underline"
            data-testid="ai-scope-cross-link"
          >
            {t(
              scope === "system"
                ? "aiSettings.openPersonal"
                : "aiSettings.openInstance"
            )}
          </Link>
        ) : null}
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <SegmentedTabs
        ariaLabel={t("aiSettings.tabsAria")}
        className="max-w-md"
        items={AI_TABS.map((tab) => ({
          value: tab,
          label: t(`aiSettings.tab.${tab}`, { defaultValue: tab }),
        }))}
        value={activeTab}
        onValueChange={(next) => setActive(next as AITab)}
      />

      <h2 className="sr-only">
        {t(`aiSettings.tab.${activeTab}`, { defaultValue: activeTab })}
      </h2>

      {activeTab === "providers" && (
        <ProvidersTab
          scope={scope}
          providers={pageProviders}
          canManageGlobal={canManageGlobal}
          onChanged={() => void refresh()}
          onAdd={() => setSetupOpen(true)}
          onEdit={(p) => setEditProvider(p)}
          onRerunSetup={(p) => setRerunProvider(p)}
        />
      )}
      {activeTab === "models" && (
        <ModelsTab
          providers={pageProviders}
          canManageGlobal={canManageGlobal}
          onChanged={() => void refresh()}
        />
      )}
      {activeTab === "tasks" && (
        <TasksTab
          canManageGlobal={canManageGlobal}
          onChanged={() => void refresh()}
          initialScope={scope}
          lockScope
          effectiveByTask={scope === "user" ? effectiveByTask : undefined}
        />
      )}

      {showInstanceNote && activeTab === "providers" && (
        <div
          className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-3 text-sm text-[var(--as-muted-fg)]"
          data-testid="ai-instance-note"
        >
          {t("aiSettings.providers.instanceNote")}
        </div>
      )}

      {setupOpen && (
        <ProviderSetupModal
          canUseSystemScope={scope === "system"}
          initialScope={scope}
          lockScope
          configuredKeys={pageProviders
            .map((p) => p.preset_key)
            .filter((key): key is string => Boolean(key))}
          onClose={() => setSetupOpen(false)}
          onManual={() => {
            setSetupOpen(false);
            setEditProvider("new");
          }}
          onSaved={() => void refresh()}
        />
      )}

      {rerunProvider && (
        <ReRunSetupDialog
          provider={rerunProvider}
          onClose={() => setRerunProvider(null)}
          onApplied={() => void refresh()}
        />
      )}

      {editProvider && (
        <ProviderModal
          provider={editProvider === "new" ? null : editProvider}
          canUseSystemScope={scope === "system"}
          initialScope={scope}
          lockScope
          mockAllowed={mockAllowed}
          onClose={() => setEditProvider(null)}
          onSaved={() => {
            setEditProvider(null);
            void refresh();
          }}
        />
      )}

      {showFirstRun && !loading && activeTab === "providers" && (
        <SetupFirstRunCard
          title={t(
            scope === "system"
              ? "aiSettings.firstRun.instanceTitle"
              : "aiSettings.firstRun.title"
          )}
          body={t(
            scope === "system"
              ? "aiSettings.firstRun.instanceBody"
              : "aiSettings.firstRun.body"
          )}
          setupLabel={t("aiSettings.firstRun.cta")}
          onSetup={() => setSetupOpen(true)}
          data-testid="ai-first-run"
        />
      )}
    </div>
  );
}
