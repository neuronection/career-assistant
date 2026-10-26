import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { SearchProvider, SearchProviderProbe } from "@/api/ai";
import { apiDetail } from "@/api/client";
import {
  Button,
  ConfirmationModal,
  Modal,
  ModalBody,
  ModalContent,
  ModalHeader,
  ModalTitle,
  WebSearchProviderSettingsForm,
  WebSearchProviderWizard,
  WebSearchProvidersList,
  type WebSearchProviderFormValue,
  type WebSearchProviderSaveInput,
  type WebSearchProviderView,
  type WebSearchProvidersListLabels,
  type WebSearchProviderWizardLabels,
} from "@/components/ui";
import {
  defaultProviderName,
  providerSaveBody,
  searchExtraFields,
  toCardView,
  toCatalogType,
  toProbeView,
  toSearchProviderCatalog,
} from "@/components/settings/searchProviderViews";

interface EditState {
  id: string;
  type: string;
  value: WebSearchProviderFormValue;
}

// Tools → web search (ADR-0033 domain tools.web-search): the family
// multi-provider shape (ADR-0035 / plan 28) rendered through the library
// web-search-providers module — configured instances as ProviderCards with
// every management action in the ⋯ menu, add = tiles → settings-form
// wizard in a modal, edit = the catalog-driven settings form. Career keeps
// persistence, key sealing and the probe calls app-side; the first enabled
// provider that answers wins (card order = fallback priority).

