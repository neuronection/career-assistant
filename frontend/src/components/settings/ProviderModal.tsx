import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CUSTOM_PRESET_KEY, type ProviderPresetOption } from "@neuronection/assistant-ui";
import { COUNTRIES } from "@neuronection/assistant-ui/countries";
import * as aiApi from "@/api/ai";
import type { AIProvider, ProviderPreset } from "@/api/ai";
import { Button, Modal, ModalContent, ModalHeader, ModalTitle, ModalFooter, ProviderForm, SearchableDropdown } from "@/components/ui";
import { apiDetail } from "@/api/client";

interface ProviderModalProps {
  provider: AIProvider | null;
  canUseSystemScope: boolean;
  mockAllowed: boolean;
  onClose: () => void;
  onSaved: () => void;
}

const CUSTOM = CUSTOM_PRESET_KEY;

/** Create/edit provider: preset catalog, type, base URL, key (*** preserves),
 * hosting + country and scope. */
export function ProviderModal({ provider, canUseSystemScope, mockAllowed, onClose, onSaved }: ProviderModalProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(provider?.name ?? "");
  const [providerType, setProviderType] = useState<string>(provider?.provider_type ?? "openai");
  const [apiBase, setApiBase] = useState(provider?.api_base ?? "https://api.openai.com/v1");
  const [apiKey, setApiKey] = useState("");
  const [scope, setScope] = useState<string>(provider?.scope ?? "user");
  const [isLocal, setIsLocal] = useState<boolean>(provider?.is_local ?? false);
  const [country, setCountry] = useState<string>(provider?.country ?? "");
  const [presets, setPresets] = useState<Record<string, ProviderPreset>>({});
  const [presetKey, setPresetKey] = useState<string>(CUSTOM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    aiApi
      .fetchProviderPresets()
      .then(setPresets)
      .catch(() => setPresets({}));
  }, []);

  const presetOptions: ProviderPresetOption[] = Object.entries(presets).map(([key, preset]) => ({
    key,
    name: preset.name,
    local: preset.local,
  }));

  const applyPreset = (key: string) => {
    setPresetKey(key);
    if (key === CUSTOM) return;
    const preset = presets[key];
    if (!preset) return;
    setName(preset.name);
    setApiBase(preset.base_url);
    setProviderType(preset.type);
    setIsLocal(preset.local);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    const trimmedKey = apiKey.trim();
    try {
      if (provider) {
        await aiApi.updateProvider(provider.id, {
          name,
          provider_type: providerType as AIProvider["provider_type"],
          api_base: apiBase,
          scope: scope as AIProvider["scope"],
          is_local: isLocal,
          country: country.trim() || null,
          ...(trimmedKey ? { api_key: trimmedKey } : {}),
        });
      } else {
        await aiApi.createProvider({
          name,
          provider_type: providerType as AIProvider["provider_type"],
          api_base: apiBase,
          api_key: trimmedKey || null,
          scope: scope as AIProvider["scope"],
          is_local: isLocal,
          country: country.trim() || null,
        });
      }
      onSaved();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onOpenChange={(o) => !o && onClose()}>
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>
            {provider ? t("aiSettings.providerModal.editTitle") : t("aiSettings.providerModal.addTitle")}
          </ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <ProviderForm
            presets={presetOptions}
            presetKey={presetKey}
            onPresetChange={applyPreset}
            presetLabel={t("aiSettings.providerModal.presetLabel")}
            customPresetLabel={t("aiSettings.providerModal.customPreset")}
            name={name}
            onNameChange={setName}
            baseUrl={apiBase}
            onBaseUrlChange={setApiBase}
            apiKey={apiKey}
            onApiKeyChange={setApiKey}
            nameLabel={t("aiSettings.providerModal.nameLabel")}
            baseUrlLabel={t("aiSettings.providerModal.baseUrlLabel")}
            apiKeyLabel={t("aiSettings.providerModal.apiKeyLabel")}
            hasStoredKey={Boolean(provider?.api_key)}
            storedKeyLabel={t("aiSettings.providerModal.storedKeyLabel")}
            keyPlaceholder="sk-…"
            showLocationKind
            locationKind={isLocal ? "local" : "cloud"}
            onLocationKindChange={(kind) => setIsLocal(kind === "local")}
            locationLabel={t("aiSettings.providerModal.hosting")}
            localLabel={t("aiSettings.providerModal.localKind")}
            cloudLabel={t("aiSettings.providerModal.cloudKind")}
            showCountry
            country={country}
            onCountryChange={setCountry}
            countryLabel={t("aiSettings.providerModal.country")}
            countryPlaceholder={t("aiSettings.providerModal.countryPlaceholder")}
            countryOptions={COUNTRIES.map((entry) => ({
              value: entry.code,
              label: `${entry.flag} ${entry.name}`,
            }))}
            error={error}
          >
          <div className="text-sm">
            {t("aiSettings.providerModal.typeLabel")}
            <div className="mt-1">
              <SearchableDropdown
                options={[
                  { value: "openai", label: "OpenAI", description: "api.openai.com" },
                  { value: "google", label: "Google Gemini", description: "generativelanguage.googleapis.com" },
                  { value: "openai_compatible", label: "OpenAI-compatible", description: "OpenRouter / Ollama / LM Studio" },
                  ...(mockAllowed
                    ? [{ value: "mock", label: "Mock", description: t("aiSettings.providerModal.mockDescription") }]
                    : []),
                ]}
                value={providerType}
                onChange={setProviderType}
              />
            </div>
          </div>
          <div className="text-sm">
            {t("aiSettings.providerModal.scopeLabel")}
            <div className="mt-1">
              <SearchableDropdown
                options={[
                  ...(canUseSystemScope
                    ? [{ value: "system", label: t("aiSettings.providerModal.globalScope") }]
                    : []),
                  { value: "user", label: t("aiSettings.providerModal.personalScope") },
                ]}
                value={scope}
                onChange={setScope}
              />
            </div>
          </div>
          </ProviderForm>
        </div>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={busy || name.trim().length < 1}>
            {busy ? t("common.saving") : t("aiSettings.providerModal.saveProvider")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
