import { create } from "zustand";

const MAX_COMPARE = 4;

export interface CompareItem {
  id: string;
  title: string;
}

interface CompareState {
  items: CompareItem[];
  toggle: (item: CompareItem) => void;
  remove: (id: string) => void;
  clear: () => void;
}

export const COMPARE_LIMIT = MAX_COMPARE;

export const useCompareStore = create<CompareState>((set) => ({
  items: [],
  toggle: (item) =>
    set((state) => {
      if (state.items.some((i) => i.id === item.id)) {
        return { items: state.items.filter((i) => i.id !== item.id) };
      }
      const next = [...state.items, item];
      return {
        items:
          next.length > MAX_COMPARE ? next.slice(next.length - MAX_COMPARE) : next,
      };
    }),
  remove: (id) =>
    set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
  clear: () => set({ items: [] }),
}));
