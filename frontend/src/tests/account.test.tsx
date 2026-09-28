import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "@/api/admin";
import { Account } from "@/pages/settings/Account";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/admin")>();
  return {
    ...actual,
    listMySessions: vi.fn(),
    revokeMySession: vi.fn(),
    changeMyPassword: vi.fn(),
    deleteMyAccount: vi.fn(),
  };
});

const mocked = vi.mocked(adminApi);

function axiosFailure(status: number, detail: string): AxiosError {
  const response = {
    status,
    statusText: "Error",
    data: { detail },
    headers: {},
    config: {},
  } as unknown as AxiosResponse;
  return new AxiosError(
    `Request failed with status code ${status}`,
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    response,
  );
}

const SESSIONS: adminApi.UserSession[] = [
  {
    id: "fam-1",
    client_label: "Firefox on Linux",
    created_at: "2026-09-01T10:00:00Z",
    expires_at: "2026-10-01T10:00:00Z",
    revoked_at: null,
    current: true,
  },
  {
    id: "fam-2",
    client_label: "Phone",
    created_at: null,
    expires_at: "2026-10-01T10:00:00Z",
    revoked_at: null,
    current: false,
  },
  {
    id: "fam-3",
    client_label: "Old laptop",
    created_at: "2026-08-01T10:00:00Z",
    expires_at: "2026-09-01T10:00:00Z",
    revoked_at: "2026-08-15T10:00:00Z",
    current: false,
  },
];

const ME = {
  id: "u-admin",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  is_active: true,
  is_admin: true,
};

describe("Account (§12 account self-service)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: ME, loading: false, status: "authenticated", error: null });
    mocked.listMySessions.mockResolvedValue(SESSIONS);
    mocked.revokeMySession.mockResolvedValue(undefined);
    mocked.changeMyPassword.mockResolvedValue(ME);
    mocked.deleteMyAccount.mockResolvedValue(undefined);
  });

  it("lists sessions with the current marker and revoked state", async () => {
    render(<Account />);
    const rows = await screen.findAllByTestId("account-session");
    expect(rows).toHaveLength(3);
    expect(screen.getByText("Firefox on Linux")).toBeInTheDocument();
    expect(screen.getByText("(this device)")).toBeInTheDocument();
    expect(screen.getByText("Phone")).toBeInTheDocument();
    expect(screen.getByText("Signed out")).toBeInTheDocument();
  });

  it("revoking another device is confirmed first, then revoked and re-listed", async () => {
    render(<Account />);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out — Phone" }));
    const modal = screen.getByRole("dialog", { name: "Sign out this device?" });
    expect(mocked.revokeMySession).not.toHaveBeenCalled();
    fireEvent.click(within(modal).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mocked.revokeMySession).toHaveBeenCalledWith("fam-2"));
    expect(await screen.findByText("Device signed out.")).toBeInTheDocument();
    await waitFor(() => expect(mocked.listMySessions).toHaveBeenCalledTimes(2));
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("revoking the current device drops to the login screen", async () => {
    render(<Account />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Sign out — Firefox on Linux" }),
    );
    const modal = screen.getByRole("dialog", { name: "Sign out this device?" });
    expect(
      within(modal).getByText(
        "This is the device you are using — you will be returned to the login screen.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mocked.revokeMySession).toHaveBeenCalledWith("fam-1"));
    await waitFor(() => expect(useAuthStore.getState().status).toBe("anonymous"));
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("password change gates at 10 chars and keeps the caller signed in", async () => {
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "old-pass" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "short" },
    });
    const submit = screen.getByRole("button", { name: "Change password" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "long-enough-123" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mocked.changeMyPassword).toHaveBeenCalledWith("old-pass", "long-enough-123"),
    );
    expect(
      await screen.findByText("Password changed. Other devices were signed out."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("a wrong current password maps to the friendly message", async () => {
    mocked.changeMyPassword.mockRejectedValue(axiosFailure(403, "Invalid password"));
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "wrong" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "long-enough-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("That password is not correct.")).toBeInTheDocument();
  });

  it("account deletion requires the password and drops to the login screen", async () => {
    render(<Account />);
    const submit = screen.getByRole("button", { name: "Delete my account" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Confirm with your password"), {
      target: { value: "secret-1" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(mocked.deleteMyAccount).toHaveBeenCalledWith("secret-1"));
    await waitFor(() => expect(useAuthStore.getState().status).toBe("anonymous"));
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("deletion failure surfaces the message and stays signed in", async () => {
    mocked.deleteMyAccount.mockRejectedValue(axiosFailure(403, "Invalid password"));
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Confirm with your password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    expect(await screen.findByText("That password is not correct.")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("authenticated");
  });
});
