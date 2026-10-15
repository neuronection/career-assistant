import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, RefreshCw, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import * as aiApi from "@/api/ai";
import type { WebSettings } from "@/api/ai";
import * as sourcesApi from "@/api/sources";
import type { ConnectorCatalogEntry, PostingSource, SourceProbe } from "@/api/sources";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";

/**
 * Tools → connectors (ADR-0033, domain tools.connectors — broadened by
 * plan 32 Phase 1 to job-source connectors): external-service credentials
 * for the chat tools (MCP GitHub token) AND posting-source connector
 * instances — catalog-driven forms from the extension registry, sealed
 * x-secret slots (never echoed; hint only), per-source probes through the
 * polite runtime.
 */
type SourceDraft = {
  id: string | null;
  key: string;
  connector_key: string;
  config: Record<string, string>;
  secrets: Record<string, string>;
};

export function ConnectorsSection() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<WebSettings | null>(null);
  const [githubToken, setGithubToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");

  useEffect(() => {
    aiApi
      .fetchWebSettings()
      .then(setSettings)
      .catch((err) => setError(apiDetail(err)));
  }, []);

  const save = async (payload: { github_token?: string }) => {
    setBusy(true);
    setError("");
    setSavedNote("");
    try {
      const data = await aiApi.updateWebSettings(payload);
      setSettings(data);
      setGithubToken("");
      setSavedNote(t("toolsSettings.connectors.saved"));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !error) return null;

  return (
    <div className="space-y-8" data-testid="connectors-section">
      <div className="space-y-3" data-testid="github-token-field">
        <h3 className="text-sm font-semibold">{t("toolsSettings.connectors.mcpTitle")}</h3>
        <p className="text-sm text-slate-500">{t("toolsSettings.connectors.mcpHint")}</p>
        <div className="space-y-1">
          <label className="text-sm font-medium" htmlFor="github-token">
            {t("toolsSettings.connectors.githubToken")}{" "}
            {settings?.github_token_set
              ? `(${t("toolsSettings.connectors.tokenSet")})`
              : `(${t("toolsSettings.connectors.tokenOptional")})`}
          </label>
          <input
            id="github-token"
            data-testid="github-token-input"
            type="password"
            value={githubToken}
            onChange={(e) => setGithubToken(e.target.value)}
            placeholder="gh_pat_…"
            autoComplete="off"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <Button
          size="sm"
          disabled={busy || githubToken.length === 0}
          data-testid="save-github-token"
          onClick={() => void save({ github_token: githubToken })}
        >
          <Save className="w-4 h-4" />
          {t("toolsSettings.connectors.saveToken")}
        </Button>
      </div>

      {savedNote ? (
        <p className="text-xs text-emerald-600" data-testid="connectors-saved-note">
          {savedNote}
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-red-600" data-testid="connectors-error">
          {error}
        </p>
      ) : null}

      <JobSourceConnectors />
      <ExtensionSourcesSection />
    </div>
  );
}

function JobSourceConnectors() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<PostingSource[]>([]);
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [draft, setDraft] = useState<SourceDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [probingId, setProbingId] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, SourceProbe>>({});

  const refresh = useCallback(async () => {
    try {
      setSources(await sourcesApi.fetchAdminSources());
    } catch (err) {
      setNotice(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    sourcesApi.fetchConnectorCatalog().then(setCatalog).catch(() => setCatalog([]));
  }, [refresh]);

  const catalogByKey = useMemo(
    () => Object.fromEntries(catalog.map((entry) => [entry.key, entry])),
    [catalog],
  );

  const save = async (form: SourceDraft) => {
    setBusy(true);
    setNotice("");
    try {
      const secrets = Object.fromEntries(
        Object.entries(form.secrets).filter(([, value]) => value.trim() !== ""),
      );
      const payload = {
        key: form.key.trim(),
        connector_key: form.connector_key,
        config: form.config,
        secrets,
      };
      if (form.id) {
        await sourcesApi.updateSource(form.id, { config: form.config, secrets });
      } else {
        await sourcesApi.createSource(payload);
      }
      setDraft(null);
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (source: PostingSource) => {
    setBusy(true);
    try {
      await sourcesApi.updateSource(source.id, { enabled: !source.enabled });
      await refresh();
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const probe = async (source: PostingSource) => {
    setProbingId(source.id);
    try {
      const result = await sourcesApi.probeSource(source.id);
      setProbes((current) => ({ ...current, [source.id]: result }));
    } catch (err) {
      setProbes((current) => ({
        ...current,
        [source.id]: { ok: false, error: { code: "error", detail: apiDetail(err), retryable: "no" } },
      }));
    } finally {
      setProbingId(null);
    }
  };

  const sync = async (source: PostingSource) => {
    setBusy(true);
    try {
      await sourcesApi.syncSource(source.id);
      setNotice(t("toolsSettings.connectors.sources.syncQueued", { key: source.key }));
    } catch (err) {
      setNotice(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const entry = draft ? catalogByKey[draft.connector_key] : undefined;
  const secretFields = entry?.secret_fields ?? [];
  const required = new Set(entry?.config_schema.required ?? []);
  const configFields = Object.entries(entry?.config_schema.properties ?? {}).filter(
    ([name]) => !secretFields.includes(name),
  );
  const missingRequired = draft
    ? [...required].some(
        (name) => !secretFields.includes(name) && !(draft.config[name] ?? "").trim(),
      ) || draft.key.trim() === ""
    : false;

  return (
    <div className="space-y-3" data-testid="job-sources-block">
      <h3 className="text-sm font-semibold">{t("toolsSettings.connectors.sources.title")}</h3>
      <p className="text-sm text-slate-500">{t("toolsSettings.connectors.sources.hint")}</p>

      {sources.map((source) => {
        const result = probes[source.id];
        const connector = catalogByKey[source.connector_key];
        const needsSecret = Object.entries(source.secret_hints).some(
          ([slot, hint]) => connector?.secret_fields.includes(slot) && !hint.set,
        );
        return (
          <div
            key={source.id}
            className="border-slate-300 space-y-1 rounded-md border p-3"
            data-testid={`job-source-${source.key}`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={source.enabled}
                  aria-label={t("toolsSettings.connectors.sources.enabledAria", {
                    key: source.key,
                  })}
                  onChange={() => void toggle(source)}
                />
                {source.key}
              </label>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                {connector?.title ?? source.connector_key}
              </span>
              {Object.entries(source.secret_hints).map(([slot, hint]) => (
                <span
                  key={slot}
                  className="text-xs text-slate-500"
                  data-testid={`secret-hint-${source.key}-${slot}`}
                >
                  {hint.set
                    ? t("toolsSettings.connectors.sources.secretSet", {
                        slot,
                        hint: hint.hint ?? "",
                      })
                    : t("toolsSettings.connectors.sources.secretMissing", { slot })}
                </span>
              ))}
              {needsSecret ? (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">
                  {t("toolsSettings.connectors.sources.needsSecret")}
                </span>
              ) : null}
            </div>
            {source.error ? (
              <p className="text-xs text-red-600" data-testid={`job-source-error-${source.key}`}>
                {source.error}
              </p>
            ) : null}
            {result ? (
              <p
                className={
                  result.ok ? "text-xs text-emerald-600" : "text-xs text-amber-600"
                }
                data-testid={`job-source-probe-${source.key}`}
              >
                {result.ok
                  ? t("toolsSettings.connectors.sources.probeOk", {
                      items: result.items ?? 0,
                      latency: result.latency_ms ?? 0,
                    })
                  : t("toolsSettings.connectors.sources.probeError", {
                      code: result.error?.code ?? "error",
                      detail: result.error?.detail ?? "",
                    })}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={probingId === source.id}
                onClick={() => void probe(source)}
              >
                {probingId === source.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : null}
                {t("toolsSettings.connectors.sources.test")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void sync(source)}
              >
                <RefreshCw className="w-4 h-4" />
                {t("toolsSettings.connectors.sources.sync")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setDraft({
                    id: source.id,
                    key: source.key,
                    connector_key: source.connector_key,
                    config: Object.fromEntries(
                      Object.entries(source.config).map(([k, v]) => [k, String(v)]),
                    ),
                    secrets: {},
                  })
                }
              >
                {t("toolsSettings.connectors.sources.edit")}
              </Button>
            </div>
          </div>
        );
      })}

      {sources.length === 0 && draft === null ? (
        <p className="py-4 text-center text-sm text-slate-400">
          {t("toolsSettings.connectors.sources.empty")}
        </p>
      ) : null}

      {draft === null ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            setDraft({
              id: null,
              key: "",
              connector_key: catalog[0]?.key ?? "",
              config: {},
              secrets: {},
            })
          }
          data-testid="add-job-source"
        >
          <Plus className="w-4 h-4" />
          {t("toolsSettings.connectors.sources.add")}
        </Button>
      ) : null}

      {draft !== null && entry ? (
        <form
          className="border-slate-300 space-y-2 rounded-md border p-3"
          data-testid="job-source-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save(draft);
          }}
        >
          <div className="flex flex-wrap gap-2">
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm sm:w-auto"
              value={draft.connector_key}
              disabled={draft.id !== null}
              aria-label={t("toolsSettings.connectors.sources.connector")}
              onChange={(event) =>
                setDraft({ ...draft, connector_key: event.target.value, config: {}, secrets: {} })
              }
            >
              {catalog.map((connector) => (
                <option key={connector.key} value={connector.key}>
                  {connector.title}
                </option>
              ))}
            </select>
            <input
              className="w-full flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={t("toolsSettings.connectors.sources.key")}
              value={draft.key}
              disabled={draft.id !== null}
              onChange={(event) => setDraft({ ...draft, key: event.target.value })}
            />
          </div>
          {configFields.map(([name, field]) => (
            <input
              key={name}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={`${field.title ?? name}${required.has(name) ? " *" : ""}`}
              list={field.enum ? `job-source-enum-${name}` : undefined}
              value={draft.config[name] ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, config: { ...draft.config, [name]: event.target.value } })
              }
            />
          ))}
          {secretFields.map((name) => (
            <input
              key={name}
              type="password"
              autoComplete="off"
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={t("toolsSettings.connectors.sources.secret", {
                name: entry.config_schema.properties[name]?.title ?? name,
              })}
              value={draft.secrets[name] ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, secrets: { ...draft.secrets, [name]: event.target.value } })
              }
            />
          ))}
          {notice ? (
            <p className="text-xs text-red-600" data-testid="job-source-form-error">
              {notice}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <Button size="sm" type="submit" disabled={busy || missingRequired}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {t("toolsSettings.connectors.sources.save")}
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setDraft(null)}>
              {t("toolsSettings.connectors.sources.cancel")}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
