import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JobSourcePresetDialog } from "@/components/settings/connectors/JobSourcePresetDialog";
import { JOB_SOURCE_PRESETS } from "@/config/jobSourcePresets";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

function renderDialog(
  overrides: Partial<Parameters<typeof JobSourcePresetDialog>[0]> = {},
) {
  const onAddPresets = vi.fn();
  const onCustom = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <JobSourcePresetDialog
      open
      onOpenChange={onOpenChange}
      onAddPresets={onAddPresets}
      onCustom={onCustom}
      {...overrides}
    />,
  );
  return { onAddPresets, onCustom, onOpenChange };
}

describe("JobSourcePresetDialog", () => {
  it("renders every preset grouped by provider", async () => {
    renderDialog();
    expect(await screen.findByTestId("job-source-presets")).toBeTruthy();
    for (const preset of JOB_SOURCE_PRESETS) {
      expect(screen.getByTestId(`preset-${preset.slug}`)).toBeTruthy();
    }
    expect(screen.getByTestId("preset-group-Recruitee")).toBeTruthy();
    expect(screen.getByTestId("preset-group-Workable")).toBeTruthy();
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

  it("multi-selects and bulk-adds the picked presets", async () => {
    const user = userEvent.setup();
    const { onAddPresets } = renderDialog();
    const ballys = screen.getByTestId("preset-ballysintralotsa");
    expect(ballys.getAttribute("aria-pressed")).toBe("false");
    await user.click(ballys);
    expect(ballys.getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByTestId("preset-skroutz"));
    expect(screen.getByTestId("presets-add")).not.toHaveProperty("disabled", true);
    await user.click(screen.getByTestId("presets-add"));
    expect(onAddPresets).toHaveBeenCalledTimes(1);
    const picked = onAddPresets.mock.calls[0][0] as { slug: string }[];
    expect(picked.map((entry) => entry.slug)).toEqual(["ballysintralotsa", "skroutz"]);
  });

  it("reports per-item outcomes and keeps failures selected for retry", async () => {
    const user = userEvent.setup();
    const { onAddPresets } = renderDialog();
    await screen.findByTestId("job-source-presets");
    const ballys = screen.getByTestId("preset-ballysintralotsa");
    const skroutz = screen.getByTestId("preset-skroutz");
    await user.click(ballys);
    await user.click(skroutz);
    onAddPresets.mockResolvedValueOnce([
      { preset: JOB_SOURCE_PRESETS.find((p) => p.slug === "ballysintralotsa"), ok: true },
      {
        preset: JOB_SOURCE_PRESETS.find((p) => p.slug === "skroutz"),
        ok: false,
        detail: "a source with this key already exists",
      },
    ]);
    await user.click(screen.getByTestId("presets-add"));
    const report = await screen.findByTestId("preset-report");
    expect(report.textContent).toContain("Skroutz");
    expect(report.textContent).toContain("already exists");
    expect(skroutz.getAttribute("aria-pressed")).toBe("true");
    expect(ballys.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders already-added presets as badges and never selects them", async () => {
    const user = userEvent.setup();
    const { onAddPresets } = renderDialog({ existingKeys: ["ballysintralotsa", "jobicy"] });
    const addedCard = await screen.findByTestId("preset-ballysintralotsa");
    expect(addedCard.getAttribute("disabled")).not.toBeNull();
    expect(screen.getByTestId("preset-added-ballysintralotsa")).toBeTruthy();
    await user.click(addedCard);
    expect(onAddPresets).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("preset-affideagreece"));
    await user.click(screen.getByTestId("presets-add"));
    const picked = onAddPresets.mock.calls[0][0] as { slug: string }[];
    expect(picked.map((entry) => entry.slug)).toEqual(["affideagreece"]);
  });

  it("falls back to the custom wizard", async () => {
    const user = userEvent.setup();
    const { onCustom } = renderDialog();
    await user.click(screen.getByTestId("preset-custom"));
    expect(onCustom).toHaveBeenCalled();
  });
});
