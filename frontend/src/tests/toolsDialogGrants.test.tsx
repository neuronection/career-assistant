import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsDialog } from "@/components/chat/ToolsDialog";
import * as aiApi from "@/api/ai";
import { initI18n } from "@/lib/i18n";

vi.mock("@/api/ai", () => ({
  fetchAiTools: vi.fn(),
  grantAiTool: vi.fn(),
  revokeAiToolGrant: vi.fn(),
}));

const stateChanging = {
  key: "cv_set_template",
  title: "Set template",
  description: "Switch the CV template.",
  scope: "write",
  risk_class: "state-changing",
  granted: false,
  audiences: ["chat"],
  cost_hint: null,
  requires_user: true,
  input_schema: null,
  builtin: true,
  kind: "tool" as const,
  hitl: false,
};

const destructive = {
  key: "wipe_source",
  title: "Wipe source",
  description: "Destructively wipe one source.",
  scope: "write",
  risk_class: "destructive",
  granted: false,
  audiences: ["chat"],
  cost_hint: null,
  requires_user: true,
  input_schema: null,
  builtin: false,
  kind: "tool" as const,
  hitl: false,
};

const readOnly = {
  key: "search_jobs",
  title: "Searching the job catalog",
  description: "Full-text search over the job catalog.",
  scope: "read",
  risk_class: "read-only",
  audiences: ["chat"],
  cost_hint: null,
  requires_user: false,
  input_schema: null,
  builtin: true,
  kind: "tool" as const,
  hitl: false,
};

function renderDialog() {
  return render(
    <MemoryRouter>
      <ToolsDialog open onOpenChange={() => {}} />
    </MemoryRouter>,
  );
}

describe("ToolsDialog — the D20 consent surface", () => {
  beforeEach(async () => {
    await initI18n();
    vi.mocked(aiApi.fetchAiTools).mockReset().mockResolvedValue([
      readOnly,
      stateChanging,
      destructive,
    ]);
    vi.mocked(aiApi.grantAiTool).mockReset().mockResolvedValue(undefined);
    vi.mocked(aiApi.revokeAiToolGrant).mockReset().mockResolvedValue(undefined);
  });

  it("badges state-changing and destructive tools in the catalog", async () => {
    renderDialog();
    await screen.findByTestId("chat-tools-dialog");
    expect(await screen.findByText("Changes data")).toBeInTheDocument();
    expect(screen.getByText("Destructive")).toBeInTheDocument();
  });

  it("offers grants for state-changing tools only", async () => {
    renderDialog();
    await screen.findByTestId("chat-tools-dialog");
    const grants = await screen.findByTestId("chat-tools-grants");
    expect(grants).toHaveTextContent("Needs your enablement");
    expect(grants).toHaveTextContent("Set template");
    expect(grants.textContent).not.toContain("Wipe source");
    expect(grants.textContent).not.toContain("Searching the job catalog");
  });

  it("toggles a grant through the API", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByTestId("chat-tools-dialog");
    const row = await screen.findByTestId("tool-grant-cv_set_template");
    await user.click(row);
    await waitFor(() => expect(aiApi.grantAiTool).toHaveBeenCalledWith("cv_set_template"));

    await user.click(row);
    await waitFor(() =>
      expect(aiApi.revokeAiToolGrant).toHaveBeenCalledWith("cv_set_template"),
    );
  });

  it("snaps the toggle back when the grant is rejected", async () => {
    vi.mocked(aiApi.grantAiTool).mockRejectedValueOnce(new Error("rejected"));
    const user = userEvent.setup();
    renderDialog();
    await screen.findByTestId("chat-tools-dialog");
    const row = await screen.findByTestId("tool-grant-cv_set_template");
    await user.click(row);
    await waitFor(() => expect(aiApi.grantAiTool).toHaveBeenCalled());
    await waitFor(() =>
      expect(row).toHaveAttribute("aria-checked", "false"),
    );
  });
});
