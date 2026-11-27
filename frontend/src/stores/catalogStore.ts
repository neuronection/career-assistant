import { create } from "zustand";
import * as jobsApi from "@/api/jobs";
import type { Job, JobFacets } from "@/types/wire";
import type { JobFamilyNode } from "@/types";

interface CatalogState {
  families: JobFamilyNode[];
  jobs: Job[];
  total: number;
  facets: JobFacets;
  loading: boolean;
  /** The last load failed; the previous jobs stay (and read as stale). */
  error: boolean;
  filters: Record<string, unknown>;
  loadFamilies: () => Promise<void>;
  loadJobs: (filters?: Record<string, unknown>) => Promise<void>;
  setFilters: (filters: Record<string, unknown>) => void;
}

export const useCatalogStore = create<CatalogState>((set, get) => ({
  families: [],
  jobs: [],
  total: 0,
  facets: {},
  loading: false,
  error: false,
  filters: {},

  loadFamilies: async () => {
    const families = await jobsApi.fetchFamilyTree();
    set({ families });
  },

  loadJobs: async (filters) => {
    set({ loading: true, error: false });
    try {
      const next = filters ?? {};
      const page = await jobsApi.fetchJobs({ page_size: 100, ...next });
      set({
        jobs: page.items ?? [],
        total: page.total ?? 0,
        facets: page.facets ?? {},
        filters: next,
        error: false,
      });
    } catch {
      // Keep the last grid but stop describing the query that never ran.
      set({ facets: {}, error: true });
    } finally {
      set({ loading: false });
    }
  },

  setFilters: (filters) => {
    set({ filters });
    void get().loadJobs();
  },
}));
