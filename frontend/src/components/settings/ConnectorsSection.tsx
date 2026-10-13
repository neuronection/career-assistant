import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import * as aiApi from "@/api/ai";
import type { WebSettings } from "@/api/ai";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";

/**
 * Tools → connectors (ADR-0033, domain tools.connectors): external-service
 * credentials used by the chat tools. Split out of the former AI-config
 * `web` tab in plan 27 Phase 3.
 */
export function ConnectorsSection() {
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
      setSavedNote("Saved");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (!settings && !error) return null;

  return (
    <div className="space-y-6" data-testid="connectors-section">
      <p className="text-sm text-slate-500">
        Credentials for external services the assistant&rsquo;s tools call. The
        GitHub API token raises the repository-lookup rate limit.
      </p>

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
        <p className="text-xs text-emerald-600" data-testid="connectors-saved-note">
          {savedNote}
        </p>
      )}
      {error && (
        <p className="text-xs text-red-600" data-testid="connectors-error">
          {error}
        </p>
      )}
    </div>
  );
}
