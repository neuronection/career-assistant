import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import * as aiApi from "@/api/ai";
import type { SearchProvider, SearchProviderProbe } from "@/api/ai";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";

// Tools → web search (ADR-0033 domain tools.web-search): the family
// multi-provider shape (ADR-0035 / plan 28 Phase 4) — an ordered list; the
// first enabled provider that answers wins. Career serves it through its
// SSRF-guarded searxng transport (plan 80); keyed POST providers join when
// guarded adapters land. The form renders from the vendored catalog.
type Draft = {
  id: string | null;
  type: string;
  name: string;
  base_url: string;
  api_key: string;
};

const PROBE_LABEL_KEYS: Record<string, string> = {
  ok: "toolsSettings.webSearch.probeOk",
  unreachable: "toolsSettings.webSearch.probeUnreachable",
  auth: "toolsSettings.webSearch.probeAuth",
  rate_limit: "toolsSettings.webSearch.probeRateLimited",
  json_disabled: "toolsSettings.webSearch.probeJsonDisabled",
  error: "toolsSettings.webSearch.probeError",
};

export function WebSearchSection() {
  const { t } = useTranslation();
  const [providers, setProviders] = useState<SearchProvider[]>([]);
  const [catalog, setCatalog] = useState<aiApi.SearchProviderCatalog | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, SearchProviderProbe>>({});

  const refresh = useCallback(async () => {
    try {
      setProviders(await aiApi.listSearchProviders());
    } catch (error) {
      setNotice(apiDetail(error));
    }
  }, []);

  useEffect(() => {
    void refresh();
    aiApi.getSearchProviderCatalog().then(setCatalog).catch(() => setCatalog(null));
  }, [refresh]);

  const save = async (form: Draft) => {
    setBusy(true);
    setNotice("");
    try {
      const body = {
        type: form.type,
        name: form.name.trim() || null,
        base_url: form.base_url.trim() || null,
        api_key: form.api_key.trim() === "" ? null : form.api_key.trim(),
      };
      if (form.id) {
        await aiApi.updateSearchProvider(form.id, body);
      } else {
        await aiApi.createSearchProvider(body);
      }
      setDraft(null);
      await refresh();
    } catch (error) {
      setNotice(apiDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (provider: SearchProvider) => {
    setBusy(true);
    try {
      await aiApi.updateSearchProvider(provider.id, { enabled: !provider.enabled });
      await refresh();
    } catch (error) {
      setNotice(apiDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const move = async (id: string, direction: "up" | "down") => {
    setBusy(true);
    try {
      setProviders(await aiApi.moveSearchProvider(id, direction));
    } catch (error) {
      setNotice(apiDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      await aiApi.deleteSearchProvider(id);
      await refresh();
    } catch (error) {
      setNotice(apiDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (provider: SearchProvider) => {
    setTestingId(provider.id);
    try {
      const result = await aiApi.testSearchProvider(provider.id);
      setProbes((current) => ({ ...current, [provider.id]: result }));
    } catch (error) {
      setProbes((current) => ({
        ...current,
        [provider.id]: {
          status: "error",
          error: apiDetail(error),
          latency_ms: 0,
          result_count: null,
        },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const catalogEntry = (type: string) => catalog?.providers[type];
  const entry = draft ? catalogEntry(draft.type) : undefined;
  const saveDisabled =
    busy || (entry?.baseUrlRequired === true && draft?.base_url.trim() === "");

  return (
    <div className="space-y-6" data-testid="web-search-section">
      <p className="text-sm text-slate-500">{t("toolsSettings.webSearch.hint")}</p>

      {providers.map((provider, index) => {
        const result = probes[provider.id];
        return (
          <div
            key={provider.id}
            className="border-slate-300 space-y-1 rounded-md border p-3"
            data-testid={`web-search-provider-${provider.id}`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={provider.enabled}
                  aria-label={t("toolsSettings.webSearch.enabledAria", { name: provider.name })}
                  onChange={() => void toggle(provider)}
                />
                {provider.name}
              </label>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                {catalogEntry(provider.type)?.label ?? provider.type}
              </span>
              {provider.base_url ? (
                <span className="truncate font-mono text-xs text-slate-500">
                  {provider.base_url}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-slate-500">
                {provider.key_set
                  ? (provider.key_hint ?? t("toolsSettings.webSearch.keyStored"))
                  : t("toolsSettings.webSearch.noKey")}
              </span>
            </div>
            {result ? (
              <p
                className={
                  result.status === "ok" ? "text-xs text-emerald-600" : "text-xs text-amber-600"
                }
                data-testid={`web-search-probe-${provider.id}`}
              >
                {result.status === "error" && result.error
                  ? result.error
                  : t(PROBE_LABEL_KEYS[result.status] ?? "toolsSettings.webSearch.probeError")}
                {result.status === "ok" ? ` · ${result.latency_ms} ms` : ""}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={testingId === provider.id}
                onClick={() => void runTest(provider)}
              >
                {testingId === provider.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : null}
                {t("toolsSettings.webSearch.test")}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title={t("toolsSettings.webSearch.moveUp")}
                disabled={index === 0 || busy}
                onClick={() => void move(provider.id, "up")}
              >
                <ChevronUp className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title={t("toolsSettings.webSearch.moveDown")}
                disabled={index === providers.length - 1 || busy}
                onClick={() => void move(provider.id, "down")}
              >
                <ChevronDown className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title={t("toolsSettings.webSearch.edit")}
                onClick={() =>
                  setDraft({
                    id: provider.id,
                    type: provider.type,
                    name: provider.name,
                    base_url: provider.base_url ?? "",
                    api_key: "",
                  })
                }
              >
                <Pencil className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title={t("toolsSettings.webSearch.delete")}
                disabled={busy}
                onClick={() => void remove(provider.id)}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
              {!provider.enabled ? (
                <span className="text-xs text-slate-400">
                  {t("toolsSettings.webSearch.disabled")}
                </span>
              ) : null}
            </div>
          </div>
        );
      })}

      {providers.length === 0 && draft === null ? (
        <p className="py-4 text-center text-sm text-slate-400">
          {t("toolsSettings.webSearch.empty")}
        </p>
      ) : null}

      {draft === null ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            setDraft({
              id: null,
              type: catalog?.providerOrder[0] ?? "searxng",
              name: "",
              base_url: "",
              api_key: "",
            })
          }
        >
          <Plus className="w-4 h-4" />
          {t("toolsSettings.webSearch.add")}
        </Button>
      ) : null}

      {draft !== null ? (
        <form
          className="border-slate-300 space-y-2 rounded-md border p-3"
          data-testid="web-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save(draft);
          }}
        >
          <div className="flex flex-wrap gap-2">
            <select
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm sm:w-auto"
              value={draft.type}
              disabled={draft.id !== null}
              aria-label={t("toolsSettings.webSearch.type")}
              onChange={(event) => setDraft({ ...draft, type: event.target.value })}
            >
              {(catalog?.providerOrder ?? []).map((type) => (
                <option key={type} value={type}>
                  {catalogEntry(type)?.label ?? type}
                </option>
              ))}
            </select>
            <input
              className="w-full flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={t("toolsSettings.webSearch.name")}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              className="w-full flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={
                entry?.baseUrlRequired
                  ? t("toolsSettings.webSearch.baseUrlRequired")
                  : (entry?.baseUrlHint ?? t("toolsSettings.webSearch.baseUrl"))
              }
              value={draft.base_url}
              onChange={(event) => setDraft({ ...draft, base_url: event.target.value })}
            />
            <input
              type="password"
              className="w-48 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              placeholder={
                draft.id
                  ? t("toolsSettings.webSearch.keyStored")
                  : entry?.requiresKey
                    ? t("toolsSettings.webSearch.key")
                    : t("toolsSettings.webSearch.keyOptional")
              }
              value={draft.api_key}
              onChange={(event) => setDraft({ ...draft, api_key: event.target.value })}
            />
          </div>
          {entry?.notes ? (
            <p className="text-[11px] text-slate-500">{entry.notes}</p>
          ) : null}
          {notice ? (
            <p className="text-xs text-red-600" data-testid="web-search-error">
              {notice}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <Button size="sm" type="submit" disabled={saveDisabled}>
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {t("toolsSettings.webSearch.save")}
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setDraft(null)}>
              {t("toolsSettings.webSearch.cancel")}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
