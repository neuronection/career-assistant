import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Notifications } from "@/pages/settings/Notifications";
import {
  fetchEmailChannelConfig,
  fetchFeedTokens,
  fetchPreferencesMatrix,
  fetchSearches,
  fetchWebhookChannelConfig,
  mintFeedToken,
  rotateFeedToken,
  setKindPreference,
  testWebhookChannel,
  updateEmailChannelConfig,
  updateWebhookChannelConfig,
} from "@/api/engagement";
import { fetchFollowupSurface, updateFollowupRules } from "@/api/applications";
import { useAuthStore } from "@/stores/authStore";
import type {
  EmailChannelConfig,
  FeedToken,
  PreferencesMatrix,
  WebhookChannelConfig,
} from "@/types";

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
    fetchEmailTransport: vi.fn(),
    updateEmailTransport: vi.fn().mockResolvedValue({}),
    fetchVapidPublicKey: vi.fn(),
    subscribePush: vi.fn(),
    unsubscribePush: vi.fn(),
    setKindPreference: vi.fn().mockResolvedValue({}),
    updateNotificationPreferences: vi.fn().mockResolvedValue({}),
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
  quiet_hours: null,
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

describe("notification channels settings", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: false } as never });
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

  it("renders email, webhook, feed and routing sections", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("email-settings")).toBeInTheDocument();
    expect(screen.getByTestId("webhook-settings")).toBeInTheDocument();
    expect(screen.getByTestId("feed-tokens")).toBeInTheDocument();
    expect(screen.getByTestId("email-verified")).toHaveTextContent("Verified");
    expect(screen.getByTestId("feed-token-tok-1")).toBeInTheDocument();
  });

  it("saves a new email address", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    const address = await screen.findByTestId("email-address");
    fireEvent.change(address, { target: { value: "new@example.test" } });
    fireEvent.click(screen.getByTestId("email-save"));
    await waitFor(() =>
      expect(updateEmailChannelConfig).toHaveBeenCalledWith({
        enabled: true,
        address: "new@example.test",
        digest_mode: false,
      })
    );
    expect(await screen.findByTestId("channel-notice")).toHaveTextContent(
      "Verification link sent to new@example.test"
    );
  });

  it("saves the webhook preset and token", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    fireEvent.change(await screen.findByTestId("webhook-url"), {
      target: { value: "https://hooks.example/new" },
    });
    fireEvent.change(screen.getByTestId("webhook-secret"), {
      target: { value: "hook-secret" },
    });
    fireEvent.click(screen.getByTestId("webhook-save"));
    await waitFor(() =>
      expect(updateWebhookChannelConfig).toHaveBeenCalledWith({
        enabled: true,
        url: "https://hooks.example/new",
        template: "slack",
        secret: "hook-secret",
      })
    );
  });

  it("runs a webhook test delivery", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("webhook-test"));
    await waitFor(() => expect(testWebhookChannel).toHaveBeenCalled());
    expect(await screen.findByTestId("channel-notice")).toHaveTextContent(
      "Test delivery succeeded."
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

  it("routes one kind to email and saves a follow-up route override", async () => {
    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("kind-fit_threshold-email"));
    await waitFor(() =>
      expect(setKindPreference).toHaveBeenCalledWith("fit_threshold", {
        channels: ["in_app", "email"],
      })
    );
    fireEvent.click(await screen.findByTestId("followup-route-interview_checkin-email"));
    fireEvent.click(screen.getByTestId("followup-rules-save"));
    await waitFor(() =>
      expect(updateFollowupRules).toHaveBeenCalledWith(
        expect.objectContaining({
          channels: expect.objectContaining({ interview_checkin: ["email"] }),
        })
      )
    );
  });
});
