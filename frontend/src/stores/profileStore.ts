import { create } from "zustand";
import * as profileApi from "@/api/profile";
import type { Profile, TaxonomyTag } from "@/types";

interface ProfileState {
  profile: Profile | null;
  interests: TaxonomyTag[];
  skills: TaxonomyTag[];
  loading: boolean;
  load: () => Promise<void>;
  loadTaxonomy: () => Promise<void>;
  saveSection: (section: Partial<Profile>) => Promise<void>;
  analyze: () => Promise<void>;
}

export const useProfileStore = create<ProfileState>((set, get) => ({
  profile: null,
  interests: [],
  skills: [],
  loading: false,

  load: async () => {
    if (get().loading || get().profile) return;
    set({ loading: true });
    try {
      const profile = await profileApi.fetchProfile();
      set({ profile });
    } finally {
      set({ loading: false });
    }
  },

  loadTaxonomy: async () => {
    if (get().interests.length > 0) return;
    const [interests, skills] = await Promise.all([
      profileApi.fetchInterests(),
      profileApi.fetchSkills(),
    ]);
    set({ interests, skills });
  },

  saveSection: async (section) => {
    const profile = await profileApi.saveProfileSection(section);
    set({ profile });
  },

  analyze: async () => {
    const { ai_summary, completeness } = await profileApi.analyzeProfile();
    const profile = get().profile;
    if (profile) {
      set({ profile: { ...profile, ai_summary, completeness } });
    }
  },
}));
