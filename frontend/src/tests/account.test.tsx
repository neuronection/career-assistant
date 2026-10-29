import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as adminApi from "@/api/admin";
import * as backgroundJobsApi from "@/api/backgroundJobs";
import * as profilesApi from "@/api/profiles";
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
    logoutAllDevices: vi.fn(),
  };
});

vi.mock("@/api/backgroundJobs", () => ({
  requestExport: vi.fn(),
  fetchBackgroundJob: vi.fn(),
  downloadExport: vi.fn(),
  cancelBackgroundJob: vi.fn(),
  isTerminal: (job: { status: string }) =>
    ["succeeded", "failed", "cancelled"].includes(job.status),
}));

vi.mock("@/api/profiles", () => ({
  listProfiles: vi.fn(),
  createProfile: vi.fn(),
  patchProfile: vi.fn(),
  deleteProfile: vi.fn(),
}));

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

const PROFILES = [
  { id: "p-1", name: "Default", color: null, is_default: true },
  { id: "p-2", name: "Research", color: null, is_default: false },
];

describe("Account (§12 account self-service, plan 148)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: ME, loading: false, status: "authenticated", error: null });
    mocked.listMySessions.mockResolvedValue(SESSIONS);
    mocked.revokeMySession.mockResolvedValue(undefined);
    mocked.changeMyPassword.mockResolvedValue(ME);
    mocked.deleteMyAccount.mockResolvedValue(undefined);
    mocked.logoutAllDevices.mockResolvedValue(undefined);
    vi.mocked(profilesApi.listProfiles).mockResolvedValue(PROFILES);
    vi.mocked(profilesApi.createProfile).mockResolvedValue(PROFILES[1]);
    vi.mocked(profilesApi.patchProfile).mockResolvedValue(PROFILES[1]);
    vi.mocked(backgroundJobsApi.requestExport).mockResolvedValue("job-1");
    vi.mocked(backgroundJobsApi.downloadExport).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the identity header and the profile rows with badges", async () => {
    render(<Account />);
    expect(await screen.findByTestId("account-identity-name")).toHaveTextContent(
      "Ada Lovelace"
    );
    expect(screen.getByTestId("account-identity-email")).toHaveTextContent(
      "ada@example.com"
    );
    expect(screen.getByTestId("account-admin-badge")).toBeInTheDocument();
    const row = screen.getByTestId("account-profile-p-1");
    expect(within(row).getAllByText("Default").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("settings-section-delete-account")).toHaveClass(
      "border-[color-mix(in_srgb,var(--as-danger)_38%,var(--as-border))]"
    );
  });

  it("creates a profile from the identity card", async () => {
    const user = (await import("@testing-library/user-event")).userEvent.setup();
    render(<Account />);
    await user.type(await screen.findByTestId("new-profile-name"), "Research 2");
    await user.click(screen.getByTestId("create-profile"));
    await waitFor(() =>
      expect(profilesApi.createProfile).toHaveBeenCalledWith("Research 2")
    );
  });

  it("lists sessions with the current marker and revoked state", async () => {
    render(<Account />);
    const rows = await screen.findAllByTestId("account-session");
    expect(rows).toHaveLength(3);
    expect(screen.getByText("Firefox on Linux")).toBeInTheDocument();
    expect(screen.getByText("this device")).toBeInTheDocument();
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
    expect(await screen.findByTestId("sessions-message")).toHaveTextContent(
      "Device signed out."
    );
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

  it("sign-out-everywhere confirms and drops to the login screen", async () => {
    render(<Account />);
    fireEvent.click(await screen.findByTestId("logout-all"));
    const modal = screen.getByRole("dialog", { name: "Sign out on every device?" });
    fireEvent.click(within(modal).getByRole("button", { name: "Sign out everywhere" }));
    await waitFor(() => expect(mocked.logoutAllDevices).toHaveBeenCalled());
    await waitFor(() => expect(useAuthStore.getState().status).toBe("anonymous"));
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

  it("account deletion is armed behind the password, then drops to the login screen", async () => {
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Confirm with your password"), {
      target: { value: "secret-1" },
    });
    fireEvent.click(screen.getByTestId("delete-account-arm"));
    const confirm = screen.getByTestId("delete-account-confirm");
    expect(confirm).toHaveTextContent("Confirm delete");
    fireEvent.click(confirm);
    await waitFor(() => expect(mocked.deleteMyAccount).toHaveBeenCalledWith("secret-1"));
    await waitFor(() => expect(useAuthStore.getState().status).toBe("anonymous"));
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("cancelling the armed delete disarms without calling the API", async () => {
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Confirm with your password"), {
      target: { value: "secret-1" },
    });
    fireEvent.click(screen.getByTestId("delete-account-arm"));
    fireEvent.click(screen.getByTestId("delete-account-cancel"));
    expect(screen.queryByTestId("delete-account-confirm")).toBeNull();
    expect(mocked.deleteMyAccount).not.toHaveBeenCalled();
  });

  it("deletion failure surfaces the message and disarms", async () => {
    mocked.deleteMyAccount.mockRejectedValue(axiosFailure(403, "Invalid password"));
    render(<Account />);
    fireEvent.change(screen.getByLabelText("Confirm with your password"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByTestId("delete-account-arm"));
    fireEvent.click(screen.getByTestId("delete-account-confirm"));
    expect(await screen.findByText("That password is not correct.")).toBeInTheDocument();
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(screen.queryByTestId("delete-account-confirm")).toBeNull();
  });

  describe("data export", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("requests the export, polls to success and offers the download", async () => {
      vi.mocked(backgroundJobsApi.fetchBackgroundJob).mockResolvedValue({
        id: "job-1",
        kind: "export",
        status: "succeeded",
      } as never);
      render(<Account />);
      await act(async () => {
        await Promise.resolve();
      });
      fireEvent.click(screen.getByTestId("export-request"));
      expect(backgroundJobsApi.requestExport).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      fireEvent.click(screen.getByTestId("export-download"));
      expect(backgroundJobsApi.downloadExport).toHaveBeenCalledWith("job-1");
    });
  });
});
