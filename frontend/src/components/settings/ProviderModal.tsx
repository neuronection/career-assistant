import { useState } from "react";
import * as aiApi from "@/api/ai";
import type { AIProvider } from "@/api/ai";
import { Button, Modal, ModalContent, ModalHeader, ModalTitle, ModalFooter, ProviderForm, SearchableDropdown } from "@/components/ui";
import { apiDetail } from "@/api/client";

interface ProviderModalProps {
  provider: AIProvider | null;
  canUseSystemScope: boolean;
  mockAllowed: boolean;
  onClose: () => void;
  onSaved: () => void;
}

/** Create/edit provider: type, base URL, key (*** preserves) and scope. */
export function ProviderModal({ provider, canUseSystemScope, mockAllowed, onClose, onSaved }: ProviderModalProps) {
  const [name, setName] = useState(provider?.name ?? "");
  const [providerType, setProviderType] = useState<string>(provider?.provider_type ?? "openai_compatible");
  const [apiBase, setApiBase] = useState(provider?.api_base ?? "https://api.openai.com/v1");
  const [apiKey, setApiKey] = useState("");
  const [scope, setScope] = useState<string>(provider?.scope ?? "user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
          ...(trimmedKey ? { api_key: trimmedKey } : {}),
        });
      } else {
        await aiApi.createProvider({
          name,
          provider_type: providerType as AIProvider["provider_type"],
          api_base: apiBase,
          api_key: trimmedKey || null,
          scope: scope as AIProvider["scope"],
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
          <ModalTitle>{provider ? "Edit provider" : "Add provider"}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <ProviderForm
            name={name}
            onNameChange={setName}
            baseUrl={apiBase}
            onBaseUrlChange={setApiBase}
            apiKey={apiKey}
            onApiKeyChange={setApiKey}
            nameLabel="Name"
            baseUrlLabel="API base URL"
            apiKeyLabel="API key"
            hasStoredKey={Boolean(provider?.api_key)}
            storedKeyLabel="stored — leave empty to keep"
            keyPlaceholder="sk-…"
            error={error}
          >
          <div className="text-sm">
            Type
            <div className="mt-1">
              <SearchableDropdown
                options={[
                  { value: "openai", label: "OpenAI", description: "api.openai.com" },
                  { value: "openai_compatible", label: "OpenAI-compatible", description: "OpenRouter / Ollama / LM Studio" },
                  ...(mockAllowed
                    ? [{ value: "mock", label: "Mock", description: "deterministic offline (dev only)" }]
                    : []),
                ]}
                value={providerType}
                onChange={setProviderType}
              />
            </div>
          </div>
          <div className="text-sm">
            Scope
            <div className="mt-1">
              <SearchableDropdown
                options={[
                  ...(canUseSystemScope ? [{ value: "system", label: "Global (all users)" }] : []),
                  { value: "user", label: "Personal (just me)" },
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
            Cancel
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={busy || name.trim().length < 1}>
            {busy ? "Saving…" : "Save provider"}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
