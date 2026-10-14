import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Database, Eye, Loader2, Mic, Type, Volume2, Wrench, X } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { AIProvider, ProviderPreset, ProviderSetupErrorDetail } from "@/api/ai";
import { Button, SetupReview, type SetupReviewOptions } from "@/components/ui";
import { apiDetail } from "@/api/client";
import { SetupErrorPanel } from "./setupErrors";

// ADR-0036 §3: setup binds the decision DEFAULT slot only (task id
// `decision`); kind slots inherit.
const DECISION_DEFAULT_TASK_TYPE = "decision";

const CAP_ICONS = {
  text: Type,
  vision: Eye,
  tools: Wrench,
  embeddings: Database,
  stt: Mic,
  tts: Volume2,
} as const;

function guessCaps(externalId: string): string[] {
  const id = externalId.toLowerCase();
  if (id.includes("embedding") || id.includes("bge")) return ["embeddings"];
  if (/(whisper|transcribe|stt)/.test(id)) return ["stt"];
  if (/(tts|speech|voice)/.test(id)) return ["tts"];
  const caps = ["text"];
  if (/(4o|gpt-5|vision|vl|claude|gemini|llava|pixtral|gemma3)/.test(id)) caps.push("vision");
  if (/(gpt-4|gpt-5|o3|o4|claude|gemini|deepseek|qwen|llama-3|mistral)/.test(id)) caps.push("tools");
  return caps;
}

/** Re-run one-click setup for an adopted provider: stored-key note,
 * curated cards, fill-empty switches with `now:` values — the five-bind
 * body is emitted here (append semantics, never removes). */
export function ReRunSetupDialog({
  provider,
  onClose,
  onApplied,
}: {
  provider: AIProvider;
  onClose: () => void;
  onApplied: () => void;
}) {
  const { t } = useTranslation();
  const presetKey = provider.preset_key ?? "";
  const [preset, setPreset] = useState<ProviderPreset | null>(null);
  const [assignments, setAssignments] = useState<aiApi.StoredAssignment[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<SetupReviewOptions>({
    curatedIds: [],
    bindChat: true,
    bindVision: true,
    bindStt: true,
    bindDecision: true,
  });
  const [error, setError] = useState<ProviderSetupErrorDetail | null>(null);
  const [plainError, setPlainError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const initialized = useRef(false);

  useEffect(() => {
    aiApi
      .fetchProviderPresets()
      .then((presets) => setPreset(presets[presetKey] ?? null))
      .catch(() => setPreset(null));
    aiApi
      .fetchAssignments(provider.scope)
      .then(setAssignments)
      .catch(() => setAssignments([]));
  }, [presetKey, provider.scope]);

  useEffect(() => {
    if (!initialized.current && preset?.curated_models) {
      initialized.current = true;
      setOptions((current) => ({ ...current, curatedIds: preset.curated_models ?? [] }));
    }
  }, [preset]);

  const assignmentFor = (taskType: string) =>
    assignments.find((a) => a.task_type === taskType && a.is_active);
  const assignmentLabel = (taskType: string) => {
    const row = assignmentFor(taskType);
    if (!row?.model_id) return null;
    return labels[row.model_id] ?? row.model_id;
  };
  useEffect(() => {
    aiApi
      .fetchAllModels()
      .then((rows) =>
        setLabels(Object.fromEntries(rows.map((m) => [m.id, m.name || m.model_name])))
      )
      .catch(() => setLabels({}));
  }, []);

  const decisionDeclared = (preset?.decision_models?.length ?? 0) > 0;
  const bindDecision = decisionDeclared && options.bindDecision;
  const nowLabel = (taskType: string) => {
    const label = assignmentLabel(taskType);
    return t("aiSettings.setup.review.now", {
      model: label ?? t("aiSettings.setup.review.unset"),
    });
  };

  const reviewSlots = [
    {
      id: "chat",
      label: t("aiSettings.setup.review.fillText"),
      bind: options.bindChat,
      currentValue: nowLabel("text"),
      optionsKey: "bindChat" as const,
    },
    {
      id: "vision",
      label: t("aiSettings.setup.review.fillVision"),
      bind: options.bindVision,
      currentValue: nowLabel("vision"),
      optionsKey: "bindVision" as const,
    },
    ...(preset?.stt_model
      ? [
          {
            id: "stt",
            label: t("aiSettings.setup.review.fillStt"),
            bind: options.bindStt,
            currentValue: nowLabel("stt"),
            optionsKey: "bindStt" as const,
          },
        ]
      : []),
    ...(decisionDeclared
      ? [
          {
            id: "decision",
            label: t("aiSettings.setup.review.fillDecision"),
            bind: bindDecision,
            currentValue: nowLabel(DECISION_DEFAULT_TASK_TYPE),
            optionsKey: "bindDecision" as const,
          },
        ]
      : []),
  ];

  const apply = async () => {
    setBusy(true);
    setError(null);
    setPlainError(null);
    try {
      await aiApi.setupProviderPreset(presetKey, {
        api_key: null,
        scope: provider.scope,
        options: {
          curated_ids: preset?.curated_models ? options.curatedIds : undefined,
          bind_chat: options.bindChat,
          bind_vision: options.bindVision,
          bind_stt: options.bindStt,
          bind_decision: bindDecision,
        },
      });
      onApplied();
      onClose();
    } catch (err) {
      const setupError = apiSetupError(err);
      setError(setupError);
      setPlainError(setupError ? null : apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("aiSettings.setup.automatically")}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-xl"
      >
        <div className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <h2 className="text-base font-semibold">{t("aiSettings.setup.automatically")}</h2>
            <Button variant="ghost" size="icon" aria-label={t("common.close")} onClick={onClose}>
              <X className="h-4 w-4" aria-hidden />
            </Button>
          </div>
          <p className="text-sm text-slate-500">
            {t("aiSettings.setup.review.keyNote", { name: provider.name })}
          </p>
          <SetupReview
            models={(preset?.curated_models ?? []).map((modelId) => ({
              id: modelId,
              name: modelId,
              caps: guessCaps(modelId),
              selected: options.curatedIds.includes(modelId),
            }))}
            slots={reviewSlots}
            capIcons={CAP_ICONS}
            modelsLabel={t("aiSettings.setup.review.modelsLabel")}
            footnote={t("aiSettings.setup.review.footnote")}
            onOptionsChange={setOptions}
          />
          <SetupErrorPanel error={error} plainError={plainError} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button size="sm" disabled={busy || !preset} onClick={() => void apply()}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
              {t("aiSettings.setup.review.apply")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function apiSetupError(err: unknown): ProviderSetupErrorDetail | null {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return aiApi.setupErrorDetail(detail);
}
