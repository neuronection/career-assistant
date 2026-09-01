import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { JobCard } from "@/components/JobCard";
import { NotificationBell } from "@/components/NotificationBell";
import { RecentSearches } from "@/components/RecentSearches";
import {
  deleteSearch,
  fetchFeed,
  fetchSearches,
  markSeen,
  fetchNotifications,
  fetchUnreadCount,
  markNotificationsRead,
  dismissNotifications,
  fetchNotificationPreferences,
  fetchRules,
  updateNotificationPreferences,
  updateRule,
} from "@/api/engagement";
import type { FeedResponse, Job, NotificationItem, SearchRecord } from "@/types";

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchFeed: vi.fn(),
    markSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    fetchNotifications: vi.fn(),
    fetchUnreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }),
    markNotificationsRead: vi.fn().mockResolvedValue({ marked: 1 }),
    dismissNotifications: vi.fn().mockResolvedValue({ marked: 1 }),
    fetchRules: vi.fn(),
    updateRule: vi.fn(),
    fetchSearches: vi.fn(),
    deleteSearch: vi.fn().mockResolvedValue(undefined),
    fetchNotificationPreferences: vi.fn(),
    updateNotificationPreferences: vi.fn(),
  };
});

vi.mock("@/api/notificationStream", () => ({
  streamNotifications: vi
    .fn()
    .mockResolvedValue(undefined),
}));

vi.mock("@/api/stages", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/stages")>();
  return {
    ...mod,
    fetchBootstrap: vi.fn().mockResolvedValue({
      career_stage: "student",
      stage_source: "derived",
      features: { universities: true, grade_fields: true },
      suggested_scoring_weights: {
        skills: 3,
        location: 3,
        experience: 3,
        education: 3,
        interests: 3,
      },
      effective_scoring_weights: {
        skills: 3,
        location: 3,
        experience: 3,
        education: 3,
        interests: 3,
      },
      weights_overridden: false,
      notification_channels: ["in_app", "desktop"],
    }),
  };
});

vi.mock("@/api/matching", () => ({
  fetchRankings: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchCandidates: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/profile", () => ({
  fetchProfile: vi.fn().mockResolvedValue({
    preferences: {
      scoring_weights: { skills: 3, location: 3, experience: 3, education: 3, interests: 3 },
    },
  }),
}));

vi.mock("@/api/jobs", () => ({
  fetchFamilyTree: vi.fn().mockResolvedValue([]),
  fetchJobs: vi.fn().mockResolvedValue([]),
  fetchGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
}));

import { Dashboard } from "@/pages/Dashboard";
import { useProfileStore } from "@/stores/profileStore";
import { useCatalogStore } from "@/stores/catalogStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";

const mockFetchFeed = vi.mocked(fetchFeed);
const mockFetchNotifications = vi.mocked(fetchNotifications);
const mockFetchRules = vi.mocked(fetchRules);
const mockUpdateRule = vi.mocked(updateRule);

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "j1",
    code: "software-developer",
    title: "Software Developer",
    family_key: "technology-software",
    short_description: "Builds software.",
    status: "published",
    source: "seed",
    attributes: {
      subjects: [],
      work_style: {} as Job["attributes"]["work_style"],
      education: { level: "bachelor", fields: [] },
      physical: {} as Job["attributes"]["physical"],
      salary: {} as Job["attributes"]["salary"],
      demand: {} as Job["attributes"]["demand"],
      environments: [],
      typical_positives: [],
      typical_negatives: [],
    },
    interests: [{ key: "technology-software", label: "Software" }],
    skills: [],
    links: [],
    created_at: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

describe("JobCard engagement state", () => {
  it("shows the education chip, saved marker and seen state", () => {
    render(<JobCard job={makeJob()} saved seen />);
    expect(screen.getByTestId("education-chip")).toHaveTextContent("Bachelor's");
    expect(screen.getByText("seen")).toBeInTheDocument();
  });

  it("shows notes and the exploration chip", () => {
    render(<JobCard job={makeJob()} notes="Great fit for me" exploration />);
    expect(screen.getByTestId("job-card-notes")).toHaveTextContent("Great fit for me");
    expect(screen.getByText("explore")).toBeInTheDocument();
  });
});

describe("Recent searches", () => {
  it("lists records, re-runs on click and deletes", async () => {
    const onApply = vi.fn();
    const record: SearchRecord = {
      id: "s1",
      scope: "rankings",
      query: "nurse",
      filters: { family_key: "healthcare" },
      result_count: 4,
      saved: false,
      created_at: "2026-08-31T00:00:00Z",
    };
    vi.mocked(fetchSearches).mockResolvedValue([record]);

    render(<RecentSearches scope="rankings" onApply={onApply} />);
    const item = await screen.findByTestId("recent-search-item");
    expect(item).toHaveTextContent("nurse");
    fireEvent.click(item);
    expect(onApply).toHaveBeenCalledWith(record);

    fireEvent.click(screen.getByLabelText("Delete search"));
    await waitFor(() => expect(deleteSearch).toHaveBeenCalledWith("s1"));
  });
});

