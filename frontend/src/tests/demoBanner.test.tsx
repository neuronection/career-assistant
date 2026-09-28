import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as authApi from "@/api/auth";
import * as instanceApi from "@/api/instance";
import { DemoBanner, clearDemoModeCache } from "@/components/DemoBanner";
import { SessionGate } from "@/components/SessionGate";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/api/instance", () => ({
  getInstanceConfig: vi.fn(),
}));

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return {
    ...actual,
    fetchMe: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  };
});

const mockedInstance = vi.mocked(instanceApi);

const DEMO_CONFIG: instanceApi.InstanceConfig = {
  demo_mode: true,
  auth_mode: "authenticated",
  registration_enabled: false,
};

describe("DemoBanner (identity-auth §13)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearDemoModeCache();
    useAuthStore.setState({
      user: null,
      loading: false,
      status: "anonymous",
      error: null,
      boot: vi.fn().mockResolvedValue(false),
    });
  });

  it("renders the 'Demo — synthetic data' badge on a demo instance", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue(DEMO_CONFIG);
    render(<DemoBanner />);
    expect(await screen.findByText("Demo — synthetic data")).toBeInTheDocument();
    expect(
      screen.getByText("This instance runs on fictional data and resets periodically."),
    ).toBeInTheDocument();
  });

  it("renders nothing when the instance is not a demo", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...DEMO_CONFIG,
      demo_mode: false,
    });
    const { container } = render(<DemoBanner />);
    await waitFor(() => {
      expect(mockedInstance.getInstanceConfig).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("fails closed to no badge when the instance config cannot be read", async () => {
    mockedInstance.getInstanceConfig.mockRejectedValue(new Error("offline"));
    const { container } = render(<DemoBanner />);
    await waitFor(() => {
      expect(mockedInstance.getInstanceConfig).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("is visible through the boot gate BEFORE login (demo vs not)", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue(DEMO_CONFIG);
    vi.mocked(authApi.fetchMe).mockRejectedValue(new Error("not-authenticated"));
    render(
      <SessionGate>
        <div>the app</div>
      </SessionGate>,
    );
    // The login gate is up (anonymous) — and the demo badge rides with it.
    expect(await screen.findByText("Demo — synthetic data")).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();

    clearDemoModeCache();
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...DEMO_CONFIG,
      demo_mode: false,
    });
    const second = render(
      <SessionGate>
        <div>the app</div>
      </SessionGate>,
    );
    await waitFor(() => {
      expect(mockedInstance.getInstanceConfig).toHaveBeenCalledTimes(2);
    });
    expect(second.container.textContent).not.toContain("Demo — synthetic data");
  });
});
