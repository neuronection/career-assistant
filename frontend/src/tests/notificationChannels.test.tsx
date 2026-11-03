import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Notifications } from "@/pages/settings/Notifications";
import {
  broadcastAnnouncement,
  fetchEmailChannelConfig,
  fetchFeedTokens,
  fetchNotificationDeliveries,
  fetchPreferencesMatrix,
  fetchRules,
  fetchSearches,
  fetchWebhookChannelConfig,
  mintFeedToken,
  resetKindPreference,
  rotateFeedToken,
  setKindPreference,
  testWebhookChannel,
  updateEmailChannelConfig,
  updateNotificationPreferences,
  updateRule,
  updateWebhookChannelConfig,
} from "@/api/engagement";
import { fetchFollowupSurface, updateFollowupRules } from "@/api/applications";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type {
  AlertRule,
  EmailChannelConfig,
  FeedToken,
  NotificationDeliveryRow,
  PreferencesMatrix,
  WebhookChannelConfig,
} from "@/types/wire";

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchPreferencesMatrix: vi.fn(),
    fetchEmailChannelConfig: vi.fn(),
    updateEmailChannelConfig: vi.fn(),
    resendEmailVerification: vi.fn().mockResolvedValue({ sent: true, pending_address: "a@b.c" }),
    verifyEmailAddress: vi.fn(),
    testEmailChannel: vi.fn(),
    fetchWebhookChannelConfig: vi.fn(),
    updateWebhookChannelConfig: vi.fn(),
    testWebhookChannel: vi.fn(),
    fetchFeedTokens: vi.fn(),
    mintFeedToken: vi.fn(),
    rotateFeedToken: vi.fn(),
    revokeFeedToken: vi.fn().mockResolvedValue(undefined),
    fetchSearches: vi.fn(),
    fetchEmailTransport: vi.fn().mockResolvedValue({
      host: "smtp.local",
      port: 587,
      username: "",
      from_address: "career@local",
      from_name: "",
      starttls: true,
      use_ssl: false,
      password_set: false,
    }),
    updateEmailTransport: vi.fn().mockResolvedValue({}),
    fetchVapidPublicKey: vi.fn(),
    subscribePush: vi.fn(),
    unsubscribePush: vi.fn(),
    setKindPreference: vi.fn().mockResolvedValue({}),
    resetKindPreference: vi.fn().mockResolvedValue(undefined),
    updateNotificationPreferences: vi.fn().mockResolvedValue({}),
    fetchRules: vi.fn(),
    updateRule: vi.fn(),
    fetchNotificationDeliveries: vi.fn(),
    broadcastAnnouncement: vi.fn(),
  };
});

vi.mock("@/api/applications", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/applications")>();
  return {
    ...mod,
    fetchFollowupSurface: vi.fn(),
    updateFollowupRules: vi.fn(),
  };
});

const matrix: PreferencesMatrix = {
  channels: ["in_app", "browser", "email", "webhook"],
  quiet_hours: { start: "22:00", end: "07:00" },
  desktop_channel_enabled: true,
  kinds: [
    {
      key: "fit_threshold",
      label: "Fit threshold reached",
      group: "career",
      severity: "info",
      manage_url: null,
      mutable: true,
      default_channels: ["in_app"],
      enabled: true,
      channels: ["in_app"],
      overridden: false,
    },
    {
      key: "new_posting_match",
      label: "New posting match",
      group: "postings",
      severity: "info",
      manage_url: "/settings/audit?tab=retrieval&section=quality",
      mutable: true,
      default_channels: ["in_app", "email"],
      enabled: true,
      channels: ["in_app", "email"],
      overridden: true,
    },
    {
      key: "channel_test",
      label: "Channel test delivery",
      group: "system",
      severity: "info",
      manage_url: null,
      mutable: false,
      default_channels: ["in_app"],
      enabled: true,
      channels: ["in_app"],
      overridden: false,
    },
  ],
};

const email: EmailChannelConfig = {
  enabled: true,
  address: "me@example.test",
  pending_address: "",
  digest_mode: false,
  verified: true,
  verified_at: "2026-10-20T10:00:00Z",
};

const webhook: WebhookChannelConfig = {
  enabled: true,
  url: "https://hooks.example/abc",
  template: "slack",
  secret_set: true,
  verified: false,
  verified_at: null,
};

const token: FeedToken = {
  id: "tok-1",
  kind: "ics",
  scope: {},
  created_at: "2026-10-20T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
  rotated_from_id: null,
};

const rules: AlertRule[] = [
  {
    kind: "fit_threshold",
    params: { min_fit: 7, family_keys: [], muted_family_keys: [], max_per_day: 5, quiet_hours: null },
    enabled: true,
    is_default: true,
  },
  {
    kind: "new_posting_match",
    params: { min_fit: 7, family_keys: [], muted_family_keys: [], max_per_day: 5, quiet_hours: null },
    enabled: true,
    is_default: true,
  },
];

