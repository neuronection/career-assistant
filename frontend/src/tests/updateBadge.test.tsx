import { render, screen } from "@testing-library/react";
import { fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as versionApi from "@/api/version";
import { UpdateBadge, clearUpdateCheckCache } from "@/components/UpdateBadge";

vi.mock("@/api/version", () => ({
  getUpdateCheck: vi.fn(),
}));

const mockedVersion = vi.mocked(versionApi);

const AVAILABLE: versionApi.UpdateCheck = {
  current_version: "0.16.0",
  latest_version: "v0.17.0",
  update_available: true,
  release_url: "https://github.com/neuronection/career-assistant/releases/tag/v0.17.0",
  checked_at: "2026-10-30T00:00:00Z",
  error: null,
};

const UP_TO_DATE: versionApi.UpdateCheck = {
  ...AVAILABLE,
  update_available: false,
  latest_version: "v0.16.0",
};

describe("UpdateBadge", () => {
  beforeEach(() => {
    mockedVersion.getUpdateCheck.mockReset();
    clearUpdateCheckCache();
  });

  afterEach(() => {
    clearUpdateCheckCache();
  });

  it("renders the version without a dot when up to date", async () => {
    mockedVersion.getUpdateCheck.mockResolvedValueOnce(UP_TO_DATE);
    const { container } = render(<UpdateBadge version="0.16.0" />);
    await waitFor(() => expect(mockedVersion.getUpdateCheck).toHaveBeenCalled());
    expect(screen.getByText("v0.16.0")).toBeTruthy();
    expect(container.querySelector(".rounded-full")).toBeNull();
  });

  it("shows the accent dot when an update is offered", async () => {
    mockedVersion.getUpdateCheck.mockResolvedValueOnce(AVAILABLE);
    const { container } = render(<UpdateBadge version="0.16.0" />);
    await waitFor(() => expect(container.querySelector(".rounded-full")).not.toBeNull());
  });

  it("opens a popover with release links on click", async () => {
    mockedVersion.getUpdateCheck.mockResolvedValueOnce(AVAILABLE);
    render(<UpdateBadge version="0.16.0" />);
    await waitFor(() => expect(screen.getByRole("button")).toBeTruthy());
    fireEvent.click(screen.getByRole("button"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("v0.17.0");
    const links = Array.from(dialog.querySelectorAll("a")).map((a) =>
      a.getAttribute("href"),
    );
    expect(links).toContain(AVAILABLE.release_url);
    expect(links.some((href) => href?.endsWith("/releases"))).toBe(true);
  });

  it("closes the popover on Escape", async () => {
    mockedVersion.getUpdateCheck.mockResolvedValueOnce(AVAILABLE);
    render(<UpdateBadge version="0.16.0" />);
    fireEvent.click(await screen.findByRole("button"));
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("renders no popover controls when the check fails (fail-closed)", async () => {
    mockedVersion.getUpdateCheck.mockRejectedValueOnce(new Error("offline"));
    render(<UpdateBadge version="0.16.0" />);
    await waitFor(() => expect(mockedVersion.getUpdateCheck).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
