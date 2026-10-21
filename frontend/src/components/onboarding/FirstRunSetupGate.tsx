import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AiStatus } from "@/types";

/** Paths that never trigger the first-run bounce: onboarding owns the flow,
 * settings is where a power user configures AI by hand, and About is static. */
const EXEMPT_PREFIXES = ["/onboarding", "/settings", "/about"];

/** Whether an unconfigured, un-skipped app should land on the setup step. */
export function shouldRedirectToSetup(
  pathname: string,
  ai: AiStatus | undefined
): boolean {
  if (!ai || ai.configured || ai.setup_dismissed) return false;
  return !EXEMPT_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );
}

/** Boot redirect for the first run (plan 118.2): with no provider configured
 * the app opens the system-setup step instead of a page whose AI features
 * would all fail. Bounces once per mount, so skipping never fights back. */
export function FirstRunSetupGate() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const ai = useBootstrapStore((state) => state.bootstrap?.ai);
  const bounced = useRef(false);

  useEffect(() => {
    if (bounced.current || !shouldRedirectToSetup(pathname, ai)) return;
    bounced.current = true;
    navigate("/onboarding/setup", { replace: true });
  }, [ai, pathname, navigate]);

  return null;
}
