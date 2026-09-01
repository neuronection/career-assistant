import { useEffect, useMemo, useState } from "react";
import { Pencil, Plus, Trash2, Zap } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { Button, ConfirmationModal, ConnectionTestRow, EmptyState } from "@/components/ui";
import type { ConnectionTestStatus } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";

const STRINGS = {
  hint: "A provider is an API endpoint (OpenAI, OpenRouter, Ollama, LM Studio…) holding the key and base URL.",
  add: "Add provider",
  groups: [
    { scope: "system", title: "Global providers", empty: "No global providers configured." },
    { scope: "user", title: "Personal providers", empty: "No personal providers yet." },
  ] as const,
  readOnlyNote: "read-only (admin required)",
  inactive: "inactive",
  keyNotSet: "key: not set",
  connection: "Connection",
  test: "Test",
  testOk: "Connected",
  testFail: "Failed",
  modelsCount: "models",
  noModelsHint: "Register a model first — the connection test sends a tiny completion.",
  deleteTitle: (name: string) => `Delete ${name}?`,
  deleteDescription: "Its models and task assignments will be removed too.",
  deleteConfirm: "Delete",
  cancel: "Cancel",
};

interface ProvidersTabProps {
  providers: AIProvider[];
  canManageGlobal: boolean;
  onChanged: () => void;
  onAdd: () => void;
  onEdit: (provider: AIProvider) => void;
}

interface TestResult {
  ok: boolean;
  error?: string;
}

export function ProvidersTab({ providers, canManageGlobal, onChanged, onAdd, onEdit }: ProvidersTabProps) {
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, aiApi.ProviderModelInfo[]>>({});
  const [testingId, setTestingId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [deleting, setDeleting] = useState<AIProvider | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    aiApi
      .fetchAllModels()
      .then((rows) => {
        if (cancelled) return;
        const grouped: Record<string, aiApi.ProviderModelInfo[]> = {};
        for (const m of rows) {
          grouped[m.provider_id] = grouped[m.provider_id] ?? [];
          grouped[m.provider_id].push(m);
        }
        setModelsByProvider(grouped);
      })
      .catch(() => setModelsByProvider({}));
    return () => {
      cancelled = true;
    };
  }, []);

  const testModelFor = (providerId: string): aiApi.ProviderModelInfo | null =>
    modelsByProvider[providerId]?.[0] ?? null;

  const runTest = async (provider: AIProvider) => {
    const model = testModelFor(provider.id);
    if (!model) return;
    setError("");
    setTestingId(provider.id);
    try {
      const result = await aiApi.testConnection(provider.id, model.id);
      setResults((prev) => ({
        ...prev,
        [provider.id]: result.ok ? { ok: true } : { ok: false, error: result.error ?? "unknown error" },
      }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [provider.id]: { ok: false, error: apiDetail(err) } }));
    } finally {
      setTestingId(null);
    }
  };

  const remove = async (provider: AIProvider) => {
    if (!deleting) return;
    setError("");
    setDeleteBusy(true);
    try {
      await aiApi.deleteProvider(provider.id);
      setDeleting(null);
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const statusFor = (provider: AIProvider): ConnectionTestStatus => {
    if (testingId === provider.id) return "testing";
    const result = results[provider.id];
    if (!result) return "idle";
    return result.ok ? "ok" : "fail";
  };

  const cards = useMemo(
    () =>
      STRINGS.groups.map(({ scope, title, empty }) => ({
        scope: scope as AIProvider["scope"],
        title,
        empty,
        items: providers.filter((p) => p.scope === scope),
      })),
    [providers],
  );

  return (
    <div className="space-y-6" data-testid="providers-tab">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{STRINGS.hint}</p>
        <Button size="sm" onClick={onAdd}>
          <Plus className="w-4 h-4" />
          {STRINGS.add}
        </Button>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      {cards.map(({ scope, title, empty, items }) => (
        <section key={scope}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
            {scope === "system" && !canManageGlobal && (
              <span className="text-xs text-slate-400">{STRINGS.readOnlyNote}</span>
            )}
          </div>
          {items.length === 0 ? (
            <EmptyState icon={Zap} compact title={empty} />
          ) : (
            <div className="grid md:grid-cols-2 gap-3">
              {items.map((p) => {
                const editable = scope === "user" || canManageGlobal;
                const testModel = testModelFor(p.id);
                const activeCount = modelsByProvider[p.id]?.length ?? 0;
                return (
                  <div key={p.id} className="bg-white border border-slate-200 rounded-xl p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-medium flex items-center gap-2">
                          <Zap className="w-4 h-4 text-primary-600 shrink-0" />
                          <span className="truncate">{p.name}</span>
                          <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded shrink-0">
                            {p.provider_type}
                          </span>
                          {!p.is_active && <span className="text-xs text-rose-600">{STRINGS.inactive}</span>}
                        </p>
                        <p className="text-xs text-slate-400 font-mono truncate mt-0.5">
                          {p.api_base} · {p.api_key ?? STRINGS.keyNotSet}
                        </p>
                        <ConnectionTestRow
                          variant="inline"
                          className="mt-1.5"
                          label={STRINGS.connection}
                          status={statusFor(p)}
                          errorMessage={results[p.id]?.error ?? null}
                          meta={
                            activeCount > 0
                              ? `${activeCount} ${STRINGS.modelsCount}`
                              : STRINGS.noModelsHint
                          }
                          testLabel={STRINGS.test}
                          okLabel={STRINGS.testOk}
                          failLabel={STRINGS.testFail}
                          onTest={testModel ? () => void runTest(p) : undefined}
                          disabled={testingId === p.id}
                        />
                      </div>
                      {editable && (
                        <div className="flex gap-1 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Edit ${p.name}`}
                            onClick={() => onEdit(p)}
                          >
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Delete ${p.name}`}
                            onClick={() => setDeleting(p)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      ))}

      <ConfirmationModal
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={STRINGS.deleteTitle(deleting?.name ?? "")}
        description={STRINGS.deleteDescription}
        confirmLabel={STRINGS.deleteConfirm}
        cancelLabel={STRINGS.cancel}
        destructive
        busy={deleteBusy}
        onConfirm={() => {
          if (deleting) void remove(deleting);
        }}
      />
    </div>
  );
}
