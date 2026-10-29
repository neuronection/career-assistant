import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeft, BookOpen, KeyRound, Lock } from "lucide-react";
import {
  Button,
  Modal,
  ModalBody,
  ModalContent,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import {
  IntegrationConfigForm,
  parseIntegrationConfigSchema,
} from "@/components/ui/integrations";
import type {
  IntegrationConfigSchema,
  IntegrationConfigValues,
} from "@/components/ui/integrations";
import { StepperRow, SelectField } from "@/features/cv/components/cv/formPrimitives";
import type { ConnectorCatalogEntry } from "@/api/sources";

export interface SourceWizardDraft {
  id: string | null;
  key: string;
  connector_key: string;
  config: IntegrationConfigValues;
  query_mode: string;
  query_batch_size: number;
}

/** Tools → connectors → add-source wizard (plan 148 phase 2): step 1
 * picks the connector from catalog tiles, step 2 hosts the kit
 * IntegrationConfigForm (values + sealed secret slots) plus the radar
 * query-mode fields. Replaces the old inline raw form. Testids:
 * `job-source-form`, `source-tile-{key}`, `job-source-key`,
 * `job-source-query-mode`. */
export function AddSourceWizard({
  catalog,
  existingKeys,
  busy,
  error,
  secretSlots,
  managedSchema,
  radarCapable,
  queryInfoNote,
  onPick,
  onDraftChange,
  onSave,
  onCancel,
  onDocs,
  onBack,
  draft,
}: {
  catalog: ConnectorCatalogEntry[];
  existingKeys: string[];
  busy: boolean;
  error: string | null;
  secretSlots: Record<string, { set: boolean; hint: string | null }>;
  managedSchema: IntegrationConfigSchema | null;
  radarCapable: boolean;
  queryInfoNote: string;
  draft: SourceWizardDraft;
  onPick: (connector: ConnectorCatalogEntry) => void;
  onDraftChange: (draft: SourceWizardDraft) => void;
  onSave: (secrets: Record<string, string>) => void;
  onCancel: () => void;
  onDocs: (connectorKey: string) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const entry = useMemo(
    () => catalog.find((row) => row.key === draft.connector_key),
    [catalog, draft.connector_key]
  );
  const fields = useMemo(() => {
    const schema = managedSchema ?? entry?.config_schema ?? null;
    const parsed = schema
      ? parseIntegrationConfigSchema(schema as IntegrationConfigSchema)
      : [];
    if (draft.query_mode !== "radar") return parsed;
    return parsed.map((field) =>
      field.name === "keywords" || field.name === "location"
        ? { ...field, required: false }
        : field
    );
  }, [managedSchema, entry, draft.query_mode]);
  const keyTaken =
    draft.key.trim() !== "" &&
    existingKeys.includes(draft.key.trim()) &&
    draft.id === null;

  return (
    <Modal open onOpenChange={(open) => (!open ? onCancel() : undefined)}>
      <ModalContent size="lg" data-testid="job-source-form">
        <ModalHeader>
          <ModalTitle>
            {draft.id
              ? t("toolsSettings.connectors.sources.editTitle", {
                  key: draft.key,
                })
              : t("toolsSettings.connectors.sources.addTitle")}
          </ModalTitle>
        </ModalHeader>
        <ModalBody>
          {!draft.id && draft.connector_key && entry ? (
            <Button
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={onBack}
              data-testid="job-source-back"
            >
              <ArrowLeft className="h-3.5 w-3.5" />{" "}
              {t("toolsSettings.connectors.sources.backToConnectors")}
            </Button>
          ) : null}

          {!entry ? (
            <div className="grid gap-2 sm:grid-cols-2" data-testid="source-tiles">
              {catalog.map((connector) => {
                const needsSecret = connector.secret_fields.length > 0;
                return (
                  <button
                    key={connector.key}
                    type="button"
                    onClick={() => onPick(connector)}
                    data-testid={`source-tile-${connector.key}`}
                    className="flex flex-col gap-1 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-3 text-left transition-colors hover:border-[var(--as-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
                  >
                    <span className="flex items-center gap-1.5 text-sm font-semibold text-[var(--as-fg)]">
                      {connector.title}
                    </span>
                    <span className="flex flex-wrap items-center gap-1">
                      {connector.builtin ? (
                        <span className="rounded-full bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)]">
                          {t("toolsSettings.connectors.sources.builtin")}
                        </span>
                      ) : null}
                      {needsSecret ? (
                        <span className="inline-flex items-center gap-0.5 rounded-full bg-[color-mix(in_srgb,var(--as-warning)_18%,transparent)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-fg)]">
                          <KeyRound className="h-2.5 w-2.5" aria-hidden />
                          {t("toolsSettings.connectors.sources.needsSecretTile")}
                        </span>
                      ) : null}
                      {connector.capabilities?.dynamic_queries ? (
                        <span className="rounded-full bg-[color-mix(in_srgb,var(--as-primary)_10%,transparent)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-primary)]">
                          {t("toolsSettings.connectors.sources.radarCapable")}
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--as-fg)]">
                    {entry.title}
                  </span>
                  <Lock className="h-3 w-3 text-[var(--as-muted-fg)]" aria-hidden />
                  <span className="text-[11px] text-[var(--as-muted-fg)]">
                    {t("toolsSettings.connectors.sources.sealedNote")}
                  </span>
                  {entry.manifest?.docs ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      data-testid={`wizard-docs-${entry.key}`}
                      onClick={() => onDocs(entry.key)}
                    >
                      <BookOpen className="h-3.5 w-3.5" />
                      {t("toolsSettings.connectors.docs.open", "Docs")}
                    </Button>
                  ) : null}
                </div>
              </div>

              <label className="block text-xs text-[var(--as-muted-fg)]">
                {t("toolsSettings.connectors.sources.key")}
                <input
                  className="mt-1 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
                  placeholder={t("toolsSettings.connectors.sources.keyPlaceholder")}
                  value={draft.key}
                  disabled={draft.id !== null}
                  onChange={(event) =>
                    onDraftChange({ ...draft, key: event.target.value })
                  }
                  data-testid="job-source-key"
                  aria-invalid={keyTaken}
                />
              </label>
              {keyTaken ? (
                <p className="text-xs text-[var(--as-danger)]">
                  {t("toolsSettings.connectors.sources.keyTaken")}
                </p>
              ) : null}

              {radarCapable ? (
                <div className="space-y-2">
                  <SelectField
                    label={t("toolsSettings.connectors.sources.queryMode")}
                    value={draft.query_mode}
                    onChange={(query_mode) =>
                      onDraftChange({ ...draft, query_mode })
                    }
                    options={[
                      {
                        value: "static",
                        label: t("toolsSettings.connectors.sources.queryModeStatic"),
                      },
                      {
                        value: "radar",
                        label: t("toolsSettings.connectors.sources.queryModeRadar"),
                      },
                    ]}
                    testId="job-source-query-mode"
                  />
                  <StepperRow
                    label={t("toolsSettings.connectors.sources.queryBatch")}
                    value={draft.query_batch_size}
                    min={1}
                    max={3}
                    onChange={(query_batch_size) =>
                      onDraftChange({ ...draft, query_batch_size })
                    }
                  />
                  {queryInfoNote ? (
                    <p
                      className="text-xs text-[var(--as-muted-fg)]"
                      data-testid="job-source-query-info"
                    >
                      {queryInfoNote}
                    </p>
                  ) : null}
                </div>
              ) : null}

              <IntegrationConfigForm
                fields={fields}
                values={draft.config}
                onValuesChange={(values) => onDraftChange({ ...draft, config: values })}
                onSave={({ secrets }) => onSave(secrets)}
                busy={busy || keyTaken}
                error={error}
                secretSlots={secretSlots}
                conditions={[]}
                labels={{
                  submitLabel: t("toolsSettings.connectors.sources.save"),
                  cancelLabel: t("toolsSettings.connectors.sources.cancel"),
                  secretSetLabel: t("toolsSettings.connectors.sources.secretSetShort"),
                  secretHintLabel: t(
                    "toolsSettings.connectors.sources.secretMissingShort"
                  ),
                  enumPlaceholder: t("toolsSettings.connectors.sources.select"),
                }}
                onCancel={onCancel}
              />
            </div>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