export function WebSearchSection() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<SearchProvider[]>([]);
  const [catalog, setCatalog] = useState<aiApi.SearchProviderCatalog | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [wizardError, setWizardError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditState | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<SearchProvider | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, SearchProviderProbe>>({});

  const refresh = useCallback(async () => {
    try {
      setProviders(await aiApi.listSearchProviders());
    } catch (err) {
      setError(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    aiApi
      .getSearchProviderCatalog()
      .then(setCatalog)
      .catch((err) => setError(apiDetail(err)));
  }, [refresh]);

  const libraryCatalog = useMemo(
    () => (catalog ? toSearchProviderCatalog(catalog) : null),
    [catalog],
  );
  const extraFields = useMemo(
    () =>
      searchExtraFields(catalog?.limits, {
        timeout: t("toolsSettings.webSearch.timeoutLabel"),
        maxResults: t("toolsSettings.webSearch.maxResultsLabel"),
      }),
    [catalog, t],
  );

  const wizardLabels = useMemo<WebSearchProviderWizardLabels>(
    () => ({
      chooseStepLabel: t("toolsSettings.webSearch.stepChoose"),
      configureStepLabel: t("toolsSettings.webSearch.stepConfigure"),
      stepsLabel: t("toolsSettings.webSearch.stepsAria"),
      tilesLabel: t("toolsSettings.webSearch.tilesAria"),
      keyChipLabel: t("toolsSettings.webSearch.chipKey"),
      keylessChipLabel: t("toolsSettings.webSearch.chipKeyless"),
      cloudChipLabel: t("toolsSettings.webSearch.chipCloud"),
      selfHostedChipLabel: t("toolsSettings.webSearch.chipSelfHosted"),
      backLabel: t("toolsSettings.webSearch.back"),
      nameLabel: t("toolsSettings.webSearch.nameLabel"),
      apiKeyLabel: t("toolsSettings.webSearch.key"),
      keyOptionalLabel: t("toolsSettings.webSearch.keyOptional"),
      keyStoredLabel: t("toolsSettings.webSearch.keyStored"),
      noKeyLabel: t("toolsSettings.webSearch.noKeyNeeded"),
      baseUrlLabel: t("toolsSettings.webSearch.baseUrl"),
      baseUrlRequiredLabel: t("toolsSettings.webSearch.baseUrlRequired"),
      advancedLabel: t("toolsSettings.webSearch.advanced"),
      getKeyLabel: t("toolsSettings.webSearch.getKey"),
      saveLabel: t("toolsSettings.webSearch.save"),
      cancelLabel: t("toolsSettings.webSearch.cancel"),
    }),
    [t],
  );

  const listLabels = useMemo<WebSearchProvidersListLabels>(
    () => ({
      emptyLabel: t("toolsSettings.webSearch.empty"),
      orderLabel: (position) => t("toolsSettings.webSearch.priority", { position }),
      disabledBadge: t("toolsSettings.webSearch.disabledBadge"),
      noKeyLabel: t("toolsSettings.webSearch.noKey"),
      keyStoredLabel: t("toolsSettings.webSearch.keyStored"),
      enableLabel: t("toolsSettings.webSearch.enable"),
      disableLabel: t("toolsSettings.webSearch.disable"),
      moveUpLabel: t("toolsSettings.webSearch.moveUp"),
      moveDownLabel: t("toolsSettings.webSearch.moveDown"),
      editLabel: t("toolsSettings.webSearch.edit"),
      deleteLabel: t("toolsSettings.webSearch.delete"),
      testLabel: t("toolsSettings.webSearch.test"),
      idleLabel: t("toolsSettings.webSearch.probeIdle"),
      okLabel: t("toolsSettings.webSearch.probeOk"),
      failLabel: t("toolsSettings.webSearch.probeError"),
      actionsLabel: (name) => t("toolsSettings.webSearch.actionsAria", { name }),
    }),
    [t],
  );

  const entryFor = useCallback(
    (type: string) => catalog?.providers[type],
    [catalog],
  );

  const defaultName = useCallback(
    (type: string) => (catalog ? defaultProviderName(type, catalog, providers) : null),
    [catalog, providers],
  );

  const saveWizard = async (input: WebSearchProviderSaveInput) => {
    setBusy(true);
    setWizardError(null);
    try {
      await aiApi.createSearchProvider(providerSaveBody(input, entryFor(input.type)));
      setAdding(false);
      await refresh();
    } catch (err) {
      setWizardError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const openEdit = (view: WebSearchProviderView) => {
    const full = providers.find((provider) => provider.id === view.id);
    if (!full) return;
    setEditError(null);
    setEditing({
      id: full.id,
      type: toCatalogType(full.type),
      value: {
        name: full.name,
        apiKey: "",
        baseUrl: full.base_url,
        fields: {
          google_cx: full.google_cx ?? "",
          timeout_ms: String(full.timeout_ms ?? ""),
          max_results: String(full.max_results ?? ""),
        },
      },
    });
  };

  const saveEdit = async (value: WebSearchProviderFormValue) => {
    if (!editing) return;
    setBusy(true);
    setEditError(null);
    try {
      await aiApi.updateSearchProvider(
        editing.id,
        providerSaveBody(
          {
            id: editing.id,
            type: editing.type,
            name: value.name,
            baseUrl: value.baseUrl,
            googleCx: value.fields["google_cx"] ?? "",
            apiKey: value.apiKey,
            fields: value.fields,
          },
          entryFor(editing.type),
        ),
      );
      setEditing(null);
      await refresh();
    } catch (err) {
      setEditError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (id: string, enabled: boolean) => {
    setBusy(true);
    setError("");
    try {
      await aiApi.updateSearchProvider(id, { enabled });
      await refresh();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const move = async (id: string, direction: "up" | "down") => {
    setBusy(true);
    setError("");
    try {
      setProviders(await aiApi.moveSearchProvider(id, direction));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (id: string) => {
    setTestingId(id);
    try {
      const result = await aiApi.testSearchProvider(id);
      setProbes((current) => ({ ...current, [id]: result }));
    } catch (err) {
      setProbes((current) => ({
        ...current,
        [id]: {
          status: "error",
          latency_ms: 0,
          result_count: null,
          error: apiDetail(err),
        },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      await aiApi.deleteSearchProvider(id);
      setDeleting(null);
      await refresh();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const editingProvider = editing
    ? providers.find((provider) => provider.id === editing.id) ?? null
    : null;

  return (
    <div className="space-y-4" data-testid="web-search-section">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-slate-500">{t("toolsSettings.webSearch.hint")}</p>
        {!adding && editing === null ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setWizardError(null);
              setAdding(true);
            }}
          >
            <Plus className="w-4 h-4" />
            {t("toolsSettings.webSearch.add")}
          </Button>
        ) : null}
      </div>

      {error ? (
        <p className="text-xs text-red-600" data-testid="web-search-error">
          {error}
        </p>
      ) : null}

      {libraryCatalog ? (
        <WebSearchProvidersList
          providers={providers.map(toCardView)}
          catalog={libraryCatalog}
          probes={Object.fromEntries(
            Object.entries(probes).map(([id, probe]) => [id, toProbeView(probe)]),
          )}
          testingId={testingId}
          busy={busy}
          labels={listLabels}
          onToggle={(id, enabled) => void toggle(id, enabled)}
          onMove={(id, direction) => void move(id, direction)}
          onTest={(id) => void runTest(id)}
          onEdit={openEdit}
          onDelete={(id) =>
            setDeleting(providers.find((provider) => provider.id === id) ?? null)
          }
        />
      ) : null}

      {adding && libraryCatalog ? (
        <Modal open onOpenChange={(open) => { if (!open) setAdding(false); }}>
          <ModalContent size="lg">
            <ModalHeader>
              <ModalTitle>{t("toolsSettings.webSearch.add")}</ModalTitle>
            </ModalHeader>
            <ModalBody className="pb-4">
              <WebSearchProviderWizard
                catalog={libraryCatalog}
                defaultName={defaultName}
                extraFields={extraFields}
                busy={busy}
                error={wizardError}
                labels={wizardLabels}
                onCancel={() => setAdding(false)}
                onSave={(input) => void saveWizard(input)}
              />
            </ModalBody>
          </ModalContent>
        </Modal>
      ) : null}

      {editing && libraryCatalog && entryFor(editing.type) ? (
        <Modal open onOpenChange={(open) => { if (!open) setEditing(null); }}>
          <ModalContent size="lg">
            <ModalHeader>
              <ModalTitle>{t("toolsSettings.webSearch.edit")}</ModalTitle>
            </ModalHeader>
            <ModalBody className="pb-4">
              <WebSearchProviderSettingsForm
                type={editing.type}
                entry={libraryCatalog.entries[editing.type]}
                mode="edit"
                value={editing.value}
                onChange={(value) => setEditing({ ...editing, value })}
                onSubmit={(value) => void saveEdit(value)}
                onCancel={() => setEditing(null)}
                storedKeyHint={editingProvider?.key_hint ?? null}
                error={editError}
                busy={busy}
                extraFields={extraFields}
                labels={wizardLabels}
              />
            </ModalBody>
          </ModalContent>
        </Modal>
      ) : null}

      <ConfirmationModal
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("toolsSettings.webSearch.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("toolsSettings.webSearch.deleteDescription")}
        confirmLabel={t("toolsSettings.webSearch.delete")}
        cancelLabel={t("toolsSettings.webSearch.cancel")}
        destructive
        busy={busy}
        onConfirm={() => {
          if (deleting) void remove(deleting.id);
        }}
      />
    </div>
  );
}
