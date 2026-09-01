import { useCallback, useEffect, useMemo, useState } from "react";
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

const NO_CATALOG_HINT =
  "This provider type doesn't expose a model catalog — enter the model id manually.";
const EDIT_UNSUPPORTED_HINT =
  "Editing a registered model isn't supported by the API yet — delete it and re-add with the new settings.";

const CAP_ICONS = {
  text: FileText,
  vision: Eye,
  tools: Wrench,
  embeddings: Database,
  audio: AudioLines,
} as const;

const ADD_BATCH = 10;

export function ModelsTab({ providers, canManageGlobal, onChanged }: ModelsTabProps) {
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
    expandedProvider !== null && ["openai", "openai_compatible"].includes(expandedProvider.provider_type);

  useEffect(() => {
    if (expandedProviderId === null || expandedProvider === null) return;
    if (!supportsCatalog) {
      setRemote({ state: "error", error: NO_CATALOG_HINT, models: [], retryable: false });
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

  const handleUpdate = (_model: ModelRegistryModel, _patch: ModelRegistryPatch) => {
    setError(EDIT_UNSUPPORTED_HINT);
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
        caps: guessCaps(model.model_name),
        enabled: model.is_active,
        temperature: model.temperature,
        maxTokens: model.max_tokens,
      })),
    [models],
  );

  const capDescriptors: CapabilityDescriptor[] = AI_CAPS.map((cap) => ({
    value: cap,
    label: cap.charAt(0).toUpperCase() + cap.slice(1),
    icon: CAP_ICONS[cap],
  }));

  return (
    <div className="space-y-4" data-testid="models-tab">
      <p className="text-sm text-slate-500">
        Register the models each provider serves — add them from the provider&rsquo;s live catalog
        or by typing the model id.
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
        capsLabel="Capabilities"
        capsHint="Guessed from the model id — toggle what the model can do."
        addLabel="Add model"
        addAllLabel="Add all"
        addTitle="Add model"
        editTitle="Edit model"
        selectModelLabel="Model"
        manualIdToggleLabel="Enter the model id manually"
        editLabel="Edit"
        removeLabel="Remove"
        missingLabel="Missing"
        searchPlaceholder="Search model catalog…"
        searchLabel="Search model catalog"
        emptyProviderLabel="No models registered yet — use Add model to pick from the catalog or enter an id manually."
        externalIdRequiredLabel="The model id is required."
        remoteEmptyLabel="The provider listed no models."
        remoteLoadingLabel="Loading model catalog…"
        retryLabel="Retry"
        customOptionLabel="Custom…"
        temperatureLabel="Temperature"
        maxTokensLabel="Max tokens"
        labelLabel="Display name"
        saveLabel="Save"
        cancelLabel="Cancel"
        addDraftLabel="Add model"
        providersEmptyLabel="No providers configured yet — add one in the Providers tab first, then register its models here."
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
        title={`Delete model ${deleting?.externalId ?? ""}?`}
        description="Tasks that used this model fall back to their scope default."
        confirmLabel="Delete model"
        cancelLabel="Cancel"
        destructive
        busy={deleteBusy}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
