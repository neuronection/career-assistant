import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Applications } from "@/pages/Applications";
import { ApplicationsFunnel } from "@/components/applications/ApplicationsFunnel";
import { markSeen } from "@/lib/applicationSeen";
import { api } from "@/api/client";
import type { ApplicationDetail, ApplicationList } from "@/types/application";

const apiMock = vi.hoisted(() => ({
  fetchApplications: vi.fn(),
  fetchApplication: vi.fn(),
  transitionApplication: vi.fn(),
  addApplicationNote: vi.fn(),
  linkApplicationDocument: vi.fn(),
  snoozeApplicationFollowup: vi.fn(),
  closeApplication: vi.fn(),
  fetchFollowupSurface: vi.fn(),
  updateFollowupRules: vi.fn(),
  fetchCvs: vi.fn(),
}));

vi.mock("@/api/applications", () => ({
  fetchApplications: apiMock.fetchApplications,
  fetchApplication: apiMock.fetchApplication,
  transitionApplication: apiMock.transitionApplication,
  addApplicationNote: apiMock.addApplicationNote,
  linkApplicationDocument: apiMock.linkApplicationDocument,
  snoozeApplicationFollowup: apiMock.snoozeApplicationFollowup,
  closeApplication: apiMock.closeApplication,
  fetchFollowupSurface: apiMock.fetchFollowupSurface,
  updateFollowupRules: apiMock.updateFollowupRules,
}));

vi.mock("@/api/cv", () => ({ fetchCvs: apiMock.fetchCvs }));

const NOW = new Date().toISOString();
const WEEK_AGO = new Date(Date.now() - 7 * 84_000_000).toISOString();

function application(overrides: Partial<ApplicationDetail> = {}): ApplicationDetail {
  return {
    id: "app-1",
    posting_id: "post-1",
    posting_ref: "ref-1",
    posting_title: "Junior Data Analyst",
    posting_org: "Acme",
    stage: "applied",
    applied_at: WEEK_AGO,
    applied_via: "url",
    applied_via_url: "",
    deadline_at: null,
    next_followup_at: NOW,
    contact: {},
    offer: {},
    outcome: null,
    closed_at: null,
    cv_id: null,
    cover_letter_id: null,
    external_ref: "",
    notes: "",
    meta: {},
    created_at: WEEK_AGO,
    updated_at: NOW,
    timeline: [
      {
        id: "ev-1",
        at: WEEK_AGO,
        kind: "stage_change",
        stage_from: null,
        stage_to: "applied",
        body: "",
        actor: "user",
        meta: {},
      },
    ],
    ...overrides,
  };
}

function listing(items: ApplicationDetail[]): ApplicationList {
  return {
    items: items.map(({ timeline: _timeline, ...row }) => row),
    total: items.length,
    funnel: {
      saved: 0,
      applied: items.length,
      interviewing: 0,
      offers: 0,
      closed: 0,
    },
    next_followup_at: NOW,
  };
}

const rules = {
  enabled: true,
  cadence_days: [7, 14],
  milestone_checkins: true,
  channels: {},
};

beforeEach(() => {
  Object.values(apiMock).forEach((fn) => fn.mockReset());
  apiMock.fetchApplications.mockResolvedValue(listing([application()]));
  apiMock.fetchApplication.mockResolvedValue(application());
  apiMock.fetchCvs.mockResolvedValue([]);
  apiMock.fetchFollowupSurface.mockResolvedValue({ rules, items: [] });
  apiMock.updateFollowupRules.mockResolvedValue(rules);
  apiMock.transitionApplication.mockResolvedValue(
    application({ stage: "interview" })
  );
  apiMock.addApplicationNote.mockResolvedValue(
    application({
      notes: "Recruiter replied",
      timeline: [
        {
          id: "ev-2",
          at: NOW,
          kind: "note",
          stage_from: null,
          stage_to: null,
          body: "Recruiter replied",
          actor: "user",
          meta: {},
        },
        application().timeline[0],
      ],
    })
  );
  apiMock.snoozeApplicationFollowup.mockResolvedValue(application());
  apiMock.closeApplication.mockResolvedValue(
    application({
      stage: "rejected",
      outcome: "rejected",
      closed_at: NOW,
    })
  );
  localStorage.clear();
  void api;
});

function mount(route = "/applications") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Applications />
    </MemoryRouter>
  );
}

