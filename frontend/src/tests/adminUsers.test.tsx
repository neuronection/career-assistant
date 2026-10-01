import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "@/api/admin";
import { AdminApiError, type AdminUser } from "@/api/admin";
import { Users } from "@/pages/settings/Users";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/admin")>();
  return {
    ...actual,
    fetchUsers: vi.fn(),
    patchUser: vi.fn(),
    resetUserPassword: vi.fn(),
    forceLogout: vi.fn(),
    updateInstanceMode: vi.fn(),
  };
});

vi.mock("@/api/instance", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/instance")>();
  return {
    ...actual,
    getInstanceConfig: vi.fn().mockResolvedValue({
      demo_mode: false,
      auth_mode: "authenticated",
      registration_enabled: true,
    }),
  };
});

const mocked = vi.mocked(adminApi);

const ME = {
  id: "u-admin",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  is_active: true,
  is_admin: true,
};

const USERS: AdminUser[] = [
  {
    ...ME,
    created_at: "2026-01-01T00:00:00Z",
    activity_count: 12,
  },
  {
    id: "u-plain",
    email: "grace@example.com",
    full_name: "",
    is_admin: false,
    is_active: false,
    created_at: "2026-02-01T00:00:00Z",
    activity_count: 0,
  },
];

describe("Users (shared AdminUserTable adoption, §12 admin UI)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: ME, loading: false, status: "authenticated", error: null });
    mocked.fetchUsers.mockResolvedValue(USERS);
    mocked.patchUser.mockResolvedValue(USERS[0]);
  });

  it("renders rows with the you-marker, activity count, role and status", async () => {
    render(<Users />);
    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("grace@example.com")).toBeInTheDocument();
    expect(screen.getByText("(you)")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Matches")).toBeInTheDocument();
    expect(screen.getAllByText("Admin").length).toBeGreaterThan(0);
    expect(screen.getAllByText("User").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
  });

  it("promote/demote and activate/deactivate persist sparse patches", async () => {
    render(<Users />);
    fireEvent.click(await screen.findByRole("button", { name: /^Demote$/ }));
    await waitFor(() =>
      expect(mocked.patchUser).toHaveBeenCalledWith("u-admin", { is_admin: false }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Disable$/ }));
    await waitFor(() =>
      expect(mocked.patchUser).toHaveBeenCalledWith("u-admin", { is_active: false }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Promote$/ }));
    await waitFor(() =>
      expect(mocked.patchUser).toHaveBeenCalledWith("u-plain", { is_admin: true }),
    );
    fireEvent.click(screen.getByRole("button", { name: /^Enable$/ }));
    await waitFor(() =>
      expect(mocked.patchUser).toHaveBeenCalledWith("u-plain", { is_active: true }),
    );
  });

  it("reset-password panel gates the submit below 10 characters", async () => {
    mocked.resetUserPassword.mockResolvedValue(undefined);
    render(<Users />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Reset password" }))[0]);
    const input = screen.getByLabelText("New password");
    const submit = screen.getByRole("button", { name: "Set password" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "short" } });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "short-enough-123" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mocked.resetUserPassword).toHaveBeenCalledWith("u-admin", "short-enough-123"),
    );
  });

  it("force logout targets the row user", async () => {
    mocked.forceLogout.mockResolvedValue(undefined);
    render(<Users />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Force logout" }))[1]);
    await waitFor(() => expect(mocked.forceLogout).toHaveBeenCalledWith("u-plain"));
  });

  it("guard-rail 403s surface as the friendly self message", async () => {
    mocked.patchUser.mockRejectedValue(
      new AdminApiError(403, "Admins cannot demote or deactivate themselves"),
    );
    render(<Users />);
    fireEvent.click(await screen.findByRole("button", { name: /^Demote$/ }));
    expect(
      await screen.findByText("You cannot change your own role or status."),
    ).toBeInTheDocument();
  });

  it("the last-admin guard rail maps to its own message", async () => {
    mocked.patchUser.mockRejectedValue(new AdminApiError(403, "Cannot remove the last admin"));
    render(<Users />);
    fireEvent.click(await screen.findByRole("button", { name: /^Demote$/ }));
    expect(
      await screen.findByText("The last admin cannot be demoted or deactivated."),
    ).toBeInTheDocument();
  });

  it("shows the loading state while the list is pending", async () => {
    mocked.fetchUsers.mockReturnValue(new Promise<AdminUser[]>(() => undefined));
    render(<Users />);
    expect(await screen.findByText("Loading users…")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mocked.fetchUsers.mockResolvedValue([]);
    render(<Users />);
    expect(await screen.findByText("No users")).toBeInTheDocument();
  });

  it("maps list failures to the generic message (no raw error text)", async () => {
    mocked.fetchUsers.mockRejectedValue(new AdminApiError(500, "Traceback …"));
    render(<Users />);
    expect(await screen.findByText("Something went wrong — try again.")).toBeInTheDocument();
    expect(screen.queryByText("Traceback …")).not.toBeInTheDocument();
  });
  it("drives the §4.5 instance transition through the api layer", async () => {
    mocked.updateInstanceMode.mockResolvedValue(undefined);
    mocked.fetchUsers.mockResolvedValueOnce([USERS[0]]);
    render(<Users />);
    await screen.findByRole("button", { name: /^Demote$/ });

    const submit = screen.getByRole("button", { name: /^Disable login$/ });
    fireEvent.click(submit);
    expect(mocked.updateInstanceMode).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "current-secret-pw" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mocked.updateInstanceMode).toHaveBeenCalledWith(
        "open",
        "current-secret-pw",
      ),
    );
  });
});
