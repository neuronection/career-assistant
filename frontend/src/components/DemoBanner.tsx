import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FlaskConical } from "lucide-react";

import { getInstanceConfig } from "@/api/instance";

let demoModeFlag: Promise<boolean> | null = null;

/** Whether this is a demo instance (`instance_settings.demo_mode`,
 * identity-auth §13) — fetched once per app boot from the public
 * `GET /api/v1/instance/config`, cached so the badge never refetches.
 * A failed fetch reads as "not a demo" (fail-closed, never a blocker). */
export function loadDemoMode(): Promise<boolean> {
  if (demoModeFlag === null) {
    demoModeFlag = getInstanceConfig()
      .then((config) => config.demo_mode === true)
      .catch(() => false);
  }
  return demoModeFlag;
}

export function clearDemoModeCache(): void {
  demoModeFlag = null;
}

/** Persistent "Demo — synthetic data" badge (identity-auth §13). Lives
 * in the boot gate, not the app shell, so it renders before login as
 * well — a public demo is badged from the very first pixel. */
export function DemoBanner() {
  const { t } = useTranslation();
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    let alive = true;
    void loadDemoMode().then((value) => {
      if (alive) setDemo(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!demo) return null;
  return (
    <div
      role="status"
      className="sticky top-0 z-50 flex items-center justify-center gap-2 border-b border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-700"
    >
      <FlaskConical className="size-3.5 shrink-0" aria-hidden />
      <span>{t("demo.badge")}</span>
      <span className="font-normal opacity-80">{t("demo.description")}</span>
    </div>
  );
}
