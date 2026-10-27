import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as rulesApi from "@/api/companyRules";
import {
  acceptSuggestion,
  deleteExclusion,
  dismissSuggestion,
  saveThresholds,
  setAliasState,
  type MatchPairRow,
  type MergeSuggestionRow,
  type OrgAliasRow,
  type OrgExclusionRow,
  type OrgRow,
} from "@/api/companyRules";
import { CompanyRules } from "@/pages/settings/CompanyRules";

vi.mock("@/components/ui", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/components/ui")>();
  const FakeCombobox = (props: { value?: string; onChange: (v: string) => void }) => (
    <input
      data-testid="rules-org-picker"
      value={props.value ?? ""}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
  return { ...mod, SearchableDropdown: FakeCombobox };
});

vi.mock("@/api/companyRules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/companyRules")>();
  return {
    ...actual,
    fetchOrganizations: vi.fn(),
    fetchAliasRows: vi.fn(),
    addAlias: vi.fn(),
    removeAlias: vi.fn(),
    setAliasState: vi.fn(),
    fetchExclusions: vi.fn(),
    createExclusion: vi.fn(),
    deleteExclusion: vi.fn(),
    fetchSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    dismissSuggestion: vi.fn(),
    fetchPairs: vi.fn(),
    fetchThresholds: vi.fn(),
    saveThresholds: vi.fn(),
  };
});

const mocked = vi.mocked(rulesApi);

const ORG: OrgRow = {
  id: "org-1",
  key: "acme-cloud",
  name: "Acme Cloud",
  domain: "acme.example",
  aliases: ["Acme Cloud Ltd"],
  status: "active",
  posting_count: 3,
};

const ALIAS_ROWS: OrgAliasRow[] = [
  {
    id: "alias-1",
    alias: "Acme Cloud Ltd",
    alias_key: "acme cloud ltd",
    source: "llm",
    state: "active",
    created_by: "triage",
    created_at: "2026-10-27T00:00:00Z",
  },
];

const EXCLUSIONS: OrgExclusionRow[] = [
  {
    id: "ex-1",
    label: "confidential",
    label_key: "confidential",
    org_id: null,
    org: null,
    reason: "quality",
    source: "seed",
    created_by: "system",
    created_at: "2026-10-27T00:00:00Z",
  },
  {
    id: "ex-2",
    label: "Acme Clouds",
    label_key: "acme clouds",
    org_id: "org-1",
    org: { id: "org-1", key: "acme-cloud", name: "Acme Cloud", status: "active" },
    reason: "suggestion dismissed",
    source: "dismiss",
    created_by: "admin",
    created_at: "2026-10-27T00:00:00Z",
  },
];

const SUGGESTION: MergeSuggestionRow = {
  id: "sug-1",
  label: "Acme Cloud Ltd",
  score: 0.5,
  reason: "llm:uncertain",
  status: "open",
  evidence: { confidence: 0.5 },
  org_a: { id: "org-2", key: "acme-cloud-ltd", name: "Acme Cloud Ltd", status: "proposed" },
  org_b: { id: "org-1", key: "acme-cloud", name: "Acme Cloud", status: "active" },
  created_at: "2026-10-27T00:00:00Z",
};

const PAIR: MatchPairRow = {
  id: "pair-1",
  label: "P&G",
  status: "pending",
  verdict: null,
  confidence: null,
  evidence: { domain: "pg.com" },
  candidate: { id: "org-9", key: "procter-gamble", name: "Procter & Gamble", status: "active" },
  created_at: "2026-10-27T00:00:00Z",
};

describe("CompanyRules (plan 135 slice C)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.fetchSuggestions.mockResolvedValue([SUGGESTION]);
    mocked.fetchOrganizations.mockResolvedValue([ORG]);
    mocked.fetchAliasRows.mockResolvedValue(ALIAS_ROWS);
    mocked.fetchExclusions.mockResolvedValue(EXCLUSIONS);
    mocked.fetchPairs.mockResolvedValue([PAIR]);
    mocked.fetchThresholds.mockResolvedValue({ match: 0.9, gray_low: 0.45, llm_auto: 0.95 });
  });

  it("lists merge suggestions with both sides and the evidence reason", async () => {
    render(<CompanyRules />);
    const card = await screen.findByTestId("suggestion-card-sug-1");
    expect(card).toHaveTextContent("Acme Cloud Ltd");
    expect(card).toHaveTextContent("Acme Cloud");
    expect(card).toHaveTextContent("llm:uncertain");
  });

  it("accepting a suggestion calls accept and reloads", async () => {
    mocked.acceptSuggestion.mockResolvedValue({ id: "org-2", status: "deprecated" });
    render(<CompanyRules />);
    const button = await screen.findByTestId("suggestion-accept-sug-1");
    fireEvent.click(button);
    await waitFor(() => expect(acceptSuggestion).toHaveBeenCalledWith("sug-1"));
  });

  it("dismissing a suggestion calls dismiss (which writes the exclusion)", async () => {
    mocked.dismissSuggestion.mockResolvedValue({ id: "sug-1", status: "dismissed" });
    render(<CompanyRules />);
    const button = await screen.findByTestId("suggestion-dismiss-sug-1");
    fireEvent.click(button);
    await waitFor(() => expect(dismissSuggestion).toHaveBeenCalledWith("sug-1"));
  });

  it("the aliases tab loads rows for a picked org and can exclude one", async () => {
    mocked.setAliasState.mockResolvedValue({ ...ALIAS_ROWS[0], state: "excluded" });
    render(<CompanyRules />);
    fireEvent.click(await screen.findByRole("tab", { name: "Aliases" }));
    fireEvent.change(await screen.findByTestId("rules-org-picker"), {
      target: { value: "org-1" },
    });
    expect(await screen.findByTestId("alias-row-Acme Cloud Ltd")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("alias-toggle-alias-1"));
    await waitFor(() =>
      expect(setAliasState).toHaveBeenCalledWith("org-1", "alias-1", "excluded")
    );
  });

  it("the exclusions tab splits global and pair rows and deletes one", async () => {
    mocked.deleteExclusion.mockResolvedValue(undefined);
    render(<CompanyRules />);
    fireEvent.click(await screen.findByRole("tab", { name: "Exclusions" }));
    await waitFor(() => {
      expect(screen.getByTestId("exclusion-row-confidential")).toBeInTheDocument();
      expect(screen.getByTestId("exclusion-row-acme clouds")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("exclusion-remove-ex-1"));
    await waitFor(() => expect(deleteExclusion).toHaveBeenCalledWith("ex-1"));
  });

  it("the queue tab shows pending pairs", async () => {
    render(<CompanyRules />);
    fireEvent.click(await screen.findByRole("tab", { name: "Pending pairs" }));
    expect(await screen.findByTestId("pair-row-pair-1")).toBeInTheDocument();
    expect(screen.getByText(/Procter & Gamble/)).toBeInTheDocument();
  });

  it("thresholds load and save", async () => {
    mocked.saveThresholds.mockResolvedValue({ match: 0.92, gray_low: 0.45, llm_auto: 0.95 });
    render(<CompanyRules />);
    fireEvent.click(await screen.findByRole("tab", { name: "Thresholds" }));
    const input = await screen.findByTestId("threshold-match");
    fireEvent.change(input, { target: { value: "0.92" } });
    fireEvent.click(screen.getByTestId("thresholds-save"));
    await waitFor(() =>
      expect(saveThresholds).toHaveBeenCalledWith({
        match: 0.92,
        gray_low: 0.45,
        llm_auto: 0.95,
      })
    );
  });
});
