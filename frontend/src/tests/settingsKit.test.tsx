import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Bell, Mail } from "lucide-react";

import { expectNoA11yViolations } from "@/tests/a11y";
import { SaveStateIndicator } from "@/components/settings/saveState";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { SettingsPage } from "@/components/settings/SettingsPage";
import {
  useOptimisticToggle,
  useSettingsDraft,
} from "@/components/settings/useSettingsDraft";
import { SettingsShell as AppSettingsShell, toLibraryNav } from "@/components/SettingsShell";
import { useAuthStore } from "@/stores/authStore";
import { MemoryRouter, Route, Routes } from "react-router-dom";

describe("SaveStateIndicator", () => {
  it("renders nothing when idle", () => {
    const { container } = render(<SaveStateIndicator state="idle" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("labels saved, saving and dirty states", () => {
    const { rerender } = render(<SaveStateIndicator state="saved" />);
    expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Saved");
    rerender(<SaveStateIndicator state="saving" />);
    expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Saving…");
    rerender(<SaveStateIndicator state="dirty" />);
    expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Unsaved changes");
  });

  it("error state offers retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<SaveStateIndicator state="error" error="boom" onRetry={onRetry} />);
    expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Couldn't save");
    expect(screen.getByText("Retry")).toBeInTheDocument();
    await user.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("has no axe violations", async () => {
    const { container } = render(<SaveStateIndicator state="saving" />);
    await expectNoA11yViolations(container);
  });
});

describe("SettingsSectionCard", () => {
  it("renders title, description, badge slots and testids", () => {
    render(
      <SettingsSectionCard
        name="email"
        title="Email"
        description="Alerts and the weekly digest."
        icon={Mail}
        badges={<span data-testid="custom-badge">Active</span>}
        summary={<span data-testid="chip">Weekly digest on</span>}
        footer={<button type="button">Save</button>}
      >
        <p>body</p>
      </SettingsSectionCard>,
    );
    expect(screen.getByTestId("settings-section-email")).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("Alerts and the weekly digest.")).toBeInTheDocument();
    expect(screen.getByTestId("custom-badge")).toBeInTheDocument();
    expect(screen.getByTestId("chip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-section-email-toggle")).toBeNull();
  });

  it("adminOnly renders the Admin badge", () => {
    render(
      <SettingsSectionCard name="smtp" title="Email transport" adminOnly>
        <p />
      </SettingsSectionCard>,
    );
    expect(screen.getByTestId("settings-section-smtp-admin")).toHaveTextContent("Admin");
  });

  it("collapsible body toggles with aria-expanded", async () => {
    const user = userEvent.setup();
    render(
      <SettingsSectionCard name="smtp" title="Email transport" collapsible defaultOpen={false}>
        <p>secret knobs</p>
      </SettingsSectionCard>,
    );
    const toggle = screen.getByTestId("settings-section-smtp-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("settings-section-smtp-body")).toBeInTheDocument();
  });

  it("danger variant renders the title in danger tone", () => {
    render(
      <SettingsSectionCard name="delete" title="Delete account" variant="danger">
        <p />
      </SettingsSectionCard>,
    );
    expect(screen.getByText("Delete account")).toHaveClass(
      "text-[var(--as-danger)]",
    );
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <SettingsSectionCard
        name="email"
        title="Email"
        description="Alerts."
        icon={Mail}
        saveState="saved"
      >
        <input aria-label="Address" />
      </SettingsSectionCard>,
    );
    await expectNoA11yViolations(container);
  });
});

describe("SettingsPage", () => {
  it("renders header with icon, title and description", () => {
    render(
      <SettingsPage icon={Bell} title="Notifications" description="How we reach you.">
        <p>content</p>
      </SettingsPage>,
    );
    expect(screen.getByTestId("settings-page")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByText("How we reach you.")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-page-rail")).toBeNull();
  });

  it("renders anchor rail links for sections and jumps on click", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    const target = document.createElement("section");
    target.id = "s-kinds";
    document.body.appendChild(target);
    target.scrollIntoView = scrollIntoView;
    render(
      <SettingsPage
        title="Notifications"
        sections={[
          { id: "s-channels", label: "Channels" },
          { id: "s-kinds", label: "Notification kinds" },
        ]}
      >
        <p>content</p>
      </SettingsPage>,
    );
    expect(screen.getByTestId("settings-page-rail")).toBeInTheDocument();
    expect(screen.getByTestId("settings-page-rail-s-channels")).toHaveAttribute(
      "href",
      "#s-channels",
    );
    await user.click(screen.getByTestId("settings-page-rail-s-kinds"));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("settings-page-rail-s-kinds")).toHaveAttribute(
      "aria-current",
      "true",
    );
    target.remove();
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <SettingsPage
        icon={Bell}
        title="Notifications"
        description="How we reach you."
        sections={[{ id: "s-channels", label: "Channels" }]}
      >
        <section id="s-channels">
          <h2>Channels</h2>
        </section>
      </SettingsPage>,
    );
    await expectNoA11yViolations(container);
  });
});

function DraftHarness({
  initial,
  onSave,
  mode = "manual",
  isValid,
}: {
  initial: { address: string };
  onSave: (payload: { address: string }) => Promise<void>;
  mode?: "manual" | "autosave";
  isValid?: (draft: { address: string }) => boolean;
}) {
  const draft = useSettingsDraft({
    initial,
    buildPayload: (value) => (value.address ? { address: value.address } : null),
    onSave,
    mode,
    delay: 500,
    isValid,
  });
  return (
    <div>
      <output data-testid="state">{draft.state}</output>
      <output data-testid="dirty">{String(draft.dirty)}</output>
      <input
        aria-label="Address"
        value={draft.draft.address}
        onChange={(event) =>
          draft.setDraft((prev) => ({ ...prev, address: event.target.value }))
        }
      />
      <button type="button" onClick={() => void draft.save()}>
        save
      </button>
    </div>
  );
}

describe("SettingsShell glue (app)", () => {
  it("maps registry rows to library nav items with section labels", () => {
    const t = (key: string) => `t:${key}` as never;
    const mapped = toLibraryNav(
      [
        { to: "/settings/account", icon: Bell, labelKey: "a", descriptionKey: "b", sectionKey: "personal" },
        { to: "/settings/tools", icon: Bell, labelKey: "c", sectionKey: "aiTools" },
      ],
      t as never,
    );
    expect(mapped).toEqual([
      {
        id: "/settings/account",
        icon: Bell,
        label: "t:a",
        description: "t:b",
        section: "t:settingsNav.section.personal",
      },
      {
        id: "/settings/tools",
        icon: Bell,
        label: "t:c",
        description: undefined,
        section: "t:settingsNav.section.aiTools",
      },
    ]);
  });

  it("renders the shell with non-admin nav (admin-only entries filtered)", async () => {
    useAuthStore.setState({
      user: { id: "u1", email: "a@b.c", full_name: "A", is_admin: false } as never,
    } as never);
    const { container } = render(
      <MemoryRouter initialEntries={["/settings/account"]}>
        <Routes>
          <Route path="/settings" element={<AppSettingsShell />}>
            <Route path="account" element={<p>account body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(
      container.querySelectorAll('[data-as="settings-shell-navitem"]').length
    ).toBe(4);
    expect(screen.getByText("account body")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});

describe("useSettingsDraft", () => {
  it("tracks dirty, saves explicitly in manual mode, never PUTs untouched drafts", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<DraftHarness initial={{ address: "a@b.c" }} onSave={onSave} />);
    expect(screen.getByTestId("state")).toHaveTextContent("idle");
    await user.click(screen.getByRole("button", { name: "save" }));
    expect(onSave).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Address"), "d");
    expect(screen.getByTestId("dirty")).toHaveTextContent("true");
    expect(screen.getByTestId("state")).toHaveTextContent("dirty");
    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
    expect(onSave).toHaveBeenCalledWith({ address: "a@b.cd" });
    await user.click(screen.getByRole("button", { name: "save" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("invalid drafts block save", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <DraftHarness
        initial={{ address: "a@b.c" }}
        onSave={onSave}
        isValid={(value) => value.address.includes("@")}
      />,
    );
    await user.clear(screen.getByLabelText("Address"));
    await user.type(screen.getByLabelText("Address"), "nope");
    await user.click(screen.getByRole("button", { name: "save" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByTestId("state")).toHaveTextContent("dirty");
  });

  it("failed save surfaces the error state and a retry succeeds", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockRejectedValueOnce(new Error("nope")).mockResolvedValueOnce(undefined);
    render(<DraftHarness initial={{ address: "" }} onSave={onSave} />);
    await user.type(screen.getByLabelText("Address"), "a@b.c");
    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("error"));
    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("saved"));
  });

  it("external initial changes adopt while clean and are refused while dirty", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <DraftHarness initial={{ address: "a@b.c" }} onSave={onSave} />,
    );
    rerender(<DraftHarness initial={{ address: "fresh@b.c" }} onSave={onSave} />);
    expect(screen.getByLabelText("Address")).toHaveValue("fresh@b.c");
    expect(screen.getByTestId("state")).toHaveTextContent("idle");

    await user.type(screen.getByLabelText("Address"), "!");
    rerender(<DraftHarness initial={{ address: "newer@b.c" }} onSave={onSave} />);
    expect(screen.getByLabelText("Address")).toHaveValue("fresh@b.c!");
    expect(screen.getByTestId("dirty")).toHaveTextContent("true");
  });

  it("a draft whose payload is null is never dirty", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<DraftHarness initial={{ address: "a@b.c" }} onSave={onSave} />);
    await user.clear(screen.getByLabelText("Address"));
    expect(screen.getByTestId("dirty")).toHaveTextContent("false");
    expect(screen.getByTestId("state")).toHaveTextContent("idle");
    await user.click(screen.getByRole("button", { name: "save" }));
    expect(onSave).not.toHaveBeenCalled();
  });

  describe("autosave mode", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("debounces saves (untouched drafts never PUT)", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      render(<DraftHarness initial={{ address: "" }} onSave={onSave} mode="autosave" />);
      const input = screen.getByLabelText("Address");
      await act(async () => {
        fireEvent.change(input, { target: { value: "x" } });
        fireEvent.change(input, { target: { value: "xy" } });
        await vi.advanceTimersByTimeAsync(600);
      });
      expect(onSave).toHaveBeenCalledTimes(1);
      expect(onSave).toHaveBeenCalledWith({ address: "xy" });
    });

    it("clears the pending timer on unmount", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const { unmount } = render(
        <DraftHarness initial={{ address: "" }} onSave={onSave} mode="autosave" />,
      );
      await act(async () => {
        fireEvent.change(screen.getByLabelText("Address"), { target: { value: "x" } });
      });
      unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(600);
      });
      expect(onSave).not.toHaveBeenCalled();
    });
  });
});

