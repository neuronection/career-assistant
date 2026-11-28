import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ReferenceBankEmptyNotice } from "@/components/ReferenceBankEmptyNotice";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { Bootstrap } from "@/types/wire";
import type { User } from "@/api/auth";

const ADMIN = {
  id: "user-1",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_admin: true,
} as User;

const MEMBER = { ...ADMIN, id: "user-2", is_admin: false } as User;

function flags(overrides: Partial<Record<string, boolean>> = {}) {
  return {
    assessment: false,
    cv_templates: false,
    metrics: false,
    skill_packs: false,
    ...overrides,
  };
}

function setBanks(reference_banks: ReturnType<typeof flags>) {
  useBootstrapStore.setState({
    bootstrap: { reference_banks } as unknown as Bootstrap,
    loaded: true,
  });
}

function renderNotice(bank: "assessment" | "cv_templates" | "metrics" | "skill_packs") {
  return render(
    <MemoryRouter>
      <ReferenceBankEmptyNotice bank={bank} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  useAuthStore.setState({ user: ADMIN, loading: false, status: "authenticated", error: null });
  setBanks(flags());
});

describe("reference-bank empty notice", () => {
  it("names the missing bank and links admins to Data providers", () => {
    setBanks(flags({ assessment: true }));
    renderNotice("assessment");

    expect(screen.getByTestId("reference-bank-empty-assessment")).toBeInTheDocument();
    expect(screen.getByText(/assessment question bank/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Data providers/i })).toHaveAttribute(
      "href",
      "/settings/tools?section=sources"
    );
  });

  it("tells non-admins to ask an administrator without the action link", () => {
    useAuthStore.setState({ user: MEMBER, loading: false, status: "authenticated", error: null });
    setBanks(flags({ skill_packs: true }));
    renderNotice("skill_packs");

    expect(screen.getByText(/ask your administrator/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Data providers/i })).toBeNull();
  });

  it("renders nothing once the bank is loaded", () => {
    renderNotice("metrics");
    expect(screen.queryByTestId("reference-bank-empty-metrics")).toBeNull();
  });
});
