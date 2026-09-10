import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plus, Trash2, Zap } from "lucide-react";
import { getCountryFlag } from "@neuronection/assistant-ui/countries";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { Button, ConfirmationModal, ConnectionTestRow, EmptyState } from "@/components/ui";
import type { ConnectionTestStatus } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";

const GROUPS = [
  {
    scope: "system",
    titleKey: "aiSettings.providers.globalTitle",
    emptyKey: "aiSettings.providers.globalEmpty",
  },
  {
    scope: "user",
    titleKey: "aiSettings.providers.personalTitle",
    emptyKey: "aiSettings.providers.personalEmpty",
  },
] as const;

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
  const { t } = useTranslation();
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
      GROUPS.map(({ scope, titleKey, emptyKey }) => ({
        scope: scope as AIProvider["scope"],
        titleKey,
        emptyKey,
        items: providers.filter((p) => p.scope === scope),
      })),
    [providers],
  );

  return (
    <div className="space-y-6" data-testid="providers-tab">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{t("aiSettings.providers.hint")}</p>
        <Button size="sm" onClick={onAdd}>
          <Plus className="w-4 h-4" />
          {t("aiSettings.providers.add")}
        </Button>
      </div>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      {cards.map(({ scope, titleKey, emptyKey, items }) => (
        <section key={scope}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">{t(titleKey)}</h3>
            {scope === "system" && !canManageGlobal && (
              <span className="text-xs text-slate-400">{t("aiSettings.providers.readOnlyNote")}</span>
            )}
          </div>
          {items.length === 0 ? (
            <EmptyState icon={Zap} compact title={t(emptyKey)} />
          ) : (
            <div className="grid gap-3">
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
                          {p.is_local != null && (
                            <span
                              className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded shrink-0"
                              data-testid={`provider-hosting-${p.id}`}
                            >
                              {p.is_local
                                ? t("aiSettings.providers.hostingLocal")
                                : t("aiSettings.providers.hostingCloud")}
                            </span>
                          )}
                          {p.country && (
                            <span
                              className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded shrink-0"
                              title={p.country}
                              data-testid={`provider-country-${p.id}`}
                            >
                              {getCountryFlag(p.country)} {p.country}
                            </span>
                          )}
                          {!p.is_active && <span className="text-xs text-rose-600">{t("aiSettings.providers.inactive")}</span>}
                        </p>
                        <p className="text-xs text-slate-400 font-mono truncate mt-0.5">
                          {p.api_base} · {p.api_key ?? t("aiSettings.providers.keyNotSet")}
                        </p>
                        <ConnectionTestRow
                          variant="inline"
                          className="mt-1.5"
                          label={t("aiSettings.providers.connection")}
                          status={statusFor(p)}
                          errorMessage={results[p.id]?.error ?? null}
                          meta={
                            activeCount > 0
                              ? t("aiSettings.providers.modelsCount", { count: activeCount })
                              : t("aiSettings.providers.noModelsHint")
                          }
                          testLabel={t("aiSettings.providers.test")}
                          okLabel={t("aiSettings.providers.testOk")}
                          failLabel={t("aiSettings.providers.testFail")}
                          onTest={testModel ? () => void runTest(p) : undefined}
                          disabled={testingId === p.id}
                        />
                      </div>
                      {editable && (
                        <div className="flex gap-1 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("aiSettings.providers.editAria", { name: p.name })}
                            onClick={() => onEdit(p)}
                          >
                            <Pencil className="w-4 h-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("aiSettings.providers.deleteAria", { name: p.name })}
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
        title={t("aiSettings.providers.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("aiSettings.providers.deleteDescription")}
        confirmLabel={t("aiSettings.providers.deleteConfirm")}
        cancelLabel={t("common.cancel")}
        destructive
        busy={deleteBusy}
        onConfirm={() => {
          if (deleting) void remove(deleting);
        }}
      />
    </div>
  );
}
