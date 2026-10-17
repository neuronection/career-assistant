import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import * as extApi from "@/api/extensionSources";
import type {
  ConsentPayload,
  ExtensionCandidate,
  ExtensionInstallView,
  ExtensionSourceView,
} from "@/api/extensionSources";
import { apiDetail } from "@/api/client";
import {
  AddIntegrationSourceDialog,
  ConsentDialog,
  IntegrationSourcesList,
  isExtensionTier,
} from "@/components/ui/integrations";
import type {
  IntegrationCapabilityView,
  IntegrationConsentPayloadView,
  IntegrationExtensionGroupView,
  IntegrationSourceDraft,
  IntegrationSourceRowView,
} from "@/components/ui/integrations";

/**
 * Tools → connectors → extension sources (plan 32 Phase 3 → plan 33
 * Phase B / ADR-0040 D13+D22): app glue over the family kit — source
 * fetch/mapping and the source lifecycle API stay here; the surfaces
 * (sources list, add-from-git dialog, consent dialog) are
 * @neuronection/assistant-ui integrations modules. Consent copy renders
 * VERBATIM from the backend payload through the kit, never authored here.
 */

function mapConsent(payload: ConsentPayload): IntegrationConsentPayloadView {
  return {
    variant: "install",
    extensionId: payload.extensionId,
    version: payload.version,
    tier: isExtensionTier(payload.tier) ? payload.tier : "T1",
    importClass: payload.importClass,
    capabilities: payload.capabilities.map(
      (id) => ({ id }) as IntegrationCapabilityView,
    ),
    provenance: {
      author: payload.provenance.author,
      license: payload.provenance.license,
      repository: payload.provenance.repository,
      description: payload.provenance.description,
    },
    digest: payload.digest,
    disclosure: payload.disclosure,
    disclosureKey: payload.disclosureKey,
  };
}

function mapGroups(installs: ExtensionInstallView[]): IntegrationExtensionGroupView[] {
  const byExtension = new Map<string, ExtensionInstallView[]>();
  for (const install of installs) {
    const rows = byExtension.get(install.extensionId) ?? [];
    rows.push(install);
    byExtension.set(install.extensionId, rows);
  }
  return [...byExtension.entries()].map(([extensionId, rows]) => ({
    extension: {
      id: extensionId,
      name: extensionId,
      version: rows[0]?.version ?? null,
      originClass: rows[0]?.originClass ?? "listed",
      tier: rows[0]?.tier ?? "T1",
      digest: rows[0]?.digest ?? null,
    },
    instances: rows.map((install) => ({
      id: install.id,
      extensionId: install.extensionId,
      name: install.extensionId,
      enabled: install.enabled && install.state !== "removed",
      originClass: install.originClass,
      tier: install.tier,
      lifecycle: install.state,
      parked: install.parked,
      managedBy: install.managedBy,
      digest: install.digest,
      update:
        install.update?.state === "available" || install.update?.state === "digest-drift"
          ? {
              state: install.update.state,
              version: install.update.manifestDiff?.version?.to ?? null,
              ref: install.update.ref ?? null,
              digest: install.update.digest ?? null,
              requiresReconsent: install.update.requiresReconsent === true,
              detail: install.update.detail ?? null,
            }
          : null,
    })),
  }));
}

function mapSource(view: ExtensionSourceView): IntegrationSourceRowView {
  const live = (candidate: ExtensionCandidate) =>
    !view.installs.some(
      (install) =>
        install.extensionId === candidate.extensionId && install.state !== "removed",
    );
  return {
    id: view.id,
    kind: view.kind,
    origin: view.origin,
    status: view.status,
    error: view.error || null,
    refStrategy: view.descriptor.ref?.strategy ?? null,
    refValue: view.descriptor.ref?.value ?? null,
    gitops: view.installs.some((install) => install.managedBy === "gitops"),
    candidates: view.candidates.filter(live).map((candidate) => ({
      extensionId: candidate.extensionId,
      name: candidate.extensionId,
      digest: candidate.digest,
      ref: candidate.ref,
      compatible: candidate.compatible,
      reason: candidate.reason,
      tier: candidate.consent
        ? (isExtensionTier(candidate.consent.tier) ? candidate.consent.tier : "T1")
        : null,
      originClass: "listed",
      consent: candidate.consent ? mapConsent(candidate.consent) : null,
    })),
    groups: mapGroups(view.installs),
  };
}

