import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Banknote, Check, House, X } from "lucide-react";
import { COUNTRIES } from "@neuronection/assistant-ui/countries";
import * as aiApi from "@/api/ai";
import type { AIProvider, ProviderPreset, ProviderSetupResult } from "@/api/ai";
import {
  Button,
  ModelPicker,
  ProviderSetupForm,
  ProviderSetupManualTile,
  ProviderSetupTiles,
  SearchableDropdown,
} from "@/components/ui";
import type { ModelPickerProvider } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";

const TILE_ORDER = [
  "openai",
  "gemini",
  "openrouter",
  "typesafe",
  "groq",
  "mistral",
  "deepseek",
  "ollama",
] as const;

// ADR-0036: the decision default slot (task id `decision`).
const DECISION_DEFAULT_TASK_TYPE = "decision";

/**
 * Capability chips for a preset tile (plan 26 §13.3 follow-up): derived
 * from the API preset data — chat type → chat (+ vision where the
 * preferred model carries it, + stt where stt_model exists),
 * decision_models → decision, keyless-local → local. Labels via i18n.
 */
function chipsForPreset(
  preset: aiApi.ProviderPreset,
  t: (key: string) => string,
): { key: string; label: string }[] {
  const chips: { key: string; label: string }[] = [];
  if (preset.type !== "decision") {
    chips.push({ key: "chat", label: t("aiSettings.setup.chipChat") });
    if (preset.preferred_model?.caps.includes("vision")) {
      chips.push({ key: "vision", label: t("aiSettings.setup.chipVision") });
    }
    if (preset.stt_model) {
      chips.push({ key: "stt", label: t("aiSettings.setup.chipStt") });
    }
  }
  if (preset.decision_models && preset.decision_models.length > 0) {
    chips.push({ key: "decision", label: t("aiSettings.setup.chipDecision") });
  }
  if (preset.local) {
    chips.push({ key: "local", label: t("aiSettings.setup.chipLocal") });
  }
  return chips;
}

type Phase = "tiles" | "form" | "done";

