import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AudioLines, Database, Eye, FileText, Wrench } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { apiDetail } from "@/api/client";
import { ConfirmationModal, ModelRegistry } from "@/components/ui";
import type {
  ModelRegistryDraft,
  ModelRegistryModel,
  ModelRegistryPatch,
  ModelRegistryProvider,
} from "@/components/ui/ModelRegistry";
import type { CapabilityDescriptor } from "@neuronection/assistant-ui";
import { beautifyId } from "@neuronection/assistant-ui/fuzzy";
import { AI_CAPS, guessCaps } from "@/lib/aiCaps";

interface ModelsTabProps {
  providers: AIProvider[];
  canManageGlobal: boolean;
  onChanged: () => void;
}

const NO_CATALOG_HINT_KEY = "aiSettings.models.noCatalogHint";

const REASONING_EFFORT_OPTIONS = ["none", "low", "medium", "high", "max", "xhigh"];

const CAP_ICONS = {
  text: FileText,
  vision: Eye,
  tools: Wrench,
  embeddings: Database,
  audio: AudioLines,
} as const;

const ADD_BATCH = 10;

export function ModelsTab({ providers, canManageGlobal, onChanged }: ModelsTabProps) {
  const { t } = useTranslation();
  const [expandedProviderId, setExpandedProviderId] = useState<string | null>(null);
  const [models, setModels] = useState<aiApi.AIModel[]>([]);
  const [remote, setRemote] = useState<{
    state: "loading" | "error" | "ready";
    error: string | null;
    models: { id: string; caps: string[] }[];
    retryable: boolean;
  }>({ state: "ready", error: null, models: [], retryable: true });
  const [retryTick, setRetryTick] = useState(0);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<ModelRegistryModel | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const loadModels = useCallback(async () => {
    const lists = await Promise.all(
      providers.map((provider) => aiApi.fetchModels(provider.id).catch(() => [] as aiApi.AIModel[])),
    );
    setModels(lists.flat());
  }, [providers]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  const expandedProvider = providers.find((p) => p.id === expandedProviderId) ?? null;
  const supportsCatalog =
    expandedProvider !== null &&
    ["openai", "openai_compatible", "google"].includes(expandedProvider.provider_type);

  useEffect(() => {
    if (expandedProviderId === null || expandedProvider === null) return;
    if (!supportsCatalog) {
      setRemote({
        state: "error",
        error: t(NO_CATALOG_HINT_KEY),
        models: [],
        retryable: false,
      });
      return;
    }
    let cancelled = false;
    setRemote({ state: "loading", error: null, models: [], retryable: true });
    aiApi
      .fetchExternalModels(expandedProviderId)
      .then((rows) => {
        if (cancelled) return;
        setRemote({
          state: "ready",
          error: null,
          models: rows.map((entry) => ({ id: entry.id, caps: guessCaps(entry.id) })),
          retryable: true,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setRemote({ state: "error", error: apiDetail(err), models: [], retryable: true });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedProviderId, supportsCatalog, retryTick]);

  const handleAdd = async (providerId: string, draft: ModelRegistryDraft) => {
    setError("");
    try {
      await aiApi.addModel(providerId, {
        name: draft.label?.trim() || beautifyId(draft.externalId),
        model_name: draft.externalId,
        temperature: draft.temperature ?? null,
        max_tokens: draft.maxTokens ?? null,
        reasoning_effort: draft.reasoningEffort || null,
        caps: draft.caps,
      });
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const handleAddAll = async (providerId: string, drafts: ModelRegistryDraft[]) => {
    setError("");
    try {
      for (let offset = 0; offset < drafts.length; offset += ADD_BATCH) {
        await Promise.all(
          drafts.slice(offset, offset + ADD_BATCH).map((draft) =>
            aiApi.addModel(providerId, {
              name: beautifyId(draft.externalId),
              model_name: draft.externalId,
              temperature: draft.temperature ?? null,
              max_tokens: draft.maxTokens ?? null,
              reasoning_effort: draft.reasoningEffort || null,
              caps: draft.caps,
            }),
          ),
        );
      }
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
      await loadModels();
    }
  };

  const handleUpdate = async (model: ModelRegistryModel, patch: ModelRegistryPatch) => {
    setError("");
    try {
      await aiApi.updateModel(model.id, {
        ...(patch.label !== undefined ? { name: patch.label || beautifyId(model.externalId) } : {}),
        ...(patch.reasoningEffort !== undefined
          ? { reasoning_effort: patch.reasoningEffort || null }
          : {}),
        ...(patch.temperature !== undefined ? { temperature: patch.temperature ?? null } : {}),
        ...(patch.maxTokens !== undefined ? { max_tokens: patch.maxTokens ?? null } : {}),
        ...(patch.caps !== undefined ? { caps: patch.caps } : {}),
      });
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setError("");
    setDeleteBusy(true);
    try {
      await aiApi.deleteModel(deleting.id);
      setDeleting(null);
      await loadModels();
      onChanged();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const registryProviders: ModelRegistryProvider[] = useMemo(
    () =>
      providers.map((provider) => ({
        id: provider.id,
        name: provider.name,
        type: provider.provider_type,
        baseUrl: provider.api_base,
        readOnly: !(provider.scope === "user" ? provider.is_mine : canManageGlobal),
      })),
    [providers, canManageGlobal],
  );

  const registryModels: ModelRegistryModel[] = useMemo(
    () =>
      models.map((model) => ({
        id: model.id,
        providerId: model.provider_id,
        externalId: model.model_name,
        label: model.name || undefined,
        caps: model.caps ?? guessCaps(model.model_name),
        enabled: model.is_active,
        temperature: model.temperature,
        maxTokens: model.max_tokens,
        reasoningEffort: model.reasoning_effort ?? undefined,
      })),
    [models],
  );

  const capDescriptors: CapabilityDescriptor[] = AI_CAPS.map((cap) => ({
    value: cap,
    label: t(`aiSettings.caps.${cap}`, {
      defaultValue: cap.charAt(0).toUpperCase() + cap.slice(1),
    }),
    icon: CAP_ICONS[cap],
  }));

  return (
    <div className="space-y-4" data-testid="models-tab">
      <p className="text-sm text-slate-500">
        {t("aiSettings.models.intro")}
      </p>
      <ModelRegistry
        providers={registryProviders}
        models={registryModels}
        caps={capDescriptors}
        expandedProviderId={expandedProviderId}
        onExpandedProviderChange={setExpandedProviderId}
        remoteModels={remote.models}
        remoteState={remote.state}
        remoteError={remote.error}
        onRetryRemote={remote.retryable ? () => setRetryTick((tick) => tick + 1) : undefined}
        onAddModel={(providerId, draft) => void handleAdd(providerId, draft)}
        onAddAll={(providerId, drafts) => void handleAddAll(providerId, drafts)}
        onUpdateModel={handleUpdate}
        onDeleteModel={setDeleting}
        capsLabel={t("aiSettings.models.capsLabel")}
        capsHint={t("aiSettings.models.capsHint")}
        addLabel={t("aiSettings.models.addLabel")}
        addAllLabel={t("aiSettings.models.addAllLabel")}
        addTitle={t("aiSettings.models.addTitle")}
        editTitle={t("aiSettings.models.editTitle")}
        selectModelLabel={t("aiSettings.models.selectModelLabel")}
        manualIdToggleLabel={t("aiSettings.models.manualIdToggleLabel")}
        editLabel={t("aiSettings.models.editLabel")}
        removeLabel={t("aiSettings.models.removeLabel")}
        missingLabel={t("aiSettings.models.missingLabel")}
        searchPlaceholder={t("aiSettings.models.searchPlaceholder")}
        searchLabel={t("aiSettings.models.searchLabel")}
        emptyProviderLabel={t("aiSettings.models.emptyProviderLabel")}
        externalIdRequiredLabel={t("aiSettings.models.externalIdRequiredLabel")}
        remoteEmptyLabel={t("aiSettings.models.remoteEmptyLabel")}
        remoteLoadingLabel={t("aiSettings.models.remoteLoadingLabel")}
        retryLabel={t("aiSettings.models.retryLabel")}
        customOptionLabel={t("aiSettings.models.customOptionLabel")}
        temperatureLabel={t("aiSettings.models.temperatureLabel")}
        maxTokensLabel={t("aiSettings.models.maxTokensLabel")}
        reasoningEffortOptions={REASONING_EFFORT_OPTIONS}
        labelLabel={t("aiSettings.models.labelLabel")}
        saveLabel={t("common.save")}
        cancelLabel={t("common.cancel")}
        addDraftLabel={t("aiSettings.models.addLabel")}
        providersEmptyLabel={t("aiSettings.models.providersEmptyLabel")}
      />
      {error ? (
        <div className="p-3 bg-rose-50 text-rose-700 rounded-lg border border-rose-100 text-sm" role="alert">
          {error}
        </div>
      ) : null}
      <ConfirmationModal
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("aiSettings.models.deleteTitle", { name: deleting?.externalId ?? "" })}
        description={t("aiSettings.models.deleteBody")}
        confirmLabel={t("aiSettings.models.deleteConfirm")}
        cancelLabel={t("common.cancel")}
        destructive
        busy={deleteBusy}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
