import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FlaskConical, Lock, Unlock } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@neuronection/assistant-ui";
import { NAV, type AppNavItem } from "@/config/nav";
import { useDevModeStore } from "@/stores/devModeStore";

/**
 * Hidden developer surface in the sidebar footer. Invisible-by-default
 * hit area: 5 taps within 2s unlock dev mode (a lock/unlock icon confirms
 * the state); the popover then lists the in-dev pages for one-click
 * access and offers locking again. When locked, the popover still opens
 * (it is the unlock affordance) but lists no pages.
 */
export function DevMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { enabled, tap, disable } = useDevModeStore();
  const [open, setOpen] = useState(false);
  const tapTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (tapTimer.current !== null) window.clearTimeout(tapTimer.current);
  }, []);

  const handleTrigger = () => {
    tap();
    setOpen(true);
  };

  const devPages = NAV.filter((item) => item.inDev);
  const openable = enabled && devPages.length > 0;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        asChild
        data-testid="dev-menu-trigger"
        aria-label={t("devMenu.trigger")}
        title={t("devMenu.trigger")}
        onClick={handleTrigger}
        className="flex size-6 items-center justify-center rounded-md text-slate-300 transition-colors hover:text-primary-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
      >
        {enabled ? (
          <Unlock className="size-3.5" aria-hidden />
        ) : (
          <Lock className="size-3.5 text-slate-200" aria-hidden />
        )}
      </PopoverTrigger>
      <PopoverContent
        side="right"
        align="end"
        className="w-64 p-2"
        data-testid="dev-menu"
      >
        <div className="flex items-center justify-between px-2 pb-1.5 pt-1">
          <span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <FlaskConical className="size-3.5" aria-hidden />
            {t("devMenu.title")}
          </span>
          {enabled && (
            <button
              type="button"
              data-testid="dev-menu-lock"
              onClick={() => {
                disable();
                setOpen(false);
              }}
              className="text-[11px] font-medium text-slate-400 transition-colors hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
            >
              {t("devMenu.lock")}
            </button>
          )}
        </div>
        {openable ? (
          <div className="flex flex-col">
            {devPages.map((item: AppNavItem) => (
              <button
                key={item.to}
                type="button"
                data-testid={`dev-menu-item-${item.to.replace(/^\//, "").replace(/\//g, "-")}`}
                onClick={() => {
                  setOpen(false);
                  navigate(item.to);
                }}
                className="flex items-center gap-2 rounded-[var(--as-radius-sm)] px-2 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600"
              >
                <item.icon className="size-4 text-slate-400" aria-hidden />
                {t(item.labelKey)}
              </button>
            ))}
          </div>
        ) : (
          <p className="px-2 pb-1.5 pt-1 text-xs text-slate-500">
            {t("devMenu.lockedHint")}
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