describe("NotificationBell", () => {
  beforeEach(() => {
    mockFetchNotifications.mockResolvedValue({
      items: [
        {
          id: "r1",
          notification_id: "n1",
          kind: "fit_threshold",
          severity: "info",
          status: "unread",
          title: "Strong fit: Software Developer",
          body: "Your fit score reached 8.0/10.",
          payload: { job_code: "software-developer", link: "/jobs/software-developer" },
          source_ref: {},
          thread_key: null,
          read_at: null,
          dismissed_at: null,
          created_at: "2026-08-31T00:00:00Z",
        } satisfies NotificationItem,
      ],
      unread_count: 1,
    });
    vi.mocked(fetchUnreadCount).mockResolvedValue({ unread_count: 1 });
    mockFetchRules.mockResolvedValue({
      items: [
        {
          kind: "fit_threshold",
          params: {
            min_fit: 7,
            family_keys: [],
            muted_family_keys: [],
            max_per_day: 5,
          },
          enabled: true,
          is_default: true,
        },
      ],
    });
    mockUpdateRule.mockResolvedValue({ items: [] });
  });

  it("shows the unread badge, opens the panel and marks read", async () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("notification-badge")).toHaveTextContent("1");
    fireEvent.click(screen.getByTestId("notification-bell"));
    expect(await screen.findByText("Strong fit: Software Developer")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("notification-item"));
    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(["r1"]));
  });

  it("dismisses an item from the inbox", async () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("notification-bell"));
    fireEvent.click(await screen.findByTestId("notification-dismiss"));
    await waitFor(() => expect(dismissNotifications).toHaveBeenCalledWith(["r1"]));
  });

  it("saves an updated fit threshold rule", async () => {
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("notification-bell"));
    const slider = await screen.findByTestId("fit-rule-threshold");
    fireEvent.change(slider, { target: { value: "5" } });
    await waitFor(() =>
      expect(mockUpdateRule).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "fit_threshold", enabled: true })
      )
    );
  });

  it("shows desktop prefs (channel toggle + quiet hours) and persists them", async () => {
    const mockFetchPrefs = vi.mocked(fetchNotificationPreferences);
    const mockUpdatePrefs = vi.mocked(updateNotificationPreferences);
    mockFetchPrefs.mockResolvedValue({
      desktop_channel_enabled: true,
      quiet_hours: null,
    });
    mockUpdatePrefs.mockResolvedValue({
      desktop_channel_enabled: false,
      quiet_hours: null,
    });
    useBootstrapStore.setState({
      bootstrap: {
        career_stage: "student",
        stage_source: "derived",
        features: { universities: true, grade_fields: true },
        suggested_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 3,
          education: 3,
          interests: 3,
        },
        effective_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 3,
          education: 3,
          interests: 3,
        },
        weights_overridden: false,
        notification_channels: ["in_app", "desktop"],
      },
      loaded: true,
    });

    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("notification-bell"));
    const toggle = await screen.findByTestId("desktop-channel-enabled");
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(mockUpdatePrefs).toHaveBeenCalledWith(
        expect.objectContaining({ desktop_channel_enabled: false })
      )
    );

    fireEvent.change(screen.getByTestId("quiet-hours-start"), {
      target: { value: "22:00" },
    });
    fireEvent.change(screen.getByTestId("quiet-hours-end"), {
      target: { value: "07:00" },
    });
    await waitFor(() =>
      expect(mockUpdatePrefs).toHaveBeenLastCalledWith(
        expect.objectContaining({
          quiet_hours: { start: "22:00", end: "07:00" },
        })
      )
    );
  });

  it("hides desktop prefs when the mode does not offer the channel", async () => {
    const mockFetchPrefs = vi.mocked(fetchNotificationPreferences);
    mockFetchPrefs.mockClear();
    mockFetchPrefs.mockResolvedValue({
      desktop_channel_enabled: true,
      quiet_hours: null,
    });
    useBootstrapStore.setState({
      bootstrap: {
        career_stage: "student",
        stage_source: "derived",
        features: { universities: true, grade_fields: true },
        suggested_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 3,
          education: 3,
          interests: 3,
        },
        effective_scoring_weights: {
          skills: 3,
          location: 3,
          experience: 3,
          education: 3,
          interests: 3,
        },
        weights_overridden: false,
        notification_channels: ["in_app", "browser"],
      },
      loaded: true,
    });

    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("notification-bell"));
    await screen.findByTestId("notification-list");
    expect(screen.queryByTestId("desktop-prefs")).not.toBeInTheDocument();
    expect(fetchNotificationPreferences).not.toHaveBeenCalled();
  });
});

describe("Dashboard feed", () => {
  beforeEach(() => {
    useProfileStore.setState({ profile: null, load: vi.fn().mockResolvedValue(undefined) });
    useCatalogStore.setState({
      families: [],
      jobs: [],
      loadFamilies: vi.fn().mockResolvedValue(undefined),
      loadJobs: vi.fn().mockResolvedValue(undefined),
    });
  });

  it("renders the unseen-first feed with a badge and exploration chip", async () => {
    const feed: FeedResponse = {
      items: [
        {
          job: makeJob(),
          fit_score: 8.4,
          insight: null,
          seen: false,
          saved: false,
          user_notes: "",
          exploration: true,
        },
      ],
      total: 3,
      unseen: 3,
    };
    mockFetchFeed.mockResolvedValue(feed);

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("feed-section")).toBeInTheDocument();
    expect(screen.getByTestId("feed-unseen-badge")).toHaveTextContent("3 new");
    expect(screen.getByText("explore")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("job-card"));
    await waitFor(() => expect(markSeen).toHaveBeenCalledWith(["j1"]));
  });

  it("switches to the saved view", async () => {
    mockFetchFeed.mockResolvedValue({
      items: [
        {
          job: makeJob(),
          fit_score: 7.0,
          insight: null,
          seen: true,
          saved: true,
          user_notes: "my note",
          exploration: false,
        },
      ],
      total: 1,
      unseen: 0,
    });

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("feed-saved-toggle"));
    await waitFor(() =>
      expect(mockFetchFeed).toHaveBeenCalledWith(expect.objectContaining({ view: "saved" }))
    );
    expect(await screen.findByTestId("job-card-notes")).toHaveTextContent("my note");
  });
});
