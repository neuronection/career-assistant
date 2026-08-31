import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";

import { activateDesktop, isDesktop } from "@/lib/desktop";
import { useToastStore } from "@/stores/toastStore";

const SEVERITY_STYLES: Record<string, string> = {
  info: "border-sky-200",
  success: "border-emerald-200",
  warning: "border-amber-200",
  critical: "border-rose-300",
};

/**
 * Fallback in-app toasts for the desktop channel (single-surface rule:
 * shown only when the OS-native path is unavailable). Clicking follows
 * the plan-36 click-through contract; dismissing marks nothing.
 */
export function ToastHost() {
  const { toasts, dismiss } = useToastStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((toast) =>
      setTimeout(() => dismiss(toast.id), 6000)
    );
    return () => timers.forEach(clearTimeout);
  }, [toasts, dismiss]);

  if (toasts.length === 0) return null;

  const open = (link: string) => {
    if (!link) return;
    if (isDesktop()) void activateDesktop(link);
    navigate(link);
  };

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80"
      data-testid="toast-host"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`bg-white border ${
            SEVERITY_STYLES[toast.severity] ?? SEVERITY_STYLES.info
          } rounded-lg shadow-lg p-3`}
        >
          <div className="flex items-start justify-between gap-2">
            <button
              type="button"
              className="text-left flex-1 min-w-0"
              data-testid={`toast-${toast.id}`}
              onClick={() => {
                dismiss(toast.id);
                open(toast.link);
              }}
            >
              <p className="text-sm font-medium text-slate-900 truncate">
                {toast.title}
              </p>
              {toast.body && (
                <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                  {toast.body}
                </p>
              )}
            </button>
            <button
              type="button"
              aria-label="Dismiss"
              className="text-slate-400 hover:text-slate-600"
              onClick={() => dismiss(toast.id)}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
