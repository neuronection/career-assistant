import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, PlugZap, Plus, Sparkles, Trash2, Zap } from "lucide-react";
import { getCountryFlag } from "@neuronection/assistant-ui/countries";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import {
  Button,
  ConfirmationModal,
  EmptyState,
  ProviderCard,
} from "@/components/ui";
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
  onRerunSetup: (provider: AIProvider) => void;
}

interface TestResult {
  ok: boolean;
  error?: string;
}

export function ProvidersTab({
  providers,
  canManageGlobal,
  onChanged,
  onAdd,
  onEdit,
  onRerunSetup,
}: ProvidersTabProps) {
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

  const testModelFor = (providerId: string): aiApi.ProviderModelInfo | null => {
    const rows = modelsByProvider[providerId] ?? [];
    // Chat-capable first: a decision model on a mixed provider would ping
    // the wrong endpoint (the vendor 400s). Decision-only providers fall
    // back to their first model — the backend probes those correctly.
    return (
      rows.find(
        (m) => !m.decision_transport && !(m.caps ?? []).includes("decision"),
      ) ??
      rows[0] ??
      null
    );
  };

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
                const testing = testingId === p.id;
                const actions = [
                  ...(editable && p.preset_key
                    ? [
                        {
                          key: "setup",
                          label: t("aiSettings.setup.automatically"),
                          icon: Sparkles,
                          onSelect: () => onRerunSetup(p),
                        },
                      ]
                    : []),
                  ...(editable
                    ? [
                        {
                          key: "edit",
                          label: t("aiSettings.providers.edit"),
                          icon: Pencil,
                          onSelect: () => onEdit(p),
                        },
                      ]
                    : []),
                  ...(testModel
                    ? [
                        {
                          key: "test",
                          label: t("aiSettings.providers.test"),
                          icon: PlugZap,
                          disabled: testing,
                          pending: testing,
                          onSelect: () => void runTest(p),
                        },
                      ]
                    : []),
                  ...(editable
                    ? [
                        {
                          key: "delete",
                          label: t("aiSettings.providers.deleteConfirm"),
                          icon: Trash2,
                          danger: true,
                          onSelect: () => setDeleting(p),
                        },
                      ]
                    : []),
                ];
                return (
                  <ProviderCard
                    key={p.id}
                    name={p.name}
                    logoPreset={p.preset_key ?? undefined}
                    subtitle={p.api_base}
                    status={statusFor(p)}
                    okLabel={t("aiSettings.providers.testOk")}
                    failLabel={t("aiSettings.providers.testFail")}
                    errorMessage={results[p.id]?.error ?? null}
                    meta={
                      activeCount > 0
                        ? t("aiSettings.providers.modelsCount", { count: activeCount })
                        : t("aiSettings.providers.noModelsHint")
                    }
                    badges={[
                      { key: "type", label: p.provider_type },
                      ...(p.is_local != null
                        ? [
                            {
                              key: "hosting",
                              label: p.is_local
                                ? t("aiSettings.providers.hostingLocal")
                                : t("aiSettings.providers.hostingCloud"),
                              testId: `provider-hosting-${p.id}`,
                            },
                          ]
                        : []),
                      ...(p.country
                        ? [
                            {
                              key: "country",
                              label: `${getCountryFlag(p.country)} ${p.country}`,
                              title: p.country,
                              testId: `provider-country-${p.id}`,
                            },
                          ]
                        : []),
                      ...(!p.api_key
                        ? [
                            {
                              key: "key",
                              label: t("aiSettings.providers.noKey"),
                              danger: true,
                              testId: `provider-key-${p.id}`,
                            },
                          ]
                        : []),
                      ...(!p.is_active
                        ? [
                            {
                              key: "inactive",
                              label: t("aiSettings.providers.inactive"),
                              danger: true,
                            },
                          ]
                        : []),
                    ]}
                    actions={actions}
                    actionsLabel={t("aiSettings.providers.actionsAria", { name: p.name })}
                  />
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
