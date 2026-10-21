import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { expectNoA11yViolations } from "./a11y";
import { Layout } from "@/components/Layout";
import { SettingsShell } from "@/components/SettingsShell";
import { FormRow, SelectField, TextField } from "@/components/cv/formPrimitives";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useChatStore } from "@/stores/chatStore";

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: "user-1",
      email: "owner@example.com",
      full_name: "Owner",
      is_admin: true,
    } as never,
    loading: false,
    status: "authenticated",
    error: null,
    loadUser: async () => {},
  } as never);
  useChatStore.setState({
    chatMode: "bubble",
    chatModeChosen: true,
    sessions: [],
    loadSessions: async () => {},
  } as never);
  useBootstrapStore.setState({
    bootstrap: {
      onboarding_path: "explore",
      auth_mode: "open",
      ai: { configured: true, setup_dismissed: true },
      features: {},
    } as never,
    loaded: true,
  } as never);
});

describe("a11y: shared shells", () => {
  it("Layout chrome (sidebar, header, main) has no axe violations", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/rankings"]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/rankings" element={<p>Rankings content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText("Rankings content")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("the settings shell's nav and pane have no axe violations", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/settings/account"]}>
        <Routes>
          <Route path="/settings" element={<SettingsShell />}>
            <Route path="account" element={<p>Account pane</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText("Account pane")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("labelled form controls have no axe violations", async () => {
    const { container } = render(
      <form aria-label="Profile form">
        <FormRow label="Full name">
          <TextField label="Full name" value="" onChange={() => {}} />
        </FormRow>
        <FormRow label="Degree">
          <SelectField
            label="Degree"
            value="bachelor"
            options={[
              { value: "bachelor", label: "Bachelor" },
              { value: "master", label: "Master" },
            ]}
            onChange={() => {}}
          />
        </FormRow>
      </form>
    );
    await expectNoA11yViolations(container);
  });
});