export function ExtensionSourcesSection() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<ExtensionSourceView[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [consentTarget, setConsentTarget] = useState<{
    sourceId: string;
    candidate: ExtensionCandidate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    try {
      setSources(await extApi.fetchExtensionSources());
    } catch (err) {
      setNotice(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setNotice("");
    try {
      await action();
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const addSource = async (draft: IntegrationSourceDraft) => {
    const descriptor: Record<string, unknown> =
      draft.localPath.trim() !== ""
        ? {
            local: { path: draft.localPath.trim() },
            ref: { strategy: draft.refStrategy, ...(draft.refValue ? { value: draft.refValue } : {}) },
          }
        : {
            url: draft.url.trim(),
            ref: { strategy: draft.refStrategy, ...(draft.refValue ? { value: draft.refValue } : {}) },
          };
    if (draft.subpath.trim() !== "") descriptor.subpath = draft.subpath.trim();
    const token = draft.secretValue?.trim();
    if (token) {
      descriptor.credentials = [{ slot: draft.secretSlot ?? "repo-token" }];
    }
    await run(async () => {
      const created = await extApi.addExtensionSource({
        descriptor,
        secrets: token ? { [draft.secretSlot ?? "repo-token"]: token } : undefined,
      });
      await extApi.syncExtensionSource(created.id);
    });
    setAddOpen(false);
  };

  const install = async () => {
    if (!consentTarget) return;
    const { sourceId, candidate } = consentTarget;
    await run(() => extApi.installExtension(sourceId, candidate.extensionId, true));
    setConsentTarget(null);
  };

  const mapped = useMemo(() => sources.map(mapSource), [sources]);

  return (
    <div className="space-y-3" data-testid="extension-sources-block">
      <h3 className="text-sm font-semibold">
        {t("toolsSettings.connectors.extSources.title")}
      </h3>
      <p className="text-sm text-slate-500">
        {t("toolsSettings.connectors.extSources.hint")}
      </p>

      <IntegrationSourcesList
        sources={mapped}
        busy={busy}
        checkingId={syncingId}
        error={notice || null}
        labels={{
          emptyLabel: t("toolsSettings.connectors.extSources.empty"),
          checkLabel: t("toolsSettings.connectors.extSources.check"),
          removeSourceLabel: t("toolsSettings.connectors.extSources.removeSource"),
          checkAriaLabel: t("toolsSettings.connectors.extSources.check"),
          removeSourceAriaLabel: t("toolsSettings.connectors.extSources.removeSource"),
          gitopsSourceLabel: t("toolsSettings.connectors.extSources.gitops"),
          candidateLabel: t("toolsSettings.connectors.extSources.listed"),
          installLabel: t("toolsSettings.connectors.extSources.consentInstall"),
          incompatibleLabel: t("toolsSettings.connectors.extSources.incompatible"),
          enableAriaLabel: t("toolsSettings.connectors.extSources.enableAria"),
          parkLabel: t("toolsSettings.connectors.extSources.park"),
          restoreLabel: t("toolsSettings.connectors.extSources.restore"),
          tombstoneLabel: t("toolsSettings.connectors.extSources.tombstone"),
          applyUpdateLabel: t("toolsSettings.connectors.extSources.applyUpdate"),
          updateAvailableLabel: t("toolsSettings.connectors.extSources.updateAvailableShort"),
          reconsentRequiredLabel: t("toolsSettings.connectors.extSources.needsReconsent"),
          digestDriftLabel: t("toolsSettings.connectors.extSources.digestDriftShort"),
          gitopsLabel: t("toolsSettings.connectors.extSources.gitops"),
          parkedLabel: t("toolsSettings.connectors.extSources.parked"),
          tombstonedLabel: t("toolsSettings.connectors.extSources.tombstoned"),
          conditionLabels: {
            "needs-config": t("toolsSettings.connectors.extSources.needsConfig"),
            "needs-secret": t("toolsSettings.connectors.sources.needsSecret"),
          },
        }}
        onCheck={(sourceId) => {
          setSyncingId(sourceId);
          setNotice("");
          void extApi
            .syncExtensionSource(sourceId)
            .then((report) => {
              if (!report.ok && report.error) {
                setNotice(`${report.error.code}: ${report.error.detail}`);
              }
            })
            .catch((err) => setNotice(apiDetail(err)))
            .finally(() => {
              setSyncingId(null);
              void refresh();
            });
        }}
        onRemoveSource={(sourceId) => void run(() => extApi.removeExtensionSource(sourceId))}
        onInstallCandidate={(sourceId, candidate) => {
          const raw = sources
            .find((source) => source.id === sourceId)
            ?.candidates.find((row) => row.extensionId === candidate.extensionId);
          if (raw?.consent) {
            setConsentTarget({ sourceId, candidate: raw });
          }
        }}
        onToggleEnabled={(_sourceId, instance, enabled) =>
          void run(() => extApi.setExtensionEnabled(instance.id, enabled))
        }
        onApplyUpdate={(_sourceId, instance) =>
          void run(() => extApi.applyExtensionUpdate(instance.id, true))
        }
        onPark={(_sourceId, instance) => void run(() => extApi.parkExtensionInstall(instance.id))}
        onTombstone={(_sourceId, instance) =>
          void run(() => extApi.tombstoneExtensionInstall(instance.id))
        }
      />

      <button
        type="button"
        className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
        onClick={() => setAddOpen(true)}
        data-testid="add-extension-source"
      >
        {t("toolsSettings.connectors.extSources.add")}
      </button>

      <AddIntegrationSourceDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onSubmit={(draft) => void addSource(draft)}
        busy={busy}
        secretSlot="repo-token"
        labels={{
          title: t("toolsSettings.connectors.extSources.addTitle"),
          urlLabel: t("toolsSettings.connectors.extSources.url"),
          localPathLabel: t("toolsSettings.connectors.extSources.localPath"),
          refStrategyLabel: t("toolsSettings.connectors.extSources.strategy"),
          refValueLabel: t("toolsSettings.connectors.extSources.refValue"),
          subpathLabel: t("toolsSettings.connectors.extSources.subpath"),
          secretLabel: t("toolsSettings.connectors.extSources.token"),
          submitLabel: t("toolsSettings.connectors.extSources.add"),
          cancelLabel: t("toolsSettings.connectors.sources.cancel"),
          closeLabel: t("toolsSettings.connectors.extSources.close"),
          submittingLabel: t("toolsSettings.connectors.extSources.submitting"),
        }}
      />

      <ConsentDialog
        open={consentTarget !== null}
        onOpenChange={(open) => {
          if (!open) setConsentTarget(null);
        }}
        payload={
          consentTarget?.candidate.consent ? mapConsent(consentTarget.candidate.consent) : null
        }
        busy={busy}
        onConsent={() => void install()}
        labels={{
          installTitle: t("toolsSettings.connectors.extSources.consentTitle", {
            id: consentTarget?.candidate.extensionId ?? "",
          }),
          tierLabel: t("toolsSettings.connectors.extSources.fieldTier"),
          versionLabel: t("toolsSettings.connectors.extSources.fieldVersion"),
          authorLabel: t("toolsSettings.connectors.extSources.fieldAuthor"),
          licenseLabel: t("toolsSettings.connectors.extSources.fieldLicense"),
          repositoryLabel: t("toolsSettings.connectors.extSources.fieldRepository"),
          digestLabel: t("toolsSettings.connectors.extSources.fieldDigest"),
          capabilitiesLabel: t("toolsSettings.connectors.extSources.capabilities"),
          confirmLabel: t("toolsSettings.connectors.extSources.consentConfirm"),
          declineLabel: t("toolsSettings.connectors.extSources.decline"),
          closeLabel: t("toolsSettings.connectors.extSources.close"),
        }}
      />
    </div>
  );
}
