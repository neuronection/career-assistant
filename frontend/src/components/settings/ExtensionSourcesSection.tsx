import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import * as extApi from "@/api/extensionSources";
import type {
  ConsentPayload,
  ExtensionCandidate,
  ExtensionInstallView,
  ExtensionSourceView,
} from "@/api/extensionSources";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";

/**
 * Tools → connectors → extension sources (plan 32 Phase 3 / ADR-0040
 * D13+D22): the git import layer — add-from-git form, per-source
 * candidates with their consent payloads, digest-pinned installs with
 * origin chips (imported — never rendered as official), update state and
 * park/tombstone affordances. Local-first UI: the shared panel shape is
 * pending in @neuronection/assistant-ui (extension-sources) — swap after
 * the owner publishes; the consent copy renders VERBATIM from the
 * backend payload, never authored here.
 */

type Draft = {
  url: string;
  localPath: string;
  strategy: "release-tag" | "tag-pattern" | "branch" | "commit-pin";
  refValue: string;
  subpath: string;
  token: string;
};

type ConsentTarget = {
  sourceId: string;
  candidate: ExtensionCandidate;
};

const EMPTY_DRAFT: Draft = {
  url: "",
  localPath: "",
  strategy: "release-tag",
  refValue: "",
  subpath: "",
  token: "",
};

function shortDigest(digest: string): string {
  return digest ? `${digest.slice(0, 12)}…` : "";
}

function ConsentDisclosure({ payload }: { payload: ConsentPayload }) {
  const { t } = useTranslation();
  return (
    <div
      className="border-amber-300 bg-amber-50 space-y-2 rounded-md border p-3"
      data-testid="consent-disclosure"
    >
      <p className="text-sm font-semibold">
        {t("toolsSettings.connectors.extSources.consentTitle", {
          id: payload.extensionId ?? "",
        })}
      </p>
      <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
        <div>
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldTier")}
          </dt>
          <dd>
            {payload.tier} · {payload.importClass}
          </dd>
        </div>
        <div>
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldVersion")}
          </dt>
          <dd>{payload.version}</dd>
        </div>
        <div>
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldAuthor")}
          </dt>
          <dd>{payload.provenance.author}</dd>
        </div>
        <div>
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldLicense")}
          </dt>
          <dd>{payload.provenance.license}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldRepository")}
          </dt>
          <dd className="break-all">{payload.provenance.repository ?? "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="font-medium">
            {t("toolsSettings.connectors.extSources.fieldDigest")}
          </dt>
          <dd className="font-mono break-all" data-testid="consent-digest">
            {payload.digest}
          </dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-1" data-testid="consent-capabilities">
        {payload.capabilities.map((capability) => (
          <span
            key={capability}
            className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] text-slate-700"
          >
            {capability}
          </span>
        ))}
      </div>
      <p className="border-l-amber-500 text-xs text-slate-700 border-l-4 pl-2">
        {payload.disclosure}
      </p>
    </div>
  );
}