function ModalShell({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-xl"
      >
        <div className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <h2 className="text-base font-semibold">{title}</h2>
              <p className="text-xs text-slate-500">{description}</p>
            </div>
            <Button variant="ghost" size="icon" aria-label={t("common.close")} onClick={onClose}>
              <X className="h-4 w-4" aria-hidden />
            </Button>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

function HostingToggle({
  local,
  onChange,
  disabled,
}: {
  local: boolean;
  onChange: (local: boolean) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1">
      <span className="block text-sm text-slate-500">{t("aiSettings.providerModal.hosting")}</span>
      <div className="grid grid-cols-2 gap-2" role="group" aria-label={t("aiSettings.providerModal.hosting")}>
        {(
          [
            [true, t("aiSettings.providerModal.localKind"), House],
            [false, t("aiSettings.providerModal.cloudKind"), Banknote],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={label}
            type="button"
            aria-pressed={local === value}
            disabled={disabled}
            onClick={() => onChange(value)}
            className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
              local === value
                ? "border-primary-600 bg-primary-50 text-primary-700"
                : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CountrySelect({ country, onChange }: { country: string; onChange: (c: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="text-sm">
      {t("aiSettings.providerModal.country")}
      <div className="mt-1">
        <SearchableDropdown
          options={[
            { value: "", label: t("aiSettings.providerModal.countryPlaceholder") },
            ...COUNTRIES.map((entry) => ({ value: entry.code, label: `${entry.flag} ${entry.name}` })),
          ]}
          value={country}
          onChange={onChange}
        />
      </div>
    </div>
  );
}

function ScopeSelect({
  scope,
  onChange,
}: {
  scope: "user" | "system";
  onChange: (scope: "user" | "system") => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="text-sm">
      {t("aiSettings.providerModal.scopeLabel")}
      <div className="mt-1">
        <SearchableDropdown
          options={[
            { value: "system", label: t("aiSettings.providerModal.globalScope") },
            { value: "user", label: t("aiSettings.providerModal.personalScope") },
          ]}
          value={scope}
          onChange={(next) => onChange(next as "user" | "system")}
        />
      </div>
    </div>
  );
}

function SuccessDefaults({
  provider,
  result,
  scope,
}: {
  provider: AIProvider;
  result: ProviderSetupResult;
  scope: "user" | "system";
}) {
  const { t } = useTranslation();
  const [models, setModels] = useState<aiApi.ProviderModelInfo[]>([]);
  const [assignments, setAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    aiApi
      .fetchAllModels()
      .then((rows) => setModels(rows.filter((m) => m.provider_id === provider.id && m.is_active)))
      .catch(() => setModels([]));
    aiApi
      .fetchAssignments(scope)
      .then(setAssignments)
      .catch(() => setAssignments([]));
  }, [provider.id, scope]);

  const catalog: ModelPickerProvider[] = [
    {
      id: provider.id,
      name: provider.name,
      models: models.map((model) => ({
        id: model.id,
        name: model.name || model.model_name,
        capabilities: model.caps ?? [],
      })),
    },
  ];
  const externalToId = new Map(models.map((model) => [model.model_name, model.id]));
  const assignmentFor = (taskType: string) =>
    assignments.find((a) => a.task_type === taskType && a.is_active);

  const decisionModels = models.filter(
    (model) => Boolean(model.decision_transport) || (model.caps ?? []).includes("decision")
  );
  const decisionCatalog: ModelPickerProvider[] =
    decisionModels.length > 0
      ? [
          {
            id: provider.id,
            name: provider.name,
            models: decisionModels.map((model) => ({
              id: model.id,
              name: model.name || model.model_name,
              capabilities: model.caps ?? [],
            })),
          },
        ]
      : [];

  const bind = async (taskType: string, modelId: string) => {
    setError("");
    try {
      await aiApi.setAssignment(taskType, { scope, model_id: modelId });
      const rows = await aiApi.fetchAssignments(scope);
      setAssignments(rows);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const slotValue = (taskType: string, assignedExternal: string | null): string => {
    const fromExternal = assignedExternal ? externalToId.get(assignedExternal) : undefined;
    if (fromExternal !== undefined) return fromExternal;
    return assignmentFor(taskType)?.model_id ?? "";
  };

  const hasCap = (cap: string) => models.some((model) => (model.caps ?? []).includes(cap));
  const rows = [
    { taskType: "text", labelKey: "aiSettings.setup.slot.chat", assigned: result.assigned_chat_model },
    ...(hasCap("vision")
      ? [
          {
            taskType: "vision",
            labelKey: "aiSettings.setup.slot.vision",
            assigned: result.assigned_vision_model,
          },
        ]
      : []),
    ...(hasCap("stt")
      ? [
          {
            taskType: "stt",
            labelKey: "aiSettings.setup.slot.stt",
            assigned: result.assigned_stt_model,
          },
        ]
      : []),
  ];
  // ADR-0036 §3: setup binds the `decision` default slot only — one
  // assignment, one review row; the kind slots inherit.
  const decisionRows = decisionModels.length > 0
    ? [
        {
          taskType: DECISION_DEFAULT_TASK_TYPE,
          labelKey: 'aiSettings.decisionDefaultLabel',
          assigned: result.assigned_decision_slots?.[DECISION_DEFAULT_TASK_TYPE] ?? null,
        },
      ]
    : [];

  if (models.length === 0) {
    return <p className="text-xs text-slate-500">{t("aiSettings.setup.noDefaults")}</p>;
  }

  return (
    <div className="space-y-2 rounded-md border border-slate-200 p-3">
      <h3 className="text-sm font-semibold">{t("aiSettings.tasks.defaultModelsTitle")}</h3>
      {rows.map((row) => (
        <ModelPicker
          key={row.taskType}
          providers={catalog}
          value={slotValue(row.taskType, row.assigned)}
          onChange={(modelId) => {
            if (modelId) void bind(row.taskType, modelId);
          }}
          clearable={false}
          label={t(row.labelKey)}
        />
      ))}
      {decisionRows.map((row) => (
        <ModelPicker
          key={row.taskType}
          providers={decisionCatalog}
          value={slotValue(row.taskType, row.assigned)}
          onChange={(modelId) => {
            if (modelId) void bind(row.taskType, modelId);
          }}
          clearable={false}
          label={t(row.labelKey)}
        />
      ))}
      {error ? <p className="text-xs text-rose-600">{error}</p> : null}
    </div>
  );
}

function SuccessPanel({
  result,
  presetName,
  scope,
}: {
  result: ProviderSetupResult;
  presetName: string;
  scope: "user" | "system";
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-2 text-sm font-medium">
        <Check className="h-4 w-4 text-emerald-600" aria-hidden />
        {t("aiSettings.setup.done", { name: presetName })}
      </p>
      <p className="text-xs text-slate-500">
        {t("aiSettings.setup.modelsPersisted", { count: result.catalog_count })}
      </p>
      {result.curated_missed ? (
        <p className="text-xs text-amber-600">{t("aiSettings.setup.curatedMissed")}</p>
      ) : null}
      <SuccessDefaults provider={result.provider} result={result} scope={scope} />
    </div>
  );
}

interface ProviderSetupModalProps {
  canUseSystemScope: boolean;
  configuredKeys: string[];
  onClose: () => void;
  /** "Set up manually" hands off to the full create/edit modal. */
  onManual: () => void;
  onSaved: () => void;
}

/** One-click §15 setup (family assembly): preset tiles → guided form →
 * success panel with per-slot rebind pickers. Career delta: the manual
 * path hands off to the existing ProviderModal instead of an in-modal
 * form — career already ships that surface. */
export function ProviderSetupModal({
  canUseSystemScope,
  configuredKeys,
  onClose,
  onManual,
  onSaved,
}: ProviderSetupModalProps) {
  const { t } = useTranslation();
  const [presets, setPresets] = useState<Record<string, ProviderPreset>>({});
  const [phase, setPhase] = useState<Phase>("tiles");
  const [presetKey, setPresetKey] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [advancedBase, setAdvancedBase] = useState("");
  const [isLocal, setIsLocal] = useState(false);
  const [country, setCountry] = useState("");
  const [scope, setScope] = useState<"user" | "system">("user");
  const [error, setError] = useState<aiApi.ProviderSetupErrorDetail | null>(null);
  const [plainError, setPlainError] = useState<string | null>(null);
  const [result, setResult] = useState<ProviderSetupResult | null>(null);
  const [resultName, setResultName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    aiApi
      .fetchProviderPresets()
      .then(setPresets)
      .catch(() => setPresets({}));
  }, []);

  const order = TILE_ORDER.filter((key) => key in presets);
  const preset: ProviderPreset | null = presetKey !== null ? (presets[presetKey] ?? null) : null;

  const openForm = (key: string) => {
    setPresetKey(key);
    setName("");
    setApiKey("");
    setAdvancedBase(presets[key]?.base_url ?? "");
    setIsLocal(presets[key]?.local ?? false);
    setCountry("");
    setScope("user");
    setError(null);
    setPlainError(null);
    setPhase("form");
  };

  const backToTiles = () => {
    setPhase("tiles");
    setPresetKey(null);
    setError(null);
    setPlainError(null);
  };

  const baseEdited =
    preset !== null &&
    !preset.fixed_base &&
    advancedBase.trim() !== "" &&
    advancedBase.trim() !== preset.base_url;
  const forcedManual =
    preset !== null && (baseEdited || (!preset.local && isLocal) || country.trim() !== "");

  const connect = async () => {
    if (preset === null || presetKey === null) return;
    setBusy(true);
    setError(null);
    setPlainError(null);
    try {
      let data: ProviderSetupResult;
      if (forcedManual) {
        const provider = await aiApi.createProvider({
          name: name.trim() || preset.name,
          provider_type: preset.type as AIProvider["provider_type"],
          api_base: preset.fixed_base ? preset.base_url : advancedBase.trim() || preset.base_url,
          api_key: apiKey.trim() || null,
          scope,
          is_local: isLocal,
          country: country.trim() || null,
        });
        data = {
          ok: true,
          provider,
          catalog_count: 0,
          curated_missed: false,
          assigned_chat_model: null,
          assigned_vision_model: null,
          assigned_stt_model: null,
          assigned_decision_slots: null,
        };
      } else {
        data = await aiApi.setupProviderPreset(presetKey, {
          api_key: preset.local ? null : apiKey.trim() || null,
          name: name.trim() || null,
          scope,
        });
      }
      setResultName(name.trim() || preset.name || "");
      setResult(data);
      setPhase("done");
      onSaved();
    } catch (err) {
      const detail = apiDetail(err);
      const setupError = apiSetupError(err);
      setError(setupError);
      setPlainError(setupError ? null : detail || String(err));
    } finally {
      setBusy(false);
    }
  };

  if (phase === "done" && result) {
    return (
      <ModalShell
        title={t("aiSettings.setup.title")}
        description={t("aiSettings.setup.hint")}
        onClose={onClose}
      >
        <SuccessPanel result={result} presetName={resultName} scope={scope} />
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      </ModalShell>
    );
  }

  return (
    <ModalShell
      title={
        phase === "form" && preset
          ? t("aiSettings.setup.formTitle", { name: preset.name })
          : t("aiSettings.setup.title")
      }
      description={t("aiSettings.setup.modalHint")}
      onClose={onClose}
    >
      {phase === "tiles" ? (
        <ProviderSetupTiles
          presets={order.map((key) => {
            const presetTile = presets[key];
            if (!presetTile) return { key, name: key };
            return { key, name: presetTile.name, chips: chipsForPreset(presetTile, t) };
          })}
          configured={configuredKeys}
          onSelect={openForm}
          label={t("aiSettings.setup.title")}
          localLabel={t("aiSettings.setup.local")}
        >
          <ProviderSetupManualTile onClick={onManual}>
            {t("aiSettings.setup.custom")}
          </ProviderSetupManualTile>
        </ProviderSetupTiles>
      ) : null}

      {phase === "form" && preset ? (
        <ProviderSetupForm
          preset={{
            name: preset.name,
            keyUrl: preset.key_url ?? undefined,
            steps: preset.steps ?? undefined,
            freeTierNote: preset.free_tier_note ?? undefined,
            fixedBase: preset.fixed_base,
            baseUrl: preset.base_url,
            local: preset.local,
          }}
          value={{ name, apiKey, baseUrl: advancedBase }}
          onChange={(value) => {
            setName(value.name);
            setApiKey(value.apiKey);
            setAdvancedBase(value.baseUrl ?? "");
          }}
          testing={busy}
          error={
            error
              ? { code: error.code, suspectedVendor: error.suspected_vendor ?? null }
              : plainError
                ? { code: "unknown" }
                : null
          }
          errorLabels={Object.fromEntries(
            ["invalid_key", "insufficient_credit", "new_user_quota", "region_unavailable", "timeout", "local_not_running", "unknown"].map(
              (code) => [code, t(`aiSettings.setup.errors.${code}`)]
            )
          )}
          suspectedVendorHint={t("aiSettings.setup.errors.suspectedVendor", {
            vendor: error?.suspected_vendor ?? "",
          })}
          advancedExtra={
            <>
              <HostingToggle local={isLocal} onChange={setIsLocal} disabled={preset.local} />
              <CountrySelect country={country} onChange={setCountry} />
              {canUseSystemScope && <ScopeSelect scope={scope} onChange={setScope} />}
            </>
          }
          copyLabel={t("common.copy")}
          getKeyLabel={t("aiSettings.setup.getKey")}
          nameLabel={t("aiSettings.setup.connectionName")}
          apiKeyLabel={t("aiSettings.providerModal.apiKeyLabel")}
          noKeyLabel={t("aiSettings.setup.noKeyNeeded")}
          advancedLabel={t("aiSettings.setup.advanced")}
          baseUrlLabel={t("aiSettings.providerModal.baseUrlLabel")}
          baseUrlHint={t("aiSettings.setup.baseEditHint")}
          submitLabel={t("aiSettings.setup.automatically")}
          cancelLabel={t("aiSettings.setup.chooseAnother")}
          onSubmit={() => void connect()}
          onCancel={backToTiles}
        />
      ) : null}
    </ModalShell>
  );
}

function apiSetupError(err: unknown): aiApi.ProviderSetupErrorDetail | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return aiApi.setupErrorDetail(detail);
}
