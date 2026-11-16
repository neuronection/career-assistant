import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import type { ConfigSummary, EffectiveAssignment } from "@/api/ai";
import {
  AI_CONFIG_SUMMARY_STALE_TIME_MS,
  resetConfigSummaryCache,
  useConfigSummary,
} from "@/hooks/useConfigSummary";
import { useAuthStore } from "@/stores/authStore";

const aiApi = vi.hoisted(() => ({
  fetchConfigSummary: vi.fn(),
}));

vi.mock("@/api/ai", () => ({
  fetchConfigSummary: aiApi.fetchConfigSummary,
}));

function assignment(source: string): EffectiveAssignment {
  return {
    task_type: "transcribe",
    source,
    provider_type: source === "unconfigured" ? "none" : "openai",
    model_name: source === "unconfigured" ? "not configured" : "whisper-1",
    api_base: "",
  };
}

function summary(source: string): ConfigSummary {
  return {
    tasks: [assignment(source)],
    can_manage_global: false,
    mock_allowed: false,
  };
}

function user(id: string) {
  return {
    id,
    email: `${id}@example.com`,
    full_name: id,
    is_active: true,
    is_admin: false,
  };
}

function Probe() {
  const { data, error, loading } = useConfigSummary();
  const source =
    data?.tasks.find((task) => task.task_type === "transcribe")?.source ?? "none";
  return (
    <span data-testid="probe">
      {`${loading ? "loading" : "idle"}|${source}|${error ? "error" : "ok"}`}
    </span>
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("useConfigSummary shared cache", () => {
  beforeEach(() => {
    aiApi.fetchConfigSummary.mockReset();
    resetConfigSummaryCache();
    useAuthStore.setState({ user: null });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useAuthStore.setState({ user: null });
  });

  it("keeps one summary per signed-in user", async () => {
    useAuthStore.setState({ user: user("u1") });
    aiApi.fetchConfigSummary.mockResolvedValueOnce(summary("user"));
    const first = render(<Probe />);
    await flush();
    expect(screen.getByTestId("probe")).toHaveTextContent("idle|user|ok");
    first.unmount();

    useAuthStore.setState({ user: user("u2") });
    aiApi.fetchConfigSummary.mockResolvedValueOnce(summary("unconfigured"));
    render(<Probe />);
    await flush();

    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("probe")).toHaveTextContent(
      "idle|unconfigured|ok",
    );
  });

  it("refetches once the five-minute stale window expires", async () => {
    let now = 1_700_000_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    aiApi.fetchConfigSummary.mockResolvedValue(summary("user"));

    const first = render(<Probe />);
    await flush();
    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(1);
    first.unmount();

    now += AI_CONFIG_SUMMARY_STALE_TIME_MS;
    render(<Probe />);
    await flush();

    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(2);
  });

  it("dedupes concurrent mounts into one in-flight request", async () => {
    let resolveRequest: (value: ConfigSummary) => void = () => {};
    aiApi.fetchConfigSummary.mockReturnValue(
      new Promise<ConfigSummary>((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(
      <>
        <Probe />
        <Probe />
      </>,
    );
    await flush();
    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRequest(summary("user"));
    });
    await flush();

    for (const probe of screen.getAllByTestId("probe")) {
      expect(probe).toHaveTextContent("idle|user|ok");
    }
  });

  it("ignores an old in-flight response after a reset", async () => {
    let resolveOld: (value: ConfigSummary) => void = () => {};
    aiApi.fetchConfigSummary
      .mockReturnValueOnce(
        new Promise<ConfigSummary>((resolve) => {
          resolveOld = resolve;
        }),
      )
      .mockResolvedValueOnce(summary("user"));

    render(<Probe />);
    await flush();
    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(1);

    await act(async () => {
      resetConfigSummaryCache();
    });
    await flush();
    expect(aiApi.fetchConfigSummary).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("probe")).toHaveTextContent("idle|user|ok");

    await act(async () => {
      resolveOld(summary("unconfigured"));
    });
    await flush();

    expect(screen.getByTestId("probe")).toHaveTextContent("idle|user|ok");
  });
});
