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
  filters: {},

  loadFamilies: async () => {
    const families = await jobsApi.fetchFamilyTree();
    set({ families });
  },

  loadJobs: async (filters) => {
    set({ loading: true });
    try {
      const merged = { ...get().filters, ...filters };
      const page = await jobsApi.fetchJobs({ page_size: 100, ...merged });
      set({
        jobs: page.items ?? [],
        total: page.total ?? 0,
        facets: page.facets ?? {},
        filters: merged,
      });
    } finally {
      set({ loading: false });
    }
  },

  setFilters: (filters) => {
    set({ filters });
    void get().loadJobs();
  },
}));