function InstallRow({
  install,
  busy,
  onEnable,
  onApply,
  onPark,
  onTombstone,
}: {
  install: ExtensionInstallView;
  busy: boolean;
  onEnable: (install: ExtensionInstallView, enabled: boolean) => void;
  onApply: (install: ExtensionInstallView) => void;
  onPark: (install: ExtensionInstallView) => void;
  onTombstone: (install: ExtensionInstallView) => void;
}) {
  const { t } = useTranslation();
  const update = install.update ?? {};
  const updateState = update.state ?? "";
  return (
    <div
      className="border-slate-200 space-y-1 rounded-md border p-2"
      data-testid={`extension-install-${install.extensionId}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-2 font-medium">
          <input
            type="checkbox"
            checked={install.enabled}
            aria-label={t("toolsSettings.connectors.extSources.enabledAria", {
              id: install.extensionId,
            })}
            onChange={(event) => onEnable(install, event.target.checked)}
          />
          {install.extensionId}
        </label>
        <span
          className="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-white"
          data-testid="origin-chip"
        >
          {install.originClass}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
          {install.tier}
        </span>
        <span className="font-mono text-xs text-slate-500">
          {shortDigest(install.digest)}
        </span>
        {install.managedBy === "gitops" ? (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] text-blue-700">
            gitops
          </span>
        ) : null}
        {install.parked ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">
            {t("toolsSettings.connectors.extSources.parked")}
          </span>
        ) : null}
        {install.state === "removed" ? (
          <span className="rounded-full bg-slate-300 px-2 py-0.5 text-[11px] text-slate-700">
            {t("toolsSettings.connectors.extSources.tombstoned")}
          </span>
        ) : null}
      </div>
      {updateState === "available" ? (
        <p className="text-xs text-blue-700" data-testid="update-available">
          {t("toolsSettings.connectors.extSources.updateAvailable", {
            version: update.manifestDiff?.version?.to ?? update.digest?.slice(0, 12) ?? "",
          })}
          {update.requiresReconsent
            ? ` — ${t("toolsSettings.connectors.extSources.needsReconsent")}`
            : ""}
        </p>
      ) : null}
      {updateState === "digest-drift" ? (
        <p className="text-xs text-red-600" data-testid="digest-drift">
          {t("toolsSettings.connectors.extSources.digestDrift", {
            ref: update.ref ?? install.pinRef,
          })}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {updateState === "available" ? (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => onApply(install)}
            data-testid={`apply-update-${install.extensionId}`}
          >
            {t("toolsSettings.connectors.extSources.applyUpdate")}
          </Button>
        ) : null}
        {install.state !== "removed" ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onPark(install)}
              data-testid={`park-${install.extensionId}`}
            >
              {t("toolsSettings.connectors.extSources.park")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onTombstone(install)}
              data-testid={`tombstone-${install.extensionId}`}
            >
              <Trash2 className="h-4 w-4" />
              {t("toolsSettings.connectors.extSources.tombstone")}
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}

export function ExtensionSourcesSection() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<ExtensionSourceView[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [consentTarget, setConsentTarget] = useState<ConsentTarget | null>(null);
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

  const add = async () => {
    if (!draft) return;
    const descriptor: Record<string, unknown> =
      draft.localPath.trim() !== ""
        ? {
            local: { path: draft.localPath.trim() },
            ref: { strategy: draft.strategy, ...(draft.refValue ? { value: draft.refValue } : {}) },
          }
        : {
            url: draft.url.trim(),
            ref: { strategy: draft.strategy, ...(draft.refValue ? { value: draft.refValue } : {}) },
          };
    if (draft.subpath.trim() !== "") descriptor.subpath = draft.subpath.trim();
    const secrets = draft.token.trim() !== "" ? { "repo-token": draft.token.trim() } : undefined;
    if (secrets) descriptor.credentials = [{ slot: "repo-token" }];
    await run(async () => {
      const created = await extApi.addExtensionSource({ descriptor, secrets });
      await extApi.syncExtensionSource(created.id);
    });
    setDraft(null);
  };

  const sync = async (source: ExtensionSourceView) => {
    setSyncingId(source.id);
    setNotice("");
    try {
      const report = await extApi.syncExtensionSource(source.id);
      if (!report.ok && report.error) {
        setNotice(`${report.error.code}: ${report.error.detail}`);
      }
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setSyncingId(null);
    }
  };

  const install = async (target: ConsentTarget) => {
    await run(() => extApi.installExtension(target.sourceId, target.candidate.extensionId, true));
    setConsentTarget(null);
  };

  const canAdd =
    draft !== null &&
    (draft.url.trim().startsWith("https://") || draft.localPath.trim().startsWith("/")) &&
    (draft.strategy === "release-tag" || draft.refValue.trim() !== "");

  return (
    <div className="space-y-3" data-testid="extension-sources-block">
      <h3 className="text-sm font-semibold">
        {t("toolsSettings.connectors.extSources.title")}
      </h3>
      <p className="text-sm text-slate-500">
        {t("toolsSettings.connectors.extSources.hint")}
      </p>

      {sources.map((source) => (
        <div
          key={source.id}
          className="border-slate-300 space-y-2 rounded-md border p-3"
          data-testid={`extension-source-${source.origin}`}
        >
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{source.origin}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
              {source.kind}
            </span>
            <span
              className={
                source.status === "ok"
                  ? "rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700"
                  : "rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700"
              }
              data-testid="source-status"
            >
              {source.status}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={syncingId === source.id}
              onClick={() => void sync(source)}
            >
              {syncingId === source.id ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {t("toolsSettings.connectors.extSources.check")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void run(() => extApi.removeExtensionSource(source.id))}
              data-testid={`remove-source-${source.id}`}
            >
              <Trash2 className="h-4 w-4" />
              {t("toolsSettings.connectors.extSources.removeSource")}
            </Button>
          </div>
          {source.error ? (
            <p className="text-xs text-red-600" data-testid="source-error">
              {source.error}
            </p>
          ) : null}

          {source.candidates
            .filter((candidate) => !source.installs.some((i) => i.extensionId === candidate.extensionId && i.state !== "removed"))
            .map((candidate) => (
              <div
                key={`${candidate.extensionId}-${candidate.digest}`}
                className="border-slate-200 space-y-1 rounded-md border p-2"
                data-testid={`extension-candidate-${candidate.extensionId}`}
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium">{candidate.extensionId}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                    listed
                  </span>
                  <span className="font-mono text-xs text-slate-500">
                    {shortDigest(candidate.digest)}
                  </span>
                  {candidate.compatible ? null : (
                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] text-red-700">
                      {candidate.reason}
                    </span>
                  )}
                </div>
                {candidate.compatible && candidate.consent ? (
                  <>
                    <ConsentDisclosure payload={candidate.consent} />
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => setConsentTarget({ sourceId: source.id, candidate })}
                      data-testid={`consent-install-${candidate.extensionId}`}
                    >
                      {t("toolsSettings.connectors.extSources.consentInstall")}
                    </Button>
                  </>
                ) : null}
              </div>
            ))}

          {source.installs.map((install) => (
            <InstallRow
              key={install.id}
              install={install}
              busy={busy}
              onEnable={(target, enabled) =>
                void run(() => extApi.setExtensionEnabled(target.id, enabled))
              }
              onApply={(target) =>
                void run(() => extApi.applyExtensionUpdate(target.id, true))
              }
              onPark={(target) => void run(() => extApi.parkExtensionInstall(target.id))}
              onTombstone={(target) =>
                void run(() => extApi.tombstoneExtensionInstall(target.id))
              }
            />
          ))}
        </div>
      ))}

      {sources.length === 0 && draft === null ? (
        <p className="py-4 text-center text-sm text-slate-400">
          {t("toolsSettings.connectors.extSources.empty")}
        </p>
      ) : null}

      {draft === null ? (
        <Button variant="outline" size="sm" onClick={() => setDraft(EMPTY_DRAFT)} data-testid="add-extension-source">
          <Plus className="h-4 w-4" />
          {t("toolsSettings.connectors.extSources.add")}
        </Button>
      ) : (
        <form
          className="border-slate-300 space-y-2 rounded-md border p-3"
          data-testid="extension-source-form"
          onSubmit={(event) => {
            event.preventDefault();
            void run(add);
          }}
        >
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder={t("toolsSettings.connectors.extSources.url")}
            aria-label={t("toolsSettings.connectors.extSources.url")}
            value={draft.url}
            onChange={(event) => setDraft({ ...draft, url: event.target.value })}
          />
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder={t("toolsSettings.connectors.extSources.localPath")}
            aria-label={t("toolsSettings.connectors.extSources.localPath")}
            value={draft.localPath}
            onChange={(event) => setDraft({ ...draft, localPath: event.target.value })}
          />
          <div className="flex flex-wrap gap-2">
            <select
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              aria-label={t("toolsSettings.connectors.extSources.strategy")}
              value={draft.strategy}
              onChange={(event) =>
                setDraft({ ...draft, strategy: event.target.value as Draft["strategy"] })
              }
            >
              <option value="release-tag">release-tag</option>
              <option value="tag-pattern">tag-pattern</option>
              <option value="branch">branch</option>
              <option value="commit-pin">commit-pin</option>
            </select>
            <input
              className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={t("toolsSettings.connectors.extSources.refValue")}
              aria-label={t("toolsSettings.connectors.extSources.refValue")}
              value={draft.refValue}
              onChange={(event) => setDraft({ ...draft, refValue: event.target.value })}
            />
          </div>
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder={t("toolsSettings.connectors.extSources.subpath")}
            aria-label={t("toolsSettings.connectors.extSources.subpath")}
            value={draft.subpath}
            onChange={(event) => setDraft({ ...draft, subpath: event.target.value })}
          />
          <input
            type="password"
            autoComplete="off"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            placeholder={t("toolsSettings.connectors.extSources.token")}
            aria-label={t("toolsSettings.connectors.extSources.token")}
            value={draft.token}
            onChange={(event) => setDraft({ ...draft, token: event.target.value })}
          />
          <div className="flex items-center gap-2">
            <Button size="sm" type="submit" disabled={busy || !canAdd}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("toolsSettings.connectors.extSources.add")}
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setDraft(null)}>
              {t("toolsSettings.connectors.sources.cancel")}
            </Button>
          </div>
        </form>
      )}

      {consentTarget ? (
        <div className="border-slate-300 space-y-2 rounded-md border p-3" data-testid="consent-confirm">
          <ConsentDisclosure payload={consentTarget.candidate.consent!} />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void run(() => install(consentTarget))}
              data-testid="confirm-consent"
            >
              {t("toolsSettings.connectors.extSources.consentConfirm")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConsentTarget(null)}
            >
              {t("toolsSettings.connectors.sources.cancel")}
            </Button>
          </div>
        </div>
      ) : null}

      {notice ? (
        <p className="text-xs text-red-600" data-testid="extension-sources-error">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
