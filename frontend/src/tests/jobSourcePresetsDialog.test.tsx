import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobSourcePresetDialog } from "@/components/settings/connectors/JobSourcePresetDialog";
import { JOB_SOURCE_PRESETS } from "@/config/jobSourcePresets";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

function renderDialog(overrides: Partial<Parameters<typeof JobSourcePresetDialog>[0]> = {}) {
  const onPick = vi.fn();
  const onCustom = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <JobSourcePresetDialog
      open
      onOpenChange={onOpenChange}
      onPick={onPick}
      onCustom={onCustom}
      {...overrides}
    />,
  );
  return { onPick, onCustom, onOpenChange };
}

describe("JobSourcePresetDialog", () => {
  it("renders every preset grouped by provider", async () => {
    renderDialog();
    expect(await screen.findByTestId("job-source-presets")).toBeTruthy();
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(screen.getByTestId(`preset-${preset.slug}`)).toBeTruthy();
    }
    expect(screen.getByTestId("preset-group-Recruitee")).toBeTruthy();
    expect(screen.getByTestId("preset-group-Teamtailor")).toBeTruthy();
    expect(screen.getByTestId("preset-group-Remote boards")).toBeTruthy();
  });

  it("filters by company name", async () => {
    const user = userEvent.setup();
    renderDialog();
    const search = screen.getByTestId("preset-search").querySelector("input")!;
    await user.type(search, "affidea");
    expect(screen.getByTestId("preset-affideagreece")).toBeTruthy();
    expect(screen.queryByTestId("preset-ballysintralotsa")).toBeNull();
    await user.clear(search);
    await user.type(search, "zzz-nothing");
    expect(screen.getByText("toolsSettings.connectors.presets.noMatches")).toBeTruthy();
  });

  it("filters by category tab", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(
      screen.getByRole("tab", { name: "toolsSettings.connectors.presets.filterRemote" }),
    );
    expect(screen.getByTestId("preset-jobicy")).toBeTruthy();
    expect(screen.queryByTestId("preset-ballysintralotsa")).toBeNull();
  });

  it("emits the picked preset and the custom fallback", async () => {
    const user = userEvent.setup();
    const { onPick, onCustom } = renderDialog();
    await user.click(screen.getByTestId("preset-ballysintralotsa"));
    expect(onPick).toHaveBeenCalledWith(
      expect.objectContaining({
        slug: "ballysintralotsa",
        connectorKey: "recruitee",
        config: { company: "ballysintralotsa" },
      }),
    );
    await user.click(screen.getByTestId("preset-custom"));
    expect(onCustom).toHaveBeenCalled();
  });
});