describe("applications tracker (plan 116.4)", () => {
  it("renders the board by default and toggles to the list", async () => {
    mount();
    expect(await screen.findByTestId("applications-board")).toBeInTheDocument();
    expect(screen.getByTestId("application-card-app-1")).toBeInTheDocument();
    const appliedColumn = screen.getByTestId("board-column-applied");
    expect(within(appliedColumn).getByText("Junior Data Analyst")).toBeInTheDocument();

    await userEvent.setup().click(screen.getByTestId("applications-view-list"));
    expect(screen.getByTestId("applications-list")).toBeInTheDocument();
    expect(screen.getByTestId("application-row-app-1")).toBeInTheDocument();
    expect(screen.queryByTestId("applications-board")).not.toBeInTheDocument();
  });

  it("opens the drawer from a card and appends a note", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("application-card-app-1"));
    expect(await screen.findByTestId("application-drawer-body")).toBeInTheDocument();
    expect(screen.getByTestId("application-event-stage_change")).toBeInTheDocument();

    await user.type(screen.getByTestId("application-note-input"), "Recruiter replied");
    await user.click(screen.getByTestId("application-note-save"));
    await waitFor(() =>
      expect(apiMock.addApplicationNote).toHaveBeenCalledWith("app-1", "Recruiter replied")
    );
    expect(await screen.findByTestId("application-event-note")).toBeInTheDocument();
  });

  it("moves the stage and closes the application", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("application-card-app-1"));
    await screen.findByTestId("application-drawer-body");

    await user.selectOptions(screen.getByTestId("application-stage-select"), "interview");
    await user.click(screen.getByTestId("application-stage-save"));
    await waitFor(() =>
      expect(apiMock.transitionApplication).toHaveBeenCalledWith("app-1", "interview")
    );

    await user.selectOptions(screen.getByTestId("application-close-outcome"), "rejected");
    await user.click(screen.getByTestId("application-close-save"));
    await waitFor(() =>
      expect(apiMock.closeApplication).toHaveBeenCalledWith("app-1", "rejected", "")
    );
  });

  it("opens the drawer straight from a notification deep link", async () => {
    mount("/applications?application=app-1");
    expect(await screen.findByTestId("application-drawer-body")).toBeInTheDocument();
    expect(apiMock.fetchApplication).toHaveBeenCalledWith("app-1");
  });

  it("marks the unread dot once the drawer was opened", async () => {
    mount();
    expect(await screen.findByTestId("application-unread-app-1")).toBeInTheDocument();
    markSeen("app-1", NOW);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("application-card-app-1"));
    await screen.findByTestId("application-drawer-body");
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByTestId("application-unread-app-1")).not.toBeInTheDocument()
    );
  });

  it("edits the follow-up rules from the toolbar block", async () => {
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("applications-followup-settings"));
    expect(await screen.findByTestId("followup-rules")).toBeInTheDocument();
    await user.click(screen.getByTestId("toggle-send-follow-up-reminders"));
    await user.click(screen.getByTestId("followup-rules-save"));
    await waitFor(() =>
      expect(apiMock.updateFollowupRules).toHaveBeenCalledWith({
        enabled: false,
        cadence_days: [7, 14],
        milestone_checkins: true,
      })
    );
    expect(await screen.findByTestId("followup-rules-saved")).toBeInTheDocument();
  });
});

describe("dashboard applications funnel", () => {
  it("renders saved → applied → interviewing → offers", () => {
    render(
      <MemoryRouter>
        <ApplicationsFunnel
          funnel={{ saved: 4, applied: 3, interviewing: 2, offers: 1, closed: 0 }}
        />
      </MemoryRouter>
    );
    expect(screen.getByTestId("funnel-saved")).toHaveTextContent("4");
    expect(screen.getByTestId("funnel-applied")).toHaveTextContent("3");
    expect(screen.getByTestId("funnel-interviewing")).toHaveTextContent("2");
    expect(screen.getByTestId("funnel-offers")).toHaveTextContent("1");
  });

  it("renders nothing for an empty funnel", () => {
    render(
      <MemoryRouter>
        <ApplicationsFunnel
          funnel={{ saved: 0, applied: 0, interviewing: 0, offers: 0, closed: 0 }}
        />
      </MemoryRouter>
    );
    expect(screen.queryByTestId("applications-widget")).not.toBeInTheDocument();
  });
});
