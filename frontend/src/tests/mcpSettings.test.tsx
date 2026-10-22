import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { McpServerSection } from "@/components/settings/McpServerSection";
import type { McpAuditRow, McpStatus, McpTokenView } from "@/api/mcp";

const api = vi.hoisted(() => ({
  fetchMcpStatus: vi.fn(),
  fetchMcpTokens: vi.fn(),
  fetchMcpAudit: vi.fn(),
  mintMcpToken: vi.fn(),
  rotateMcpToken: vi.fn(),
  revokeMcpToken: vi.fn(),
  setMcpWriteEnabled: vi.fn(),
}));

vi.mock("@/api/mcp", () => api);

const STATUS: McpStatus = {
  endpoint: "https://career.example/mcp",
  transport: "streamable-http",
  write_enabled: false,
  tools: [
    {
      key: "my_applications",
      title: "My applications",
      description: "Pipeline rows",
      scope: "read",
      risk_class: "read-only",
    },
    {
      key: "search_postings",
      title: "Search open postings",
      description: "Live vacancies",
      scope: "read",
      risk_class: "read-only",
    },
  ],
  read_tools: ["my_applications", "search_postings"],
  write_tools: [],
  active_tokens: 0,
};

const TOKEN: McpTokenView = {
  id: "tok-1",
  label: "Claude Desktop",
  scopes: ["read"],
  bound_user_id: "user-1",
  created_at: "2026-10-22T09:00:00Z",
  last_used_at: null,
  rotated_at: null,
  revoked_at: null,
  rotated_from_id: null,
  active: true,
};

const AUDIT: McpAuditRow = {
  id: "audit-1",
  tool: "my_applications",
  label: "Claude Desktop",
  status: "ok",
  latency_ms: 42.2,
  request_id: "request-abcdef",
  created_at: "2026-10-22T09:10:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchMcpStatus.mockResolvedValue(STATUS);
  api.fetchMcpTokens.mockResolvedValue([TOKEN]);
  api.fetchMcpAudit.mockResolvedValue([AUDIT]);
  api.setMcpWriteEnabled.mockResolvedValue({
    write_enabled: true,
    tools: STATUS.tools,
    write_tools: ["application_transition"],
  });
  api.mintMcpToken.mockResolvedValue({
    ...TOKEN,
    id: "tok-2",
    label: "Laptop",
    token: "secret-value",
  });
  api.rotateMcpToken.mockResolvedValue({
    ...TOKEN,
    id: "tok-3",
    token: "rotated-secret",
  });
  api.revokeMcpToken.mockResolvedValue(undefined);
});

describe("MCP server settings (plan 119.2/119.4)", () => {
  it("renders the endpoint, live tools with scopes and recent calls", async () => {
    render(<McpServerSection />);
    expect(await screen.findByTestId("mcp-endpoint")).toHaveTextContent(
      "https://career.example/mcp"
    );
    const tools = await screen.findByTestId("mcp-tool-list");
    expect(tools).toHaveTextContent("My applications");
    expect(tools).toHaveTextContent("read");
    expect(screen.getByText("my_applications")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("mints a token and shows the secret exactly once", async () => {
    const user = userEvent.setup();
    render(<McpServerSection />);
    await screen.findByTestId("mcp-endpoint");
    await user.type(await screen.findByTestId("mcp-token-label"), "Laptop");
    await user.click(screen.getByTestId("mcp-mint-token"));
    expect(api.mintMcpToken).toHaveBeenCalledWith({ label: "Laptop", scopes: ["read"] });
    const minted = await screen.findByTestId("mcp-minted-token");
    expect(minted).toHaveTextContent("secret-value");
    await user.click(screen.getByTestId("mcp-copy-token"));
    expect(await screen.findByTestId("mcp-copy-token")).toHaveTextContent("Copy token");
  });

  it("blocks the write scope until the admin switch is on", async () => {
    const user = userEvent.setup();
    render(<McpServerSection />);
    await screen.findByTestId("mcp-endpoint");
    const writeScope = (await screen.findByTestId("mcp-token-write-scope")) as HTMLInputElement;
    expect(writeScope.disabled).toBe(true);

    await user.click(screen.getByTestId("mcp-write-toggle"));
    expect(api.setMcpWriteEnabled).toHaveBeenCalledWith(true);
    await waitFor(() =>
      expect(api.fetchMcpStatus).toHaveBeenCalledTimes(2)
    );
  });

  it("rotates and revokes tokens through the one-time secret flow", async () => {
    const user = userEvent.setup();
    render(<McpServerSection />);
    await screen.findByTestId("mcp-endpoint");

    await user.click(await screen.findByTestId("mcp-rotate-tok-1"));
    expect(api.rotateMcpToken).toHaveBeenCalledWith("tok-1");
    expect(await screen.findByTestId("mcp-minted-token")).toHaveTextContent(
      "rotated-secret"
    );

    await user.click(screen.getByTestId("mcp-revoke-tok-1"));
    expect(api.revokeMcpToken).toHaveBeenCalledWith("tok-1");
  });

  it("shows the generic client snippet with a token placeholder", async () => {
    const user = userEvent.setup();
    render(<McpServerSection />);
    await screen.findByTestId("mcp-endpoint");
    expect(await screen.findByTestId("mcp-snippet")).toHaveTextContent("mcp-remote");
    await user.click(screen.getByText("Generic HTTP"));
    await waitFor(() =>
      expect(screen.getByTestId("mcp-snippet")).toHaveTextContent("streamable-http")
    );
    expect(screen.getByTestId("mcp-snippet")).toHaveTextContent("YOUR_MCP_TOKEN");
  });
});
