import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Plus, X, XCircle } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIModel, AIProvider, ExternalModel } from "@/api/ai";
import { Button, EmptyState, ModelPicker } from "@/components/ui";
import { apiDetail } from "@/api/client";

interface ModelsTabProps {
  providers: AIProvider[];
  canManageGlobal: boolean;
  onChanged: () => void;
}

/**
 * Models-per-provider registry: expandable provider cards; each expanded
 * card renders a ModelManager (list + add via external catalog or manual).
 * Mirrors Health-Assistant ModelsPage/ModelManager.
 */
export function ModelsTab({ providers, canManageGlobal, onChanged }: ModelsTabProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (providers.length === 0) {
    return (
      <EmptyState
        compact
        title="No providers configured yet"
        description="Go to the Providers tab to add a provider first — then register its models here."
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="models-tab">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-slate-900">Models per Provider</h3>
        <span className="px-3 py-1 bg-slate-100 text-slate-500 text-[10px] font-black uppercase tracking-widest rounded-full">
          {providers.length} Providers
        </span>
      </div>

      <div className="space-y-4">
        {providers.map((provider) => {
          const isExpanded = expandedId === provider.id;
          const canEdit = provider.scope === "user" ? provider.is_mine : canManageGlobal;
          return (
            <div
              key={provider.id}
              className={`bg-white rounded-xl border transition-all ${
                isExpanded ? "border-primary-200 shadow-sm" : "border-slate-100"
              }`}
            >
              <div
                className="p-4 flex items-center justify-between cursor-pointer group"
                onClick={() => setExpandedId(isExpanded ? null : provider.id)}
              >
                <div className="flex items-center gap-4">
                  <div
                    className={`p-2 rounded-lg transition-colors ${
                      isExpanded
                        ? "bg-primary-600 text-white"
                        : "bg-slate-100 text-slate-500 group-hover:bg-primary-50"
                    }`}
                  >
                    {isExpanded ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
                  </div>
                  <div>
                    <h4 className="text-md font-bold text-slate-900 flex items-center gap-2">
                      {provider.name}
                      <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">
                        {provider.provider_type}
                      </span>
                    </h4>
                    <p className="text-xs text-slate-400 font-medium font-mono truncate max-w-md">{provider.api_base}</p>
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div className="px-4 pb-4">
                  <div className="border-t border-slate-100 pt-4">
                    <ModelManager provider={provider} canEdit={canEdit} onChanged={onChanged} />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function beautifyModelId(modelId: string): string {
  return modelId
    .replace(/[-:]/g, " ")
    .replace(/(?<!\d)\.|\.(?!\d)/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((word) => {
      if (["gpt", "nlp", "ocr", "llm", "ai"].includes(word.toLowerCase())) {
        return word.toUpperCase();
      }
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
}

function ModelManager({
  provider,
  canEdit,
  onChanged,
}: {
  provider: AIProvider;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [models, setModels] = useState<AIModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState({ name: "", model_name: "" });
  const [error, setError] = useState("");

  const [externalModels, setExternalModels] = useState<ExternalModel[]>([]);
  const [isFetchingExternal, setIsFetchingExternal] = useState(false);
  const [fetchError, setFetchError] = useState("");

  const supportsCatalog = provider.provider_type !== "mock";

  const loadModels = useCallback(async () => {
    try {
      setModels(await aiApi.fetchModels(provider.id));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, [provider.id]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  const loadExternal = useCallback(async () => {
    if (!supportsCatalog || externalModels.length > 0 || isFetchingExternal) return;
    setIsFetchingExternal(true);
    setFetchError("");
    try {
      setExternalModels(await aiApi.fetchExternalModels(provider.id));
    } catch (err) {
      setFetchError(apiDetail(err));
    } finally {
      setIsFetchingExternal(false);
    }
  }, [supportsCatalog, provider.id, externalModels.length, isFetchingExternal]);

  useEffect(() => {
    if (isCreating && supportsCatalog) {
      void loadExternal();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCreating]);

  const selectExternalModel = (modelId: string) => {
    setFormData((prev) => ({
      model_name: modelId,
      name: prev.name === "" || prev.name === prev.model_name ? beautifyModelId(modelId) : prev.name,
    }));
  };

  const handleCreate = async () => {
    if (!formData.name.trim() || !formData.model_name.trim()) return;
    setError("");
    try {
      await aiApi.addModel(provider.id, {
        name: formData.name.trim(),
        model_name: formData.model_name.trim(),
      });
      setIsCreating(false);
      setFormData({ name: "", model_name: "" });
      setExternalModels([]);
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const handleDelete = async (id: string) => {
    setError("");
    try {
      await aiApi.deleteModel(id);
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const handleTest = async (modelId: string) => {
    const result = await aiApi.testConnection(provider.id, modelId);
    return result.ok ? `OK — replied: ${result.reply}` : `Failed: ${result.error}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-md font-bold text-slate-900">Models for {provider.name}</h3>
        {canEdit && !isCreating && (
          <Button
            size="sm"
            onClick={() => {
              setIsCreating(true);
              if (supportsCatalog) void loadExternal();
            }}
          >
            <Plus className="w-4 h-4" /> Add Model
          </Button>
        )}
      </div>

      {(error || fetchError) && (
        <div className="p-3 bg-rose-50 text-rose-700 rounded-lg flex items-center justify-between border border-rose-100">
          <span className="text-sm">{error || fetchError}</span>
          <button
            onClick={() => {
              setError("");
              setFetchError("");
            }}
            className="text-xs underline font-bold px-2 py-1"
          >
            Dismiss
          </button>
        </div>
      )}

      {isCreating && (
        <div className="p-6 bg-white rounded-xl border-2 border-primary-500 shadow-xl relative">
          <div className="flex items-center justify-between mb-5">
            <h4 className="text-md font-black text-slate-900 uppercase tracking-tight">Define New Model</h4>
            <button
              onClick={() => setIsCreating(false)}
              aria-label="Cancel"
              className="p-2 text-slate-400 hover:text-rose-500 rounded-full hover:bg-slate-100"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-[10px] font-black uppercase text-slate-400 tracking-widest ml-1 block">
                Display Name <span className="text-rose-500">*</span>
              </label>
              <input
                type="text"
                autoFocus
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary-500/30"
                placeholder="e.g. GPT-4o Mini"
              />
            </div>
            <div className="space-y-2 relative">
              <label className="text-[10px] font-black uppercase text-slate-400 tracking-widest ml-1 block">
                API Identifier <span className="text-rose-500">*</span>
              </label>
              <div className="space-y-2">
                <input
                  type="text"
                  value={formData.model_name}
                  onChange={(e) => setFormData({ ...formData, model_name: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary-500/30"
                  placeholder="e.g. gpt-4o-mini"
                />
                {supportsCatalog && (
                  <ModelPicker
                    providers={[
                      {
                        id: provider.id,
                        name: provider.name,
                        models: externalModels.map((m) => ({
                          id: m.id,
                          name: m.id,
                          capability: m.owned_by ?? undefined,
                        })),
                      },
                    ]}
                    value={formData.model_name}
                    onChange={selectExternalModel}
                    loading={isFetchingExternal}
                    label="Browse provider catalog"
                    searchPlaceholder="Search model catalog…"
                  />
                )}
              </div>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-6">
            <Button variant="secondary" size="sm" onClick={() => setIsCreating(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => void handleCreate()} disabled={!formData.name.trim() || !formData.model_name.trim()}>
              Create Model
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-400">Loading models…</p>
      ) : models.length === 0 && !isCreating ? (
        <p className="text-sm text-slate-400 italic">No models registered yet.</p>
      ) : (
        <div className="space-y-2">
          {models.map((m) => (
            <ModelRow key={m.id} model={m} canEdit={canEdit} onDelete={() => void handleDelete(m.id)} onTest={handleTest} />
          ))}
        </div>
      )}
    </div>
  );
}

function ModelRow({
  model,
  canEdit,
  onDelete,
  onTest,
}: {
  model: AIModel;
  canEdit: boolean;
  onDelete: () => void;
  onTest: (modelId: string) => Promise<string>;
}) {
  const [testState, setTestState] = useState<{ ok: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);

  return (
    <div className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-800">{model.name}</p>
        <p className="text-xs text-slate-400 font-mono">{model.model_name}</p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {testState && (
          <span className={`text-xs ${testState.ok ? "text-emerald-600" : "text-rose-600"}`}>{testState.message}</span>
        )}
        <button
          disabled={testing}
          onClick={async () => {
            setTesting(true);
            try {
              const message = await onTest(model.id);
              setTestState({ ok: message.startsWith("OK"), message });
            } finally {
              setTesting(false);
            }
          }}
          className="text-xs text-primary-700 hover:underline disabled:opacity-50"
        >
          {testing ? "testing…" : "test"}
        </button>
        {canEdit && (
          <button aria-label={`Delete model ${model.name}`} onClick={onDelete} className="text-slate-300 hover:text-rose-600">
            <XCircle className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
