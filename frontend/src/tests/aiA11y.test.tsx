import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { expectNoA11yViolations } from "@/tests/a11y";
import { AIConfig } from "@/pages/settings/AIConfig";
import { DictationUnavailable } from "@/components/ui/dictation";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/ai")>();
  return {
    ...actual,
    fetchConfigSummary: vi.fn().mockResolvedValue({
      can_manage_global: true,
      mock_allowed: false,
      tasks: [],
    }),
    fetchProviders: vi.fn().mockResolvedValue([]),
    fetchAssignments: vi.fn().mockResolvedValue([]),
    fetchAllModels: vi.fn().mockResolvedValue([]),
    fetchTasks: vi.fn().mockResolvedValue([]),
    fetchProviderPresets: vi.fn().mockResolvedValue({}),
  };
});

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: "user-1",
      email: "owner@example.com",
      full_name: "Owner",
      is_admin: true,
      is_active: true,
    },
  });
});

describe("a11y: scoped AI configuration + dictation notice", () => {
  it("personal AI configuration has no axe violations", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/settings/ai"]}>
        <AIConfig />
      </MemoryRouter>
    );
    expect(
      await screen.findByRole("heading", { name: "My AI Configuration" })
    ).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("instance AI configuration has no axe violations", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/settings/ai-admin"]}>
        <AIConfig scope="system" />
      </MemoryRouter>
    );
    expect(
      await screen.findByRole("heading", { name: "Instance AI Configuration" })
    ).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("the dismissible dictation notice is clean at 320px", async () => {
    const { container } = render(
      <div style={{ width: 320 }}>
        <DictationUnavailable
          label="Dictation unavailable"
          detail="No speech-to-text model is assigned."
          action={{ label: "Open AI settings", onClick: () => {} }}
          onDismiss={() => {}}
          dismissLabel="Dismiss"
        />
      </div>
    );
    await expectNoA11yViolations(container);
  });
});
