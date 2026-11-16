import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StorageStatusCard } from "@/components/settings/StorageStatusCard";
import { Storage } from "@/pages/settings/Storage";
import { useAuthStore } from "@/stores/authStore";

const mocks = vi.hoisted(() => ({
  fetchStorageStatus: vi.fn(),
  desktop: { value: false },
}));

vi.mock("@/api/storage", () => ({
  fetchStorageStatus: (refresh?: boolean) => mocks.fetchStorageStatus(refresh),
}));

vi.mock("@/lib/desktop", () => ({
  isDesktop: () => mocks.desktop.value,
}));

function status(overrides: Record<string, unknown> = {}) {
  return {
    backend: "s3",
    entrypoint: "server",
    cloud_profile: "aws",
    bucket: "career-assistant-prod",
    container: null,
    region: "eu-north-1",
    endpoint_host: "s3.eu-north-1.amazonaws.com",
    prefix: "prod",
    sse: "AES256",
    max_object_mb: 1024,
    presign_ttl_seconds: 300,
    required: true,
    status: "ok",
    healthy: true,
    detail: null,
    checked_at: "2026-11-15T12:00:00Z",
    ...overrides,
  };
}

describe("StorageStatusCard", () => {
  beforeEach(() => {
    mocks.fetchStorageStatus.mockReset();
    mocks.desktop.value = false;
  });

  it("renders the resolved target as read-only facts", async () => {
    mocks.fetchStorageStatus.mockResolvedValue(status());
    render(<StorageStatusCard />);

    expect(await screen.findByText("career-assistant-prod")).toBeInTheDocument();
    expect(screen.getByText("Storage status")).toBeInTheDocument();
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(
      screen.getByText("eu-north-1 · s3.eu-north-1.amazonaws.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("AES256")).toBeInTheDocument();
    expect(screen.getByText("1024 MB")).toBeInTheDocument();
    expect(screen.getByText("300 s")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.queryByText(/X-Amz-/)).not.toBeInTheDocument();
    expect(screen.queryByText(/access key/i)).not.toBeInTheDocument();
  });

  it("renders nothing on desktop and never fetches the web-only surface", () => {
    mocks.desktop.value = true;
    render(<StorageStatusCard />);
    expect(screen.queryByTestId("settings-section-storage")).not.toBeInTheDocument();
    expect(mocks.fetchStorageStatus).not.toHaveBeenCalled();
  });

  it("shows a loading state before the first snapshot", async () => {
    let resolve: (value: ReturnType<typeof status>) => void = () => {};
    mocks.fetchStorageStatus.mockReturnValue(
      new Promise<ReturnType<typeof status>>((done) => {
        resolve = done;
      }),
    );
    render(<StorageStatusCard />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Reading deployment storage status…",
    );
    resolve(status());
    expect(await screen.findByText("career-assistant-prod")).toBeInTheDocument();
  });

  it("the test button forces a fresh probe and renders the new health row", async () => {
    mocks.fetchStorageStatus
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(
        status({
          status: "unavailable",
          healthy: false,
          detail: "StorageUnavailable",
          checked_at: "2026-11-15T12:00:30Z",
        }),
      );
    render(<StorageStatusCard />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.fetchStorageStatus).toHaveBeenLastCalledWith(true),
    );
  });

  it("shows read and mutation errors", async () => {
    mocks.fetchStorageStatus.mockRejectedValueOnce(new Error("storage status unavailable"));
    const first = render(<StorageStatusCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "storage status unavailable",
    );
    first.unmount();

    mocks.fetchStorageStatus
      .mockResolvedValueOnce(status())
      .mockRejectedValueOnce(new Error("probe failed"));
    render(<StorageStatusCard />);
    expect(await screen.findByText("Healthy")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("probe failed");
  });

  it("redirects a non-admin deep link to the account settings", () => {
    useAuthStore.setState({
      user: { id: "u-plain", email: "grace@example.com", full_name: "", is_admin: false },
    } as never);
    render(
      <MemoryRouter initialEntries={["/settings/storage"]}>
        <Routes>
          <Route path="/settings/storage" element={<Storage />} />
          <Route path="/settings/account" element={<p>account settings</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("account settings")).toBeInTheDocument();
    expect(mocks.fetchStorageStatus).not.toHaveBeenCalled();
  });

  it("redirects an admin desktop deep link to the account settings", () => {
    mocks.desktop.value = true;
    useAuthStore.setState({
      user: { id: "u-admin", email: "ada@example.com", full_name: "Ada", is_admin: true },
    } as never);
    render(
      <MemoryRouter initialEntries={["/settings/storage"]}>
        <Routes>
          <Route path="/settings/storage" element={<Storage />} />
          <Route path="/settings/account" element={<p>account settings</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("account settings")).toBeInTheDocument();
    expect(mocks.fetchStorageStatus).not.toHaveBeenCalled();
  });
});
