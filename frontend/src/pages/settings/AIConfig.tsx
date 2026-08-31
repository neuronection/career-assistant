import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bot } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { useAuthStore } from "@/stores/authStore";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";
import { ProvidersTab } from "@/components/settings/ProvidersTab";
import { ModelsTab } from "@/components/settings/ModelsTab";
import { TasksTab } from "@/components/settings/TasksTab";
import { ProviderModal } from "@/components/settings/ProviderModal";

type AITab = "providers" | "models" | "tasks";
const TABS: AITab[] = ["providers", "models", "tasks"];

/** AI configuration with URL-synced tabs (?tab=providers|models|tasks). */
export function AIConfig() {
  const user = useAuthStore((s) => s.user);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get("tab") as AITab | null;
  const [activeTab, setActiveTab] = useState<AITab>(
    tabFromUrl && TABS.includes(tabFromUrl) ? tabFromUrl : "providers"
  );
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [canManageGlobal, setCanManageGlobal] = useState(false);
  const [mockAllowed, setMockAllowed] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editProvider, setEditProvider] = useState<AIProvider | "new" | null>(null);

  useEffect(() => {
    if (tabFromUrl && TABS.includes(tabFromUrl) && tabFromUrl !== activeTab) {
      setActiveTab(tabFromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabFromUrl]);

  const setActive = (tab: AITab) => {
    setActiveTab(tab);
    setSearchParams(tab !== "providers" ? { tab } : {}, { replace: true });
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [summaryData, providerData] = await Promise.all([
        aiApi.fetchConfigSummary(),
        aiApi.fetchProviders(),
      ]);
      setCanManageGlobal(summaryData.can_manage_global);
      setMockAllowed(summaryData.mock_allowed);
      setProviders(providerData);
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
        <p className="mt-3 text-sm text-slate-400">Loading AI configuration…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="ai-config">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">AI Configuration</h1>
          <p className="text-sm text-slate-500">
            Every AI feature (matching, generation, parsing, chat) runs on the resolved provider/model.
          </p>
        </div>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex rounded-lg border border-slate-200 overflow-hidden w-fit">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActive(tab)}
            data-testid={`tab-${tab}`}
            className={`text-sm px-4 py-2 capitalize ${
              activeTab === tab ? "bg-primary-600 text-white" : "bg-white hover:bg-slate-50"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "providers" && (
        <ProvidersTab
          providers={providers}
          canManageGlobal={canManageGlobal}
          onChanged={() => void refresh()}
          onAdd={() => setEditProvider("new")}
          onEdit={(p) => setEditProvider(p)}
        />
      )}
      {activeTab === "models" && (
        <ModelsTab
          providers={providers}
          canManageGlobal={canManageGlobal}
          onChanged={() => void refresh()}
        />
      )}
      {activeTab === "tasks" && (
        <TasksTab canManageGlobal={canManageGlobal} onChanged={() => void refresh()} />
      )}

      {editProvider && (
        <ProviderModal
          provider={editProvider === "new" ? null : editProvider}
          canUseSystemScope={Boolean(user?.is_admin)}
          mockAllowed={mockAllowed}
          onClose={() => setEditProvider(null)}
          onSaved={() => {
            setEditProvider(null);
            void refresh();
          }}
        />
      )}

      {providers.length === 0 && !loading && activeTab === "providers" && (
        <EmptyState
          icon={Bot}
          compact
          title="Nothing configured yet"
          description="Without providers the built-in env default (AI_PROVIDER=mock) serves every task."
        />
      )}
    </div>
  );
}
