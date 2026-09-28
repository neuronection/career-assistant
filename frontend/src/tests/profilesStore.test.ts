import { describe, expect, it, vi, beforeEach } from "vitest";
import { useProfilesStore } from "@/stores/profilesStore";
import { useProfileStore } from "@/stores/profileStore";
import { useChatStore } from "@/stores/chatStore";
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

describe("profilesStore", () => {
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

  it("hydrate binds the Default profile when nothing is remembered", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    expect(useProfilesStore.getState().currentId).toBe("p-default");
    expect(getActiveProfile()).toBe("p-default");
    expect(localStorage.getItem("ca-profile-id")).toBe("p-default");
  });

  it("hydrate prefers the remembered profile when it still exists", async () => {
    localStorage.setItem("ca-profile-id", "p-second");
    setActiveProfile("p-second");
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    expect(useProfilesStore.getState().currentId).toBe("p-second");
    expect(getActiveProfile()).toBe("p-second");
  });

  it("hydrate drops a remembered profile that no longer exists", async () => {
    localStorage.setItem("ca-profile-id", "p-gone");
    setActiveProfile("p-gone");
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    await useProfilesStore.getState().hydrate();
    expect(useProfilesStore.getState().currentId).toBe("p-default");
  });

  it("select re-binds, persists, bumps the route epoch and drops caches", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    useProfileStore.setState({ profile: { basics: {} } as never });
    useChatStore.setState({ sessions: [] as never, activeSessionId: "c1", messages: [] as never });

    await useProfilesStore.getState().select(SECOND);
    expect(getActiveProfile()).toBe("p-second");
    expect(localStorage.getItem("ca-profile-id")).toBe("p-second");
    expect(useProfilesStore.getState().currentId).toBe("p-second");
    expect(useProfilesStore.getState().epoch).toBe(1);
    expect(useProfileStore.getState().profile).toBeNull();
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  it("create posts the name and switches to the new profile", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    await useProfilesStore.getState().hydrate();
    mocked.createProfile.mockResolvedValue(SECOND);
    await useProfilesStore.getState().create("Second");
    expect(mocked.createProfile).toHaveBeenCalledWith("Second");
    expect(useProfilesStore.getState().profiles).toHaveLength(2);
    expect(useProfilesStore.getState().currentId).toBe("p-second");
  });

  it("rename patches the row in place", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    mocked.patchProfile.mockResolvedValue({ ...SECOND, name: "Renamed" });
    await useProfilesStore.getState().rename(SECOND, "Renamed");
    expect(mocked.patchProfile).toHaveBeenCalledWith("p-second", { name: "Renamed" });
    expect(
      useProfilesStore.getState().profiles.find((row) => row.id === "p-second")?.name,
    ).toBe("Renamed");
  });

  it("setDefault moves the single default flag", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    mocked.patchProfile.mockResolvedValue({ ...SECOND, is_default: true });
    await useProfilesStore.getState().setDefault(SECOND);
    expect(mocked.patchProfile).toHaveBeenCalledWith("p-second", { is_default: true });
    const rows = useProfilesStore.getState().profiles;
    expect(rows.filter((row) => row.is_default).map((row) => row.id)).toEqual(["p-second"]);
  });

  it("delete refetches and re-mounts pages when the active profile goes away", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    await useProfilesStore.getState().select(SECOND);
    const epochAfterSelect = useProfilesStore.getState().epoch;

    mocked.deleteProfile.mockResolvedValue(undefined);
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    await useProfilesStore.getState().remove(SECOND);
    expect(mocked.deleteProfile).toHaveBeenCalledWith("p-second");
    expect(useProfilesStore.getState().currentId).toBe("p-default");
    expect(useProfilesStore.getState().epoch).toBe(epochAfterSelect + 1);
  });

  it("delete of a non-active profile keeps the epoch", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT, SECOND]);
    await useProfilesStore.getState().hydrate();
    mocked.deleteProfile.mockResolvedValue(undefined);
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    await useProfilesStore.getState().remove(SECOND);
    expect(useProfilesStore.getState().epoch).toBe(0);
  });

  it("surface errors as state when an operation fails", async () => {
    mocked.listProfiles.mockResolvedValue([DEFAULT]);
    await useProfilesStore.getState().hydrate();
    mocked.createProfile.mockRejectedValue(new Error("nope"));
    await useProfilesStore.getState().create("X");
    expect(useProfilesStore.getState().error).toBe("profiles-create-failed");
  });
});
