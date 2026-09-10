import { create } from "zustand";

export interface InAppToast {
  id: number;
  title: string;
  body: string;
  severity: string;
  link: string;
}

interface ToastState {
  toasts: InAppToast[];
  push: (toast: Omit<InAppToast, "id">) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

/**
 * In-app toast previews — the fallback surface for the desktop channel
 * (single-surface rule: an OS toast *or* this, never both). Web mode
 * without the browser channel simply shows nothing here.
 */
export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (toast) =>
    set((state) => ({
      toasts: [...state.toasts.slice(-3), { ...toast, id: nextId++ }],
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));
