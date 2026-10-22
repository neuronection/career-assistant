import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy, KeyRound, Loader2, Plus, RefreshCw, RotateCw, Trash2 } from "lucide-react";

import * as mcpApi from "@/api/mcp";
import type { McpAuditRow, McpStatus, McpTokenMinted, McpTokenView } from "@/api/mcp";
import { apiDetail } from "@/api/client";
import {
  approveProfileProposal,
  fetchProfileProposals,
  rejectProfileProposal,
} from "@/api/profileProposals";
import { Button } from "@/components/ui";
import { SwitchRow } from "@/components/ui/switch-row";
import { SegmentedTabs } from "@/components/ui";
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

/** Settings → Tools → Connectors → MCP server (plan 119.2).
 *
 * The instance MCP endpoint, its token lifecycle (mint shown once,
 * rotate, revoke), copy-ready client snippets, the live registry
 * projection with scopes, the admin write switch and the recent-call
 * audit. MCP-originated approval cards render here with their origin. */
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

  if (!status) {
    return error ? (
      <p className="text-xs text-red-600" data-testid="mcp-error">
        {error}
      </p>
    ) : null;
  }

  return (
    <div className="space-y-6" data-testid="mcp-server-section">
      <div>
        <h3 className="text-sm font-semibold">{t("toolsSettings.mcp.title")}</h3>
        <p className="text-sm text-slate-500">{t("toolsSettings.mcp.hint")}</p>
      </div>

      <div className="space-y-2 rounded-md border border-slate-200 p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium">{t("toolsSettings.mcp.endpoint")}</span>
          <span className="text-[11px] text-slate-500">{status.transport}</span>
        </div>
        <div className="flex items-center gap-2">
          <code
            className="min-w-0 flex-1 truncate rounded bg-slate-50 px-2 py-1 text-xs"
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

      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("toolsSettings.mcp.tokensTitle")}
        </h4>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex-1 space-y-1 text-xs">
            <span className="font-medium">{t("toolsSettings.mcp.tokenLabel")}</span>
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder={t("toolsSettings.mcp.tokenLabelPlaceholder")}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              data-testid="mcp-token-label"
            />
          </label>
          <label className="flex items-center gap-2 pb-2 text-xs">
            <input
              type="checkbox"
              checked={writeScope}
              disabled={!status.write_enabled}
              onChange={(event) => setWriteScope(event.target.checked)}
              data-testid="mcp-token-write-scope"
            />
            {t("toolsSettings.mcp.writeScope")}
          </label>
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
        {!status.write_enabled ? (
          <p className="text-[11px] text-slate-500">{t("toolsSettings.mcp.writeScopeHint")}</p>
        ) : null}

        {minted ? (
          <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3" data-testid="mcp-minted-token">
            <p className="text-xs font-medium text-amber-900">{t("toolsSettings.mcp.shownOnce")}</p>
            <code className="block break-all rounded bg-white/70 px-2 py-1 text-xs">{minted.token}</code>
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
          <p className="text-xs text-slate-500" data-testid="mcp-tokens-empty">
            {t("toolsSettings.mcp.noTokens")}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
            {tokens.map((token) => (
              <li key={token.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs" data-testid={`mcp-token-${token.id}`}>
                <KeyRound className="h-4 w-4 text-slate-400" />
                <span className="font-medium">{token.label || t("toolsSettings.mcp.untitled")}</span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px]">{token.scopes.join(" + ")}</span>
                <span className="text-slate-500">
                  {token.active
                    ? t("toolsSettings.mcp.active")
                    : t("toolsSettings.mcp.revoked")}
                </span>
                <span className="ml-auto flex items-center gap-1">
                  {token.active ? (
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
                  ) : null}
                  {token.active ? (
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
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t("toolsSettings.mcp.snippetsTitle")}
          </h4>
          <Button size="sm" variant="outline" onClick={() => void copy("snippet", snippetText)} data-testid="mcp-copy-snippet">
            {copied === "snippet" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {t("toolsSettings.mcp.copy")}
          </Button>
        </div>
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
        <p className="text-[11px] text-slate-500">{t("toolsSettings.mcp.snippetHint")}</p>
        <pre className="overflow-x-auto rounded-md bg-slate-50 p-3 text-[11px]" data-testid="mcp-snippet">
          {snippetText}
        </pre>
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("toolsSettings.mcp.toolsTitle", { count: status.tools.length })}
        </h4>
        <ul className="grid gap-1 sm:grid-cols-2" data-testid="mcp-tool-list">
          {status.tools.map((tool) => (
            <li key={tool.key} className="rounded border border-slate-200 px-2 py-1 text-[11px]">
              <span className="font-medium">{tool.title}</span>
              <span
                className={
                  tool.scope === "write"
                    ? "ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800"
                    : "ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600"
                }
              >
                {tool.scope}
              </span>
              <p className="mt-0.5 text-slate-500">{tool.description}</p>
            </li>
          ))}
        </ul>
        {status.write_tools.length > 0 ? (
          <p className="text-[11px] text-amber-700">{t("toolsSettings.mcp.writeToolsNote")}</p>
        ) : null}
      </div>

      {proposals.length > 0 ? (
        <div className="space-y-2" data-testid="mcp-pending-proposals">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t("toolsSettings.mcp.pendingTitle", { count: proposals.length })}
          </h4>
          <ul className="space-y-1">
            {proposals.map((proposal) => (
              <li
                key={proposal.id}
                className="rounded border border-slate-200 px-3 py-2 text-xs"
                data-testid={`mcp-proposal-${proposal.id}`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{proposal.title}</span>
                  <span className="ml-auto text-[10px] text-slate-500">
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
        </div>
      ) : null}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t("toolsSettings.mcp.auditTitle")}
          </h4>
          <Button size="sm" variant="ghost" onClick={() => void reload()} data-testid="mcp-audit-refresh">
            <RefreshCw className="h-4 w-4" />
            {t("toolsSettings.mcp.refresh")}
          </Button>
        </div>
        {audit.length === 0 ? (
          <p className="text-xs text-slate-500" data-testid="mcp-audit-empty">
            {t("toolsSettings.mcp.noCalls")}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 text-[11px]">
            {audit.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5">
                <code className="font-medium">{row.tool ?? "—"}</code>
                <span className="text-slate-500">{row.label}</span>
                <span className={row.status === "ok" ? "text-emerald-600" : "text-red-600"}>
                  {row.status}
                </span>
                <span className="ml-auto text-slate-500">{Math.round(row.latency_ms)} ms</span>
                <span className="text-slate-400">{row.created_at.slice(0, 19).replace("T", " ")}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error ? (
        <p className="text-xs text-red-600" data-testid="mcp-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
