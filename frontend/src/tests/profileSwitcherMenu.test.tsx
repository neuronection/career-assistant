import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ProfileSwitcherMenu } from "@/components/ProfileSwitcherMenu";
import { useProfilesStore } from "@/stores/profilesStore";
import * as profilesApi from "@/api/profiles";
import { getActiveProfile, setActiveProfile } from "@/api/client";

vi.mock("@/api/profiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/profiles")>();
  return {
    ...actual,
    listProfiles: vi.fn(),
    createProfile: vi.fn(),
    patchProfile: vi.fn(),
    deleteProfile: vi.fn(),
  };
});

vi.mock("@/api/stages", () => ({
  fetchBootstrap: vi.fn().mockResolvedValue(null),
}));

const mocked = vi.mocked(profilesApi);

const DEFAULT = { id: "p-default", name: "Default", color: null, is_default: true };
const SECOND = { id: "p-second", name: "Second", color: null, is_default: false };

describe("ProfileSwitcherMenu (chrome integration, §6/§12/§15)", () => {
  beforeEach(() => {
    localStorage.clear();
    setActiveProfile(null);
    vi.clearAllMocks();
    useProfilesStore.setState({
      profiles: [],
      currentId: null,
      epoch: 0,
      loading: false,
      error: null,
    });
  });

  it("hydrates on mount and shows the active profile on the trigger", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    render(<ProfileSwitcherMenu />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Switch profile" })).toHaveTextContent(
        "Default",
      ),
    );
    expect(getActiveProfile()).toBe("p-default");
  });

  it("create flow posts the name and re-binds the client (§15)", async () => {
    const user = userEvent.setup();
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    mocked.createProfile.mockResolvedValue(SECOND);
    render(<ProfileSwitcherMenu />);
    await screen.findByRole("button", { name: "Switch profile" });

    await user.click(screen.getByRole("button", { name: "Switch profile" }));
    await user.type(screen.getByRole("textbox", { name: "New profile" }), "Second");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(mocked.createProfile).toHaveBeenCalledWith("Second"));
    await waitFor(() => expect(getActiveProfile()).toBe("p-second"));
  });

  it("select flow re-binds and persists the last-used profile", async () => {
    const user = userEvent.setup();
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    render(<ProfileSwitcherMenu />);
    await screen.findByRole("button", { name: "Switch profile" });

    await user.click(screen.getByRole("button", { name: "Switch profile" }));
    await user.click(screen.getByRole("button", { name: /^Second/ }));

    await waitFor(() => expect(getActiveProfile()).toBe("p-second"));
    expect(localStorage.getItem("ca-profile-id")).toBe("p-second");
  });

  it("rename flow patches through the API", async () => {
    const user = userEvent.setup();
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    mocked.patchProfile.mockResolvedValue({ ...SECOND, name: "Renamed" });
    render(<ProfileSwitcherMenu />);
    await screen.findByRole("button", { name: "Switch profile" });

    await user.click(screen.getByRole("button", { name: "Switch profile" }));
    await user.click(screen.getByRole("button", { name: "Rename Second" }));
    await user.clear(screen.getByRole("textbox", { name: "Rename Second" }));
    await user.type(screen.getByRole("textbox", { name: "Rename Second" }), "Renamed{Enter}");

    await waitFor(() =>
      expect(mocked.patchProfile).toHaveBeenCalledWith("p-second", { name: "Renamed" }),
    );
  });

  it("set-default flow patches is_default", async () => {
    const user = userEvent.setup();
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    mocked.patchProfile.mockResolvedValue({ ...SECOND, is_default: true });
    render(<ProfileSwitcherMenu />);
    await screen.findByRole("button", { name: "Switch profile" });

    await user.click(screen.getByRole("button", { name: "Switch profile" }));
    await user.click(
      screen.getByRole("button", { name: "Make Second the default profile" }),
    );

    await waitFor(() =>
      expect(mocked.patchProfile).toHaveBeenCalledWith("p-second", { is_default: true }),
    );
  });

  it("delete flow is destructive-confirmed (§12)", async () => {
    const user = userEvent.setup();
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    mocked.deleteProfile.mockResolvedValue(undefined);
    render(<ProfileSwitcherMenu />);
    await screen.findByRole("button", { name: "Switch profile" });

    await user.click(screen.getByRole("button", { name: "Switch profile" }));
    await user.click(screen.getByRole("button", { name: "Delete Second" }));
    // confirm modal gates the delete
    expect(mocked.deleteProfile).not.toHaveBeenCalled();

    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    const modal = screen.getByRole("dialog", { name: "Delete profile" });
    await user.click(within(modal).getByRole("button", { name: /^Delete Second$/ }));
    await waitFor(() => expect(mocked.deleteProfile).toHaveBeenCalledWith("p-second"));
    await waitFor(() =>
      expect(
        useProfilesStore.getState().profiles.map((row) => row.id),
      ).toEqual(["p-default"]),
    );
  });
});
