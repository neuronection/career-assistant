import { useState } from "react";
import { Trash2, Zap } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { Button, EmptyState } from "@/components/ui";
import { apiDetail } from "@/api/client";

interface ProvidersTabProps {
  providers: AIProvider[];
  canManageGlobal: boolean;
  onChanged: () => void;
  onAdd: () => void;
  onEdit: (provider: AIProvider) => void;
}

export function ProvidersTab({ providers, canManageGlobal, onChanged, onAdd, onEdit }: ProvidersTabProps) {
  const [deleting, setDeleting] = useState<AIProvider | null>(null);
  const [error, setError] = useState("");

  const remove = async (provider: AIProvider) => {
    setError("");
    try {
      await aiApi.deleteProvider(provider.id);
      setDeleting(null);
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const groups: { scope: "system" | "user"; title: string; empty: string }[] = [
    { scope: "system", title: "Global providers", empty: "No global providers configured." },
    { scope: "user", title: "Personal providers", empty: "No personal providers yet." },
  ];

  return (
    <div className="space-y-6" data-testid="providers-tab">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          A provider is an API endpoint (OpenAI, OpenRouter, Ollama, LM Studio…) holding the key and base URL.
        </p>
        <Button size="sm" onClick={onAdd}>
          Add provider
        </Button>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      {groups.map(({ scope, title, empty }) => {
        const items = providers.filter((p) => p.scope === scope);
        return (
          <section key={scope}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
              {scope === "system" && !canManageGlobal && (
                <span className="text-xs text-slate-400">read-only (admin required)</span>
              )}
            </div>
            {items.length === 0 ? (
              <EmptyState icon={Zap} compact title={empty} />
            ) : (
              <div className="grid md:grid-cols-2 gap-3">
                {items.map((p) => (
                  <div key={p.id} className="bg-white border border-slate-200 rounded-xl p-4">
                    <div className="flex items-start justify-between">
                      <div className="min-w-0">
                        <p className="font-medium flex items-center gap-2">
                          <Zap className="w-4 h-4 text-primary-600 shrink-0" />
                          <span className="truncate">{p.name}</span>
                          <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded shrink-0">
                            {p.provider_type}
                          </span>
                          {!p.is_active && <span className="text-xs text-rose-600">inactive</span>}
                        </p>
                        <p className="text-xs text-slate-400 font-mono truncate mt-0.5">{p.api_base}</p>
                        <p className="text-xs text-slate-400 mt-0.5">key: {p.api_key ?? "not set"}</p>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        {(scope === "user" || canManageGlobal) && (
                          <button
                            aria-label={`Edit ${p.name}`}
                            onClick={() => onEdit(p)}
                            className="text-xs text-primary-700 hover:underline px-1"
                          >
                            edit
                          </button>
                        )}
                        {(scope === "user" || canManageGlobal) && (
                          <button
                            aria-label={`Delete ${p.name}`}
                            onClick={() => setDeleting(p)}
                            className="p-1 text-slate-300 hover:text-rose-600"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        );
      })}

      {deleting && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setDeleting(null)} />
          <div className="relative bg-white rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="font-semibold">Delete {deleting.name}?</h3>
            <p className="text-sm text-slate-500 mt-1">Its models and task assignments will be removed too.</p>
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="secondary" size="sm" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button variant="destructive" size="sm" onClick={() => void remove(deleting)}>
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