function ToggleHarness({ commit }: { commit: (next: boolean) => Promise<unknown> }) {
  const { toggle, valueOf, isFailing } = useOptimisticToggle();
  const persisted = true;
  return (
    <div>
      <output data-testid="value">{String(valueOf("k", persisted))}</output>
      <output data-testid="failing">{String(isFailing("k"))}</output>
      <button
        type="button"
        onClick={() => void toggle("k", !valueOf("k", persisted), () => commit(!persisted))}
      >
        toggle
      </button>
    </div>
  );
}

describe("useOptimisticToggle", () => {
  it("flips optimistically and keeps the value when the commit lands", async () => {
    const user = userEvent.setup();
    const commit = vi.fn().mockResolvedValue(undefined);
    render(<ToggleHarness commit={commit} />);
    expect(screen.getByTestId("value")).toHaveTextContent("true");
    await user.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByTestId("value")).toHaveTextContent("false");
    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("failing")).toHaveTextContent("false");
  });

  it("rolls back and flags failure when the commit rejects", async () => {
    const user = userEvent.setup();
    const commit = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(undefined);
    render(<ToggleHarness commit={commit} />);
    await user.click(screen.getByRole("button", { name: "toggle" }));
    await waitFor(() => expect(screen.getByTestId("failing")).toHaveTextContent("true"));
    expect(screen.getByTestId("value")).toHaveTextContent("true");
    await user.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByTestId("value")).toHaveTextContent("false");
    await waitFor(() => expect(screen.getByTestId("failing")).toHaveTextContent("false"));
  });
});
