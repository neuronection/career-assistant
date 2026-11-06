import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { fetchMappingsAlerts, saveMappingsAlerts } from "@/api/mappings";
import { MappingAlertsCard } from "@/components/settings/MappingAlertsCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/mappings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/mappings")>();
  return {
    ...actual,
    fetchMappingsAlerts: vi.fn(),
    saveMappingsAlerts: vi.fn(),
  };
});

beforeEach(() => {
  vi.mocked(fetchMappingsAlerts).mockResolvedValue({ coverage_floor: 0.95 });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("mapping alert settings (plan 205 AD10)", () => {
  it("loads the floor and saves an edited value", async () => {
    const user = userEvent.setup();
    vi.mocked(saveMappingsAlerts).mockResolvedValue({ coverage_floor: 0.9 });
    render(<MappingAlertsCard />);

    const input = await screen.findByTestId("mappings-alerts-floor");
    expect((input as HTMLInputElement).value).toBe("0.95");
    await user.clear(input);
    await user.type(input, "0.9");
    await user.click(screen.getByTestId("mappings-alerts-save"));
    await waitFor(() => expect(saveMappingsAlerts).toHaveBeenCalledWith(0.9));
  });
});
