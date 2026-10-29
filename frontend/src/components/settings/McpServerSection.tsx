import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bot,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  RotateCw,
  Save,
  ScrollText,
  Search,
  Trash2,
} from "lucide-react";

import * as mcpApi from "@/api/mcp";
import * as aiApi from "@/api/ai";
import type { McpAuditRow, McpStatus, McpTokenMinted, McpTokenView } from "@/api/mcp";
import { apiDetail } from "@/api/client";
import {
  approveProfileProposal,
  fetchProfileProposals,
  rejectProfileProposal,
} from "@/api/profileProposals";
import { Badge, Button } from "@/components/ui";
import { Input } from "@neuronection/assistant-ui";
import { SwitchRow } from "@/components/ui/switch-row";
import { SegmentedTabs } from "@/components/ui";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { copyText } from "@/lib/clipboard";
import type { ProfileProposalCardData } from "@/types";

const TOKEN_PLACEHOLDER = "YOUR_MCP_TOKEN";

function claudeConfig(endpoint: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        "career-assistant": {
          command: "npx",
          args: [
            "-y",
            "mcp-remote",
            endpoint,
            "--header",
            `Authorization: Bearer ${token}`,
          ],
        },
      },
    },
    null,
    2
  );
}

function httpConfig(endpoint: string, token: string): string {
  return JSON.stringify(
    {
      url: endpoint,
      transport: "streamable-http",
      headers: { Authorization: `Bearer ${token}` },
    },
    null,
    2
  );
}

function errorText(error: unknown, fallback: string): string {
  return apiDetail(error) || fallback;
}

/** Settings → Tools → connectors → MCP server (plan 119.2, plan 148
 * phase 2). Section cards: the endpoint hero with the write switch and
 * the chat-tools credentials + client-setup disclosures, the token
 * lifecycle, the live tool catalog collapsed behind a searchable
 * disclosure, MCP-originated approval cards and the recent-call audit. */
