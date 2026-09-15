import { useEffect, useState } from "react";
import { Globe, Save } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { WebSettings } from "@/api/ai";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";

const PROBE_LABELS: Record<string, string> = {
  ok: "Reachable",
  unconfigured: "Not configured",
  unreachable: "Unreachable",
  json_disabled: "JSON format disabled (enable `json` in the instance settings)",
  error: "Unexpected response",
};

/** Settings → AI: web tools (plan 80) — user-hosted SearXNG + GitHub token. */
export function WebSettingsTab() {
  const [settings, setSettings] = useState<WebSettings | null>(null);
  const [searxngUrl, setSearxngUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");

  useEffect(() => {
    aiApi
      .fetchWebSettings()
      .then((data) => {
        setSettings(data);
        setSearxngUrl(data.searxng_url);
      })
      .catch((err) => setError(apiDetail(err)));
  }, []);

  const save = async (payload: {
    searxng_url?: string;
    github_token?: string;
  }) => {
    setBusy(true);
    setError("");
    setSavedNote("");
    try {
      const data = await aiApi.updateWebSettings(payload);
      setSettings(data);
      setSearxngUrl(data.searxng_url);
      setGithubToken("");
      setSavedNote("Saved");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !error) return null;

  return (
    <div className="space-y-6" data-testid="web-tab">
      <p className="text-sm text-slate-500">
        Optional web-reach config for chat tools: a SearXNG instance backs live
        search (host it yourself and paste its URL — never bundled here), and a
        GitHub API token raises the repository-lookup rate limit.
      </p>

      {settings?.searxng_probe && (
        <div className="text-sm">
          <span className="text-slate-500">Status: </span>
          <span
            className={
              settings.searxng_probe.status === "ok"
                ? "text-emerald-600"
                : "text-amber-600"
            }
            data-testid="searxng-probe"
          >
            {PROBE_LABELS[settings.searxng_probe.status] ??
              settings.searxng_probe.status}
          </span>
        </div>
      )}

      <div className="space-y-1" data-testid="searxng-url-field">
        <label className="text-sm font-medium" htmlFor="searxng-url">
          SearXNG URL
        </label>
        <input
          id="searxng-url"
          data-testid="searxng-url-input"
          type="url"
          value={searxngUrl}
          onChange={(e) => setSearxngUrl(e.target.value)}
          placeholder="https://searx.example.org"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
      </div>
      <Button
        size="sm"
        disabled={busy || searxngUrl === settings?.searxng_url}
        data-testid="save-searxng"
        onClick={() => void save({ searxng_url: searxngUrl })}
      >
        <Save className="w-4 h-4" />
        Save search config
      </Button>

      <div className="space-y-1" data-testid="github-token-field">
        <label className="text-sm font-medium" htmlFor="github-token">
          GitHub API token {settings?.github_token_set ? "(set)" : "(optional)"}
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
        Save token
      </Button>

      {savedNote && (
        <p className="text-xs text-emerald-600" data-testid="web-saved-note">
          {savedNote}
        </p>
      )}
      {error && (
        <p className="text-xs text-red-600" data-testid="web-error">
          <Globe className="mr-1 inline w-3 h-3" />
          {error}
        </p>
      )}
    </div>
  );
}