const deliveries: NotificationDeliveryRow[] = [
  {
    id: "d1",
    channel: "email",
    status: "delivered",
    error: null,
    kind: "digest_ready",
    created_at: "2026-10-27T08:00:00Z",
  },
  {
    id: "d2",
    channel: "webhook",
    status: "failed",
    error: "502 bad gateway",
    kind: "new_posting_match",
    created_at: "2026-10-27T09:00:00Z",
  },
];

describe("notification settings (plan 148)", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: false } as never });
    useBootstrapStore.setState({
      bootstrap: {
        notification_channels: ["in_app", "browser", "email", "webhook"],
        target_families: ["data-science"],
        features: {},
      } as never,
      loaded: true,
    });
    vi.mocked(fetchPreferencesMatrix).mockResolvedValue(matrix);
    vi.mocked(fetchEmailChannelConfig).mockResolvedValue(email);
    vi.mocked(fetchWebhookChannelConfig).mockResolvedValue(webhook);
    vi.mocked(fetchFeedTokens).mockResolvedValue([token]);
    vi.mocked(fetchSearches).mockResolvedValue([
      { id: "s1", query: "remote qa", scope: "postings", saved: true } as never,
    ]);
    vi.mocked(updateEmailChannelConfig).mockResolvedValue({
      ...email,
      address: "new@example.test",
      verified: false,
      pending_address: "new@example.test",
    });
    vi.mocked(updateWebhookChannelConfig).mockResolvedValue({
      ...webhook,
      verified: false,
    });
    vi.mocked(mintFeedToken).mockResolvedValue({
      ...token,
      id: "tok-2",
      token: "secret-token-value",
    });
    vi.mocked(rotateFeedToken).mockResolvedValue({
      ...token,
      id: "tok-3",
      token: "rotated-token-value",
    });
    vi.mocked(testWebhookChannel).mockResolvedValue({
      channel: "webhook",
      delivery_id: "d1",
      status: "delivered",
      error: null,
    });
    vi.mocked(fetchRules).mockResolvedValue({ items: rules });
    vi.mocked(updateRule).mockResolvedValue({ items: rules });
    vi.mocked(fetchNotificationDeliveries).mockResolvedValue({ items: deliveries });
    vi.mocked(broadcastAnnouncement).mockResolvedValue({ delivered: 2 });
    vi.mocked(fetchFollowupSurface).mockResolvedValue({
      rules: { enabled: true, cadence_days: [7, 14], milestone_checkins: true, channels: {} },
      items: [],
    });
    vi.mocked(updateFollowupRules).mockResolvedValue({
      enabled: true,
      cadence_days: [7, 14],
      milestone_checkins: true,
      channels: { interview_checkin: ["email"] },
    });
  });

  it("renders the page scaffold with rail, channel cards and the matrix", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("settings-page")).toBeInTheDocument();
    expect(screen.getByTestId("settings-page-rail")).toBeInTheDocument();
    expect(screen.getByTestId("settings-section-email")).toBeInTheDocument();
    expect(screen.getByTestId("settings-section-webhook")).toBeInTheDocument();
    expect(screen.getByTestId("kind-matrix")).toBeInTheDocument();
    expect(screen.getByTestId("notifications-active-channels")).toHaveTextContent("2");
  });

  it("saves a new email address and reports the card-local notice", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const card = await screen.findByTestId("settings-section-email");
    fireEvent.change(within(card).getByTestId("email-address"), {
      target: { value: "new@example.test" },
    });
    fireEvent.click(within(card).getByTestId("email-save"));
    await waitFor(() =>
      expect(updateEmailChannelConfig).toHaveBeenCalledWith({
        enabled: true,
        address: "new@example.test",
        digest_mode: false,
      })
    );
    expect(await within(card).findByTestId("channel-notice")).toHaveTextContent(
      "Verification link sent to new@example.test"
    );
  });

  it("saves the webhook URL, preset and secret", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const card = await screen.findByTestId("settings-section-webhook");
    fireEvent.change(within(card).getByTestId("webhook-url"), {
      target: { value: "https://hooks.example/new" },
    });
    fireEvent.change(within(card).getByTestId("webhook-secret"), {
      target: { value: "hook-secret" },
    });
    await user.click(within(card).getByTestId("webhook-save"));
    await waitFor(() =>
      expect(updateWebhookChannelConfig).toHaveBeenCalledWith({
        enabled: true,
        url: "https://hooks.example/new",
        template: "slack",
        secret: "hook-secret",
      })
    );
  });

  it("runs a webhook test delivery and reports inside the card", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const card = await screen.findByTestId("settings-section-webhook");
    fireEvent.click(within(card).getByTestId("webhook-test"));
    await waitFor(() => expect(testWebhookChannel).toHaveBeenCalled());
    expect(await within(card).findByTestId("channel-notice")).toHaveTextContent(
      "Test delivery succeeded."
    );
  });

  it("routes one kind to a channel with an instant optimistic switch", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const sw = await screen.findByTestId("kind-fit_threshold-email");
    expect(sw).toHaveAttribute("aria-checked", "false");
    await user.click(sw);
    await waitFor(() =>
      expect(setKindPreference).toHaveBeenCalledWith("fit_threshold", {
        channels: ["in_app", "email"],
      })
    );
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("disables locked always-on kinds and offers a reset for overridden ones", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const locked = await screen.findByTestId("kind-row-channel_test");
    expect(locked).toHaveAttribute("data-locked", "true");
    expect(within(locked).getByTestId("kind-channel_test-email")).toBeDisabled();

    const row = await screen.findByTestId("kind-row-new_posting_match");
    await user.click(within(row).getByTestId("kind-new_posting_match-reset"));
    await waitFor(() => expect(resetKindPreference).toHaveBeenCalledWith("new_posting_match"));
  });

  it("links a kind to its existing manage surface when manage_url is set", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const row = await screen.findByTestId("kind-row-new_posting_match");
    const link = within(row).getByTestId("kind-new_posting_match-manage");
    expect(link).toHaveAttribute(
      "href",
      "/settings/audit?tab=retrieval&section=quality",
    );
    expect(screen.queryByTestId("kind-fit_threshold-manage")).toBeNull();
  });

  it("filters the matrix by label", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    await screen.findByTestId("kind-matrix");
    await user.type(screen.getByTestId("kind-filter"), "posting");
    expect(screen.getByTestId("kind-row-new_posting_match")).toBeInTheDocument();
    expect(screen.queryByTestId("kind-row-fit_threshold")).not.toBeInTheDocument();
  });

  it("saves alert-rule parameters", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const card = await screen.findByTestId("settings-section-rules");
    const plus = within(card).getAllByRole("button", { name: /increase/i })[0];
    await user.click(plus);
    await waitFor(() =>
      expect(updateRule).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "fit_threshold",
          params: expect.objectContaining({ min_fit: 7.5 }),
        })
      )
    );
  });

  it("mints a calendar token and shows the one-time link", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("mint-ics"));
    await waitFor(() => expect(mintFeedToken).toHaveBeenCalledWith({ kind: "ics", scope: {} }));
    const secret = await screen.findByTestId("feed-token-secret");
    expect((secret as HTMLInputElement).value).toContain("secret-token-value");
    expect(screen.getByTestId("feed-webcal")).toHaveAttribute(
      "href",
      expect.stringContaining("webcal://")
    );
  });

  it("rotates a feed token", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("feed-token-rotate-tok-1"));
    await waitFor(() => expect(rotateFeedToken).toHaveBeenCalledWith("tok-1"));
    expect((await screen.findByTestId("feed-token-secret") as HTMLInputElement).value).toContain(
      "rotated-token-value"
    );
  });

  describe("quiet hours", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("autosaves debounced without requiring the desktop channel", async () => {
      useBootstrapStore.setState({
        bootstrap: {
          notification_channels: ["in_app", "email"],
          target_families: [],
          features: {},
        } as never,
        loaded: true,
      });
      render(
        <MemoryRouter>
          <Notifications />
        </MemoryRouter>
      );
      await act(async () => {
        await Promise.resolve();
      });
      const start = screen.getByTestId("quiet-hours-start");
      await act(async () => {
        fireEvent.change(start, { target: { value: "23:30" } });
        await vi.advanceTimersByTimeAsync(900);
      });
      expect(updateNotificationPreferences).toHaveBeenCalledWith({
        desktop_channel_enabled: true,
        quiet_hours: { start: "23:30", end: "07:00" },
      });
    });
  });

  describe("admin zone", () => {
    beforeEach(() => {
      useAuthStore.setState({ user: { email: "a@b.c", is_admin: true } as never });
    });

    it("sends a broadcast and reports the delivered count", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <Notifications />
        </MemoryRouter>
      );
      const card = await screen.findByTestId("settings-section-broadcast");
      await user.type(within(card).getByTestId("broadcast-title"), "Maintenance");
      await user.click(within(card).getByTestId("broadcast-send"));
      await waitFor(() =>
        expect(broadcastAnnouncement).toHaveBeenCalledWith({
          title: "Maintenance",
          body: "",
          link: null,
        })
      );
      expect(await within(card).findByTestId("channel-notice")).toHaveTextContent(
        "Delivered to 2 users"
      );
    });

    it("surfaces per-channel delivery health with the failure count", async () => {
      render(
        <MemoryRouter>
          <Notifications />
        </MemoryRouter>
      );
      const health = await screen.findByTestId("delivery-health");
      expect(within(health).getByTestId("delivery-email")).toHaveTextContent("delivered");
      expect(within(health).getByTestId("delivery-webhook")).toHaveTextContent("failed");
      expect(within(health).getByText("502 bad gateway")).toBeInTheDocument();
      expect(screen.getByTestId("delivery-failures")).toHaveTextContent("1");
    });

    it("exposes the full SMTP transport form", async () => {
      render(
        <MemoryRouter>
          <Notifications />
        </MemoryRouter>
      );
      const card = await screen.findByTestId("settings-section-smtp");
      const toggle = within(card).getByTestId("settings-section-smtp-toggle");
      await userEvent.setup().click(toggle);
      expect(within(card).getByTestId("smtp-username")).toBeInTheDocument();
      expect(within(card).getByTestId("smtp-from-name")).toBeInTheDocument();
    });
  });
});