export function McpServerSection() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<McpStatus | null>(null);
  const [tokens, setTokens] = useState<McpTokenView[]>([]);
  const [audit, setAudit] = useState<McpAuditRow[]>([]);
  const [proposals, setProposals] = useState<ProfileProposalCardData[]>([]);
  const [minted, setMinted] = useState<McpTokenMinted | null>(null);
  const [label, setLabel] = useState("");
  const [writeScope, setWriteScope] = useState(false);
  const [snippet, setSnippet] = useState<"claude" | "http">("claude");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [toolFilter, setToolFilter] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [githubSet, setGithubSet] = useState<boolean | null>(null);
  // i18n `t` is not referentially stable in every host (test harnesses and
  // locale switches recreate it) — read it through a ref so `reload` stays
  // stable and the mount effect cannot loop.
  const translate = useRef(t);
  translate.current = t;

  const reload = useCallback(async () => {
    try {
      const [nextStatus, nextTokens, nextAudit] = await Promise.all([
        mcpApi.fetchMcpStatus(),
        mcpApi.fetchMcpTokens(),
        mcpApi.fetchMcpAudit(),
      ]);
      setStatus(nextStatus);
      setTokens(nextTokens);
      setAudit(nextAudit);
      setError("");
    } catch (err) {
      setError(errorText(err, translate.current("toolsSettings.mcp.loadError")));
    }
    try {
      const { proposals: rows } = await fetchProfileProposals("pending");
      setProposals(rows.filter((row) => row.source === "mcp"));
    } catch {
      setProposals([]);
    }
  }, []);

  useEffect(() => {
    void reload();
    aiApi
      .fetchWebSettings()
      .then((settings) => setGithubSet(settings.github_token_set))
      .catch(() => setGithubSet(null));
  }, [reload]);

  const secretShown = useMemo(() => minted?.token ?? TOKEN_PLACEHOLDER, [minted]);
  const endpoint = status?.endpoint ?? "";
  const snippetText = useMemo(
    () => (snippet === "claude" ? claudeConfig(endpoint, secretShown) : httpConfig(endpoint, secretShown)),
    [snippet, endpoint, secretShown]
  );

  const copy = async (key: string, text: string) => {
    await copyText(text);
    setCopied(key);
  };

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err, t("toolsSettings.mcp.actionError")));
    } finally {
      setBusy("");
    }
  };

  const mint = () =>
    run("mint", async () => {
      const created = await mcpApi.mintMcpToken({
        label: label.trim() || t("toolsSettings.mcp.defaultLabel"),
        scopes: writeScope ? ["read", "write"] : ["read"],
      });
      setMinted(created);
      setLabel("");
      setWriteScope(false);
      await reload();
    });

  const rotate = (id: string) =>
    run(`rotate-${id}`, async () => {
      const created = await mcpApi.rotateMcpToken(id);
      setMinted(created);
      await reload();
    });

  const revoke = (id: string) =>
    run(`revoke-${id}`, async () => {
      await mcpApi.revokeMcpToken(id);
      if (minted?.id === id) setMinted(null);
      await reload();
    });

  const resolve = (id: string, action: "approve" | "reject") =>
    run(`${action}-${id}`, async () => {
      if (action === "approve") {
        await approveProfileProposal(id);
      } else {
        await rejectProfileProposal(id);
      }
      await reload();
    });

  const toggleWrite = (enabled: boolean) =>
    run("write", async () => {
      await mcpApi.setMcpWriteEnabled(enabled);
      await reload();
    });

  const saveGithubToken = async () => {
    await run("github", async () => {
      const data = await aiApi.updateWebSettings({ github_token: githubToken });
      setGithubSet(data.github_token_set);
      setGithubToken("");
    });
  };

  const filteredTools = useMemo(() => {
    const needle = toolFilter.trim().toLowerCase();
    const tools = status?.tools ?? [];
    if (!needle) return tools;
    return tools.filter(
      (tool) =>
        tool.title.toLowerCase().includes(needle) ||
        tool.key.toLowerCase().includes(needle) ||
        tool.description.toLowerCase().includes(needle)
    );
  }, [status?.tools, toolFilter]);

  if (!status) {
    return error ? (
      <p className="text-xs text-[var(--as-danger)]" data-testid="mcp-error">
        {error}
      </p>
    ) : null;
  }

  return (
    <div className="space-y-4" data-testid="mcp-server-section">
      <SettingsSectionCard
        name="mcp"
        title={t("toolsSettings.mcp.title")}
        description={t("toolsSettings.mcp.hint")}
        icon={Bot}
        adminOnly
      >
        <div className="space-y-3">
          <div className="space-y-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-[var(--as-fg)]">
                {t("toolsSettings.mcp.endpoint")}
              </span>
              <Badge variant="secondary">{status.transport}</Badge>
            </div>
            <div className="flex items-center gap-2">
              <code
                className="min-w-0 flex-1 truncate rounded bg-[var(--as-surface-raised)] px-2 py-1 text-xs text-[var(--as-fg)]"
                data-testid="mcp-endpoint"
              >
                {status.endpoint}
              </code>
              <Button
                size="sm"
                variant="outline"
                data-testid="mcp-copy-endpoint"
                onClick={() => void copy("endpoint", status.endpoint)}
              >
                {copied === "endpoint" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {t("toolsSettings.mcp.copy")}
              </Button>
            </div>
            <SwitchRow
              label={t("toolsSettings.mcp.writeTitle")}
              checked={status.write_enabled}
              disabled={busy === "write"}
              currentValue={t(
                status.write_enabled
                  ? "toolsSettings.mcp.writeOn"
                  : "toolsSettings.mcp.writeOff"
              )}
              onCheckedChange={(next) => void toggleWrite(next)}
              data-testid="mcp-write-toggle"
            />
          </div>

          <details className="group">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]">
              {t("toolsSettings.connectors.mcpTitle")}
            </summary>
            <div className="mt-2 space-y-2" data-testid="github-token-field">
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("toolsSettings.connectors.mcpHint")}
              </p>
              <label className="block text-xs text-[var(--as-muted-fg)]">
                {t("toolsSettings.connectors.githubToken")}{" "}
                {githubSet
                  ? `(${t("toolsSettings.connectors.tokenSet")})`
                  : `(${t("toolsSettings.connectors.tokenOptional")})`}
                <Input
                  value={githubToken}
                  data-testid="github-token-input"
                  type="password"
                  placeholder={t("toolsSettings.connectors.sources.githubTokenPlaceholder")}
                  autoComplete="off"
                  onChange={(e) => setGithubToken(e.target.value)}
                  className="mt-1 w-full"
                />
              </label>
              <Button
                size="sm"
                disabled={busy === "github" || githubToken.length === 0}
                data-testid="save-github-token"
                onClick={() => void saveGithubToken()}
              >
                {busy === "github" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                {t("toolsSettings.connectors.saveToken")}
              </Button>
            </div>
          </details>

          <details className="group">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]">
              {t("toolsSettings.mcp.snippetsTitle")}
            </summary>
            <div className="mt-2 space-y-2">
              <div className="flex items-center justify-end gap-2">
                <SegmentedTabs
                  ariaLabel={t("toolsSettings.mcp.snippetsTitle")}
                  className="max-w-xs"
                  items={[
                    { value: "claude", label: t("toolsSettings.mcp.snippetClaude") },
                    { value: "http", label: t("toolsSettings.mcp.snippetHttp") },
                  ]}
                  value={snippet}
                  onValueChange={(next) => setSnippet(next as "claude" | "http")}
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void copy("snippet", snippetText)}
                  data-testid="mcp-copy-snippet"
                >
                  {copied === "snippet" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {t("toolsSettings.mcp.copy")}
                </Button>
              </div>
              <p className="text-[11px] text-[var(--as-muted-fg)]">
                {t("toolsSettings.mcp.snippetHint")}
              </p>
              <pre className="overflow-x-auto rounded-lg bg-[var(--as-muted)] p-3 text-[11px] text-[var(--as-fg)]" data-testid="mcp-snippet">
                {snippetText}
              </pre>
            </div>
          </details>

          {error ? (
            <p className="text-xs text-[var(--as-danger)]" data-testid="mcp-error">
              {error}
            </p>
          ) : null}
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        name="mcp-tokens"
        title={t("toolsSettings.mcp.tokensTitle")}
        description={t("toolsSettings.mcp.tokensHint")}
        icon={KeyRound}
        adminOnly
        badges={
          status.active_tokens > 0 ? (
            <Badge variant="secondary">{status.active_tokens}</Badge>
          ) : null
        }
        footer={
          <div className="flex w-full flex-wrap items-end gap-2">
            <label className="min-w-0 flex-1 space-y-1 text-xs text-[var(--as-muted-fg)]">
              <span className="font-medium">{t("toolsSettings.mcp.tokenLabel")}</span>
              <input
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder={t("toolsSettings.mcp.tokenLabelPlaceholder")}
                className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
                data-testid="mcp-token-label"
              />
            </label>
            <SwitchRow
              label={t("toolsSettings.mcp.writeScope")}
              checked={writeScope}
              disabled={!status.write_enabled}
              onCheckedChange={setWriteScope}
              data-testid="mcp-token-write-scope"
              className="w-auto shrink-0 border-none bg-transparent px-0 hover:bg-transparent"
            />
            <Button
              size="sm"
              disabled={busy === "mint"}
              data-testid="mcp-mint-token"
              onClick={() => void mint()}
            >
              {busy === "mint" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {t("toolsSettings.mcp.mint")}
            </Button>
          </div>
        }
      >
        {!status.write_enabled ? (
          <p className="text-[11px] text-[var(--as-muted-fg)]">
            {t("toolsSettings.mcp.writeScopeHint")}
          </p>
        ) : null}

        {minted ? (
          <div
            className="mb-3 space-y-1 rounded-lg border border-[color-mix(in_srgb,var(--as-warning)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-warning)_14%,var(--as-surface-raised))] p-3"
            data-testid="mcp-minted-token"
          >
            <p className="text-xs font-medium text-[var(--as-fg)]">
              {t("toolsSettings.mcp.shownOnce")}
            </p>
            <code className="block break-all rounded bg-[var(--as-surface-raised)] px-2 py-1 text-xs text-[var(--as-fg)]">
              {minted.token}
            </code>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void copy("token", minted.token)}
                data-testid="mcp-copy-token"
              >
                {copied === "token" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {t("toolsSettings.mcp.copyToken")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMinted(null)}>
                {t("toolsSettings.mcp.dismiss")}
              </Button>
            </div>
          </div>
        ) : null}

        {tokens.length === 0 ? (
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="mcp-tokens-empty">
            {t("toolsSettings.mcp.noTokens")}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--as-border)] rounded-lg border border-[var(--as-border)]">
            {tokens.map((token) => (
              <li
                key={token.id}
                className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs"
                data-testid={`mcp-token-${token.id}`}
              >
                <KeyRound className="h-4 w-4 text-[var(--as-muted-fg)]" />
                <span className="font-medium text-[var(--as-fg)]">
                  {token.label || t("toolsSettings.mcp.untitled")}
                </span>
                <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]">
                  {token.scopes.join(" + ")}
                </span>
                <Badge variant={token.active ? "success" : "outline"}>
                  {token.active
                    ? t("toolsSettings.mcp.active")
                    : t("toolsSettings.mcp.revoked")}
                </Badge>
                <span className="ml-auto flex items-center gap-1">
                  {token.active ? (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy === `rotate-${token.id}`}
                        data-testid={`mcp-rotate-${token.id}`}
                        onClick={() => void rotate(token.id)}
                      >
                        <RotateCw className="h-4 w-4" />
                        {t("toolsSettings.mcp.rotate")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy === `revoke-${token.id}`}
                        data-testid={`mcp-revoke-${token.id}`}
                        onClick={() => void revoke(token.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                        {t("toolsSettings.mcp.revoke")}
                      </Button>
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SettingsSectionCard>

      <SettingsSectionCard
        name="mcp-tools"
        title={t("toolsSettings.mcp.toolsTitle", { count: status.tools.length })}
        description={t("toolsSettings.mcp.toolsHint")}
        icon={ScrollText}
        adminOnly
        collapsible
        defaultOpen={false}
      >
        <div className="space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--as-muted-fg)]" aria-hidden />
            <input
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] py-1.5 pl-8 pr-3 text-sm text-[var(--as-fg)] placeholder:text-[var(--as-muted-fg)] focus:border-[var(--as-primary)] focus:outline-none"
              placeholder={t("toolsSettings.mcp.searchTools")}
              value={toolFilter}
              onChange={(event) => setToolFilter(event.target.value)}
              data-testid="mcp-tool-filter"
            />
          </div>
          <ul className="grid gap-1 sm:grid-cols-2" data-testid="mcp-tool-list">
            {filteredTools.map((tool) => (
              <li
                key={tool.key}
                className="rounded border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-2 py-1.5 text-[11px]"
                data-testid={`mcp-tool-${tool.key}`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="truncate font-medium text-[var(--as-fg)]">{tool.title}</span>
                  <Badge variant={tool.scope === "write" ? "warning" : "secondary"}>
                    {tool.scope}
                  </Badge>
                </span>
                <p className="mt-0.5 line-clamp-2 text-[var(--as-muted-fg)]">{tool.description}</p>
              </li>
            ))}
            {filteredTools.length === 0 ? (
              <li className="text-xs text-[var(--as-muted-fg)]">
                {t("toolsSettings.mcp.noToolsMatch")}
              </li>
            ) : null}
          </ul>
          {status.write_tools.length > 0 ? (
            <p className="text-[11px] text-[var(--as-warning)]">{t("toolsSettings.mcp.writeToolsNote")}</p>
          ) : null}
        </div>
      </SettingsSectionCard>

      {proposals.length > 0 ? (
        <SettingsSectionCard
          name="mcp-proposals"
          title={t("toolsSettings.mcp.pendingTitle", { count: proposals.length })}
          icon={Bot}
          adminOnly
        >
          <ul className="space-y-1" data-testid="mcp-pending-proposals">
            {proposals.map((proposal) => (
              <li
                key={proposal.id}
                className="rounded border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-xs"
                data-testid={`mcp-proposal-${proposal.id}`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[var(--as-fg)]">{proposal.title}</span>
                  <span className="ml-auto text-[10px] text-[var(--as-muted-fg)]">
                    {proposal.origin?.token_label
                      ? t("toolsSettings.mcp.origin", {
                          token: proposal.origin.token_label,
                          request: proposal.origin.request_id?.slice(0, 8) ?? "—",
                        })
                      : t("toolsSettings.mcp.originUnknown")}
                  </span>
                </div>
                <div className="mt-1 flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => void resolve(proposal.id, "approve")}
                    data-testid={`mcp-approve-${proposal.id}`}
                  >
                    {t("toolsSettings.mcp.approve")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void resolve(proposal.id, "reject")}
                  >
                    {t("toolsSettings.mcp.reject")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </SettingsSectionCard>
      ) : null}

      <SettingsSectionCard
        name="mcp-audit"
        title={t("toolsSettings.mcp.auditTitle")}
        description={t("toolsSettings.mcp.auditHint")}
        icon={ScrollText}
        adminOnly
        collapsible
        defaultOpen={false}
        footer={
          <Button size="sm" variant="ghost" onClick={() => void reload()} data-testid="mcp-audit-refresh">
            <RefreshCw className="h-3.5 w-3.5" />
            {t("toolsSettings.mcp.refresh")}
          </Button>
        }
      >
        {audit.length === 0 ? (
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="mcp-audit-empty">
            {t("toolsSettings.mcp.noCalls")}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--as-border)] rounded-lg border border-[var(--as-border)] text-[11px]">
            {audit.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5">
                <code className="font-medium text-[var(--as-fg)]">{row.tool ?? "—"}</code>
                <span className="text-[var(--as-muted-fg)]">{row.label}</span>
                <span className={row.status === "ok" ? "text-emerald-600" : "text-[var(--as-danger)]"}>
                  {row.status}
                </span>
                <span className="ml-auto text-[var(--as-muted-fg)]">
                  {Math.round(row.latency_ms)} ms
                </span>
                <span className="text-[var(--as-muted-fg)]">
                  {row.created_at.slice(0, 19).replace("T", " ")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SettingsSectionCard>
    </div>
  );
}
