import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Banknote, Check, House, Loader2, X } from "lucide-react";
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
  SetupAssignments,
  SetupReview,
  SetupSteps,
  type SetupReviewOptions,
} from "@/components/ui";
import type { ModelPickerProvider } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";
import { CAP_ICONS, guessCaps } from "@/components/settings/ReRunSetupDialog";
import { SetupErrorPanel } from "@/components/settings/setupErrors";

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

const DECISION_DEFAULT_TASK_TYPE = "decision";

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

type Phase = "tiles" | "form" | "review" | "done";

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
      .then((rows) => setModels(rows.filter((m) => m.provider_id === provider.id)))
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

export interface ProviderSetupWizardProps {
  canUseSystemScope: boolean;
  configuredKeys: string[];
  /** `modal` keeps the dialog chrome; `page` lets a route own the frame. */
  frame: "modal" | "page";
  /** Manual path: the host opens its own provider form. */
  onManual: () => void;
  onClose?: () => void;
  onSaved: () => void;
  /** Page frame: the review applied — the host continues to its next step. */
  onConfigured?: (result: ProviderSetupResult) => void;
}

/** One-click §15 setup as a reusable flow: preset tiles → guided form →
 * review → done. Composed entirely from the assistant-ui AI-settings kit;
 * hosted by the AI settings modal (dialog frame) and the first-run setup
 * route (page frame). Career delta: the manual path hands off to the
 * app's provider form instead of an in-flow form. */
