import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";

import {
  COMPANY_TABS,
  CompanyRules,
  parseCompanyTab,
} from "@/pages/settings/CompanyRules";
import { AIConfig, parseAITab } from "@/pages/settings/AIConfig";
import { ToolsConfig, parseToolsSection } from "@/pages/settings/ToolsConfig";

vi.mock("@/api/companyRules", () => ({
  fetchSuggestions: vi.fn().mockResolvedValue([]),
  fetchAliasRows: vi.fn().mockResolvedValue([]),
  fetchExclusions: vi.fn().mockResolvedValue([]),
  fetchOrganizations: vi.fn().mockResolvedValue([]),
  fetchPairs: vi.fn().mockResolvedValue([]),
  fetchThresholds: vi.fn().mockResolvedValue({ match: 0.9, gray_low: 0.55, llm_auto: 0.8 }),
  acceptSuggestion: vi.fn(),
  dismissSuggestion: vi.fn(),
  addAlias: vi.fn(),
  removeAlias: vi.fn(),
  setAliasState: vi.fn(),
  createExclusion: vi.fn(),
  deleteExclusion: vi.fn(),
  saveThresholds: vi.fn(),
}));

vi.mock("@/api/ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ai")>();
  return {
    ...actual,
    fetchConfigSummary: vi.fn().mockResolvedValue({
      can_manage_global: true,
      mock_allowed: true,
      tasks: [],
    }),
    fetchProviders: vi.fn().mockResolvedValue([]),
    fetchAssignments: vi.fn().mockResolvedValue([]),
    fetchAllModels: vi.fn().mockResolvedValue([]),
    fetchTasks: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/components/settings/WebSearchSection", () => ({
  WebSearchSection: () => null,
}));

vi.mock("@/components/settings/ConnectorsSection", () => ({
  ConnectorsSection: () => null,
}));

vi.mock("@/components/settings/RetrievalManagementSection", () => ({
  RetrievalManagementSection: () => <div data-testid="retrieval-section-probe" />,
}));

function LocationProbe() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <>
      <span data-testid="location-probe">{location.pathname + location.search}</span>
      <span data-testid="navigation-type">{navigationType}</span>
    </>
  );
}

function renderPage(initialEntry: string, page: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      {page}
      <LocationProbe />
    </MemoryRouter>,
  );
}

const probe = () => screen.getByTestId("location-probe").textContent;

describe("company rules tab params (pure helpers)", () => {
  it("COMPANY_TABS is the declared suggestions-first order", () => {
    expect([...COMPANY_TABS]).toEqual([
      "suggestions",
      "aliases",
      "exclusions",
      "queue",
      "thresholds",
    ]);
  });

  it("parseCompanyTab falls back to suggestions on missing or unknown values", () => {
    expect(parseCompanyTab(null)).toBe("suggestions");
    expect(parseCompanyTab("thresholds")).toBe("thresholds");
    expect(parseCompanyTab("bogus")).toBe("suggestions");
  });
});

describe("company rules tabs (URL-synced)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lands a ?tab=thresholds deep link on Thresholds", async () => {
    renderPage("/settings/companies?tab=thresholds", <CompanyRules />);
    expect(await screen.findByTestId("rules-thresholds")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Thresholds" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/companies?tab=thresholds");
  });

  it("strips an unknown tab param back to the canonical URL", async () => {
    renderPage("/settings/companies?tab=bogus", <CompanyRules />);
    await waitFor(() => expect(probe()).toBe("/settings/companies"));
    expect(screen.getByRole("tab", { name: "Merge suggestions" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("keeps a bare URL canonical with no rewrite on mount", async () => {
    renderPage("/settings/companies", <CompanyRules />);
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Merge suggestions" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
    expect(probe()).toBe("/settings/companies");
  });

  it("writes ?tab=aliases on click with replace navigation", async () => {
    const user = userEvent.setup();
    renderPage("/settings/companies", <CompanyRules />);
    await user.click(screen.getByRole("tab", { name: "Aliases" }));
    await waitFor(() => expect(probe()).toBe("/settings/companies?tab=aliases"));
    expect(screen.getByTestId("navigation-type")).toHaveTextContent("REPLACE");
    expect(screen.getByRole("tab", { name: "Aliases" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("ai config tabs (derived state)", () => {
  it("keeps a bare URL canonical with no rewrite on mount", async () => {
    renderPage("/settings/ai", <AIConfig />);
    expect(
      await screen.findByRole("tab", { name: "Providers" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(probe()).toBe("/settings/ai");
  });

  it("redirects the legacy ?tab=web deep link to the tools page", async () => {
    renderPage("/settings/ai?tab=web", <AIConfig />);
    await waitFor(() => expect(probe()).toBe("/settings/tools"));
  });

  it("strips an unknown tab param and lands on providers", async () => {
    renderPage("/settings/ai?tab=bogus", <AIConfig />);
    expect(
      await screen.findByRole("tab", { name: "Providers" }),
    ).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(probe()).toBe("/settings/ai"));
  });

  it("keeps a valid ?tab=models deep link intact", async () => {
    renderPage("/settings/ai?tab=models", <AIConfig />);
    expect(await screen.findByRole("tab", { name: "Models" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() => expect(probe()).toBe("/settings/ai?tab=models"));
  });
});

describe("tools sections (derived state)", () => {
  it("keeps a bare URL canonical with no rewrite on mount", () => {
    renderPage("/settings/tools", <ToolsConfig />);
    expect(screen.getByRole("tab", { name: "Web search" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/tools");
  });

  it("strips an unknown section param and lands on web search", () => {
    renderPage("/settings/tools?section=bogus", <ToolsConfig />);
    expect(screen.getByRole("tab", { name: "Web search" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/tools");
  });

  it("lands the legacy ?section=connectors deep link on mcp", () => {
    renderPage("/settings/tools?section=connectors", <ToolsConfig />);
    expect(screen.getByRole("tab", { name: "MCP" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/tools?section=mcp");
  });

  it("lands ?section=sources on the sources view", () => {
    renderPage("/settings/tools?section=sources", <ToolsConfig />);
    expect(screen.getByRole("tab", { name: "Sources" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(probe()).toBe("/settings/tools?section=sources");
  });

  it("lands ?section=retrieval on the retrieval management view", () => {
    renderPage("/settings/tools?section=retrieval", <ToolsConfig />);
    expect(screen.getByRole("tab", { name: "Retrieval" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("retrieval-section-probe")).toBeTruthy();
    expect(probe()).toBe("/settings/tools?section=retrieval");
  });
});

describe("tools section parse helper", () => {
  it("falls back to web-search on missing or unknown values", () => {
    expect(parseToolsSection(null)).toBe("web-search");
    expect(parseToolsSection("connectors")).toBe("mcp");
    expect(parseToolsSection("retrieval")).toBe("retrieval");
    expect(parseToolsSection("bogus")).toBe("web-search");
  });
});

describe("ai tab parse helper", () => {
  it("falls back to providers on missing or unknown values", () => {
    expect(parseAITab(null)).toBe("providers");
    expect(parseAITab("tasks")).toBe("tasks");
    expect(parseAITab("bogus")).toBe("providers");
  });
});