export function ProviderSetupWizard({
  canUseSystemScope,
  configuredKeys,
  frame,
  onManual,
  onClose,
  onSaved,
  onConfigured,
}: ProviderSetupWizardProps) {
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
  const [reviewOptions, setReviewOptions] = useState<SetupReviewOptions>({
    curatedIds: [],
    bindChat: true,
    bindVision: true,
    bindStt: true,
    bindDecision: true,
  });
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<aiApi.ProviderSetupErrorDetail | null>(null);
  const [applyPlainError, setApplyPlainError] = useState<string | null>(null);
  const [liveAssignments, setLiveAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [modelLabels, setModelLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    if (phase !== "review" || result === null) return;
    const activeScope = result.provider.scope;
    aiApi
      .fetchAssignments(activeScope)
      .then(setLiveAssignments)
      .catch(() => setLiveAssignments([]));
    aiApi
      .fetchAllModels()
      .then((rows) =>
        setModelLabels(Object.fromEntries(rows.map((m) => [m.id, m.name || m.model_name])))
      )
      .catch(() => setModelLabels({}));
  }, [phase, result]);

  useEffect(() => {
    aiApi
      .fetchProviderPresets()
      .then(setPresets)
      .catch(() => setPresets({}));
  }, []);

  const order = TILE_ORDER.filter((key) => key in presets);
  const preset: ProviderPreset | null = presetKey !== null ? (presets[presetKey] ?? null) : null;
  const decisionCandidate =
    preset?.decision_models?.find((entry) => entry.id === preset.decision_default) ?? null;
  const decisionDeclared = decisionCandidate !== null;

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
          options: {
            bind_chat: false,
            bind_vision: false,
            bind_stt: false,
            bind_decision: false,
          },
        });
      }
      setResultName(name.trim() || preset.name || "");
      setResult(data);
      onSaved();
      if (forcedManual) {
        setPhase("done");
        if (frame === "page") onConfigured?.(data);
      } else {
        setReviewOptions({
          curatedIds: preset.curated_models ?? [],
          bindChat: true,
          bindVision: true,
          bindStt: true,
          bindDecision: decisionDeclared,
        });
        setApplyError(null);
        setApplyPlainError(null);
        setPhase("review");
      }
    } catch (err) {
      const detail = apiDetail(err);
      const setupError = apiSetupError(err);
      setError(setupError);
      setPlainError(setupError ? null : detail || String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyReview = async () => {
    if (presetKey === null || preset === null || applying) return;
    setApplying(true);
    setApplyError(null);
    setApplyPlainError(null);
    try {
      const data = await aiApi.setupProviderPreset(presetKey, {
        api_key: preset.local ? null : apiKey.trim() || null,
        name: name.trim() || null,
        scope,
        options: {
          curated_ids: preset.curated_models ? reviewOptions.curatedIds : undefined,
          bind_chat: reviewOptions.bindChat,
          bind_vision: reviewOptions.bindVision,
          bind_stt: reviewOptions.bindStt,
          bind_decision: reviewOptions.bindDecision && decisionDeclared,
        },
      });
      setResult(data);
      onSaved();
      if (frame === "page") {
        onConfigured?.(data);
      } else {
        setPhase("done");
      }
    } catch (err) {
      const setupError = apiSetupError(err);
      setApplyError(setupError);
      setApplyPlainError(setupError ? null : apiDetail(err) || String(err));
    } finally {
      setApplying(false);
    }
  };

  let title = t("aiSettings.setup.title");
  let description = t("aiSettings.setup.modalHint");
  let body: React.ReactNode;

  if (phase === "review" && result && preset) {
    description = t("aiSettings.setup.review.intro", {
      name: resultName || preset.name,
      count: result.catalog_count,
    });
    const wizardSteps = [
      { id: "connect", label: t("aiSettings.setup.step.connect") },
      { id: "defaults", label: t("aiSettings.setup.step.defaults") },
    ];
    const selectedCurated = (preset.curated_models ?? []).filter((id) =>
      reviewOptions.curatedIds.includes(id)
    );
    const preferredId = preset.preferred_model?.id ?? null;
    const textCandidate =
      (preferredId !== null && selectedCurated.includes(preferredId) ? preferredId : null) ??
      selectedCurated.find((id) => guessCaps(id).includes("text")) ??
      selectedCurated[0] ??
      null;
    const visionCandidate =
      (textCandidate !== null && guessCaps(textCandidate).includes("vision") ? textCandidate : null) ??
      selectedCurated.find((id) => guessCaps(id).includes("vision")) ??
      null;
    const sttCandidate =
      preset.stt_model && selectedCurated.includes(preset.stt_model) ? preset.stt_model : null;

    const nowLabel = (taskType: string) => {
      const row = liveAssignments.find((a) => a.task_type === taskType && a.is_active);
      const label = row?.model_id ? (modelLabels[row.model_id] ?? row.model_id) : null;
      return t("aiSettings.setup.review.now", {
        model: label ?? t("aiSettings.setup.review.unset"),
      });
    };
    const fillsLabel = (candidate: string | null, taskType: string) =>
      candidate === null
        ? t("aiSettings.setup.review.noCandidate")
        : `${nowLabel(taskType)} · ${t("aiSettings.setup.review.fills", { model: candidate })}`;

    const assignmentRows = [
      ...(preset.type !== "decision"
        ? [
            {
              id: "chat",
              label: t("aiSettings.setup.slot.chat"),
              sub: fillsLabel(textCandidate, "text"),
              candidate: textCandidate,
              bind: reviewOptions.bindChat,
              set: (next: boolean) =>
                setReviewOptions((current) => ({ ...current, bindChat: next })),
            },
            {
              id: "vision",
              label: t("aiSettings.setup.slot.vision"),
              sub: fillsLabel(visionCandidate, "vision"),
              candidate: visionCandidate,
              bind: reviewOptions.bindVision,
              set: (next: boolean) =>
                setReviewOptions((current) => ({ ...current, bindVision: next })),
            },
            ...(preset.stt_model
              ? [
                  {
                    id: "stt",
                    label: t("aiSettings.setup.slot.stt"),
                    sub: fillsLabel(sttCandidate, "stt"),
                    candidate: sttCandidate,
                    bind: reviewOptions.bindStt,
                    set: (next: boolean) =>
                      setReviewOptions((current) => ({ ...current, bindStt: next })),
                  },
                ]
              : []),
          ]
        : []),
      ...(decisionDeclared
        ? [
            {
              id: "decision",
              label: t("aiSettings.decisionDefaultLabel"),
              sub: fillsLabel(decisionCandidate!.name, DECISION_DEFAULT_TASK_TYPE),
              candidate: decisionCandidate!.name,
              bind: reviewOptions.bindDecision,
              set: (next: boolean) =>
                setReviewOptions((current) => ({ ...current, bindDecision: next })),
            },
          ]
        : []),
    ];

    body = (
      <>
        <SetupSteps
          steps={wizardSteps}
          current={1}
          label={t("aiSettings.setup.step.progress")}
        />

        {(preset.curated_models ?? []).length > 0 ? (
          <section className="space-y-2">
            <div>
              <h3 className="text-sm font-semibold">{t("aiSettings.setup.review.modelsTitle")}</h3>
              <p className="text-xs text-slate-500">{t("aiSettings.setup.review.modelsHint")}</p>
            </div>
            <SetupReview
              models={(preset.curated_models ?? []).map((modelId) => ({
                id: modelId,
                name: modelId,
                caps: guessCaps(modelId),
                selected: reviewOptions.curatedIds.includes(modelId),
              }))}
              slots={[]}
              capIcons={CAP_ICONS}
              modelsLabel={t("aiSettings.setup.review.modelsTitle")}
              footnote={t("aiSettings.setup.review.modelsFootnote")}
              onOptionsChange={(options) =>
                setReviewOptions((current) => ({ ...current, curatedIds: options.curatedIds }))
              }
            />
          </section>
        ) : null}

        <SetupAssignments
          title={t("aiSettings.setup.review.assignmentsTitle")}
          hint={t("aiSettings.setup.review.assignmentsHint")}
          rows={assignmentRows.map((row) => ({
            id: row.id,
            label: row.label,
            hint: row.sub,
            checked: row.bind,
            disabled: row.candidate === null,
            onCheckedChange: row.set,
          }))}
        />

        <SetupErrorPanel error={applyError} plainError={applyPlainError} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" disabled={applying} onClick={() => setPhase("form")}>
            {t("common.back")}
          </Button>
          <Button size="sm" disabled={applying} onClick={() => void applyReview()}>
            {applying ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
            {t("aiSettings.setup.review.apply")}
          </Button>
        </div>
      </>
    );
  } else if (phase === "done" && result) {
    description = t("aiSettings.setup.hint");
    body = (
      <>
        <SuccessPanel result={result} presetName={resultName} scope={scope} />
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      </>
    );
  } else {
    if (phase === "form" && preset) {
      title = t("aiSettings.setup.formTitle", { name: preset.name });
    }
    body = (
      <>
        <SetupSteps
          steps={[
            { id: "connect", label: t("aiSettings.setup.step.connect") },
            { id: "defaults", label: t("aiSettings.setup.step.defaults") },
          ]}
          current={0}
          label={t("aiSettings.setup.step.progress")}
        />
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
              key: presetKey ?? undefined,
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
      </>
    );
  }

  if (frame === "page") {
    return (
      <div className="space-y-4" data-testid="provider-setup-wizard">
        <h2 className="text-base font-semibold text-[var(--as-fg)]">{title}</h2>
        <p className="text-sm text-[var(--as-muted-fg)]">{description}</p>
        {body}
      </div>
    );
  }

  return (
    <ModalShell title={title} description={description} onClose={onClose ?? (() => undefined)}>
      {body}
    </ModalShell>
  );
}

function apiSetupError(err: unknown): aiApi.ProviderSetupErrorDetail | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return aiApi.setupErrorDetail(detail);
}
