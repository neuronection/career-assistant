import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { UNAUTHENTICATED_EVENT } from "@/api/client";
import { AuthGate } from "@/components/ui/auth-gate";
import { DemoBanner } from "@/components/DemoBanner";
import { LoginScreen } from "@/components/auth/LoginScreen";
import { useAuthStore } from "@/stores/authStore";

/** Gate boot (identity-auth §4/§11): delegate to the store's boot chain
 * (cookie → refresh → desktop exchange, §10/§11) — except when the store
 * already decided the session is gone. `dropToLogin()`/`logout()` (§12
 * self-service: device revoke, account deletion) must land on the login
 * surface without another API round-trip, so the replayed boot answers
 * from the store verdict instead of re-checking. */
async function bootGate(): Promise<boolean> {
  const { status, boot } = useAuthStore.getState();
  if (status === "anonymous") return false;
  return boot();
}

/**
 * Composition root for the shared `AuthGate` (identity-auth §4): the
 * `checking → authenticated | anonymous` machine lives in the library —
 * career only wires the endpoints.
 *
 * - The store's boot chain is the machine input (`bootGate`).
 * - A mid-session 401 after a failed refresh dispatches
 *   `UNAUTHENTICATED_EVENT`; the gate's `resetKey` bumps and the flow
 *   re-runs (this time through the real boot, which finds the session
 *   dead and lands anonymous).
 * - A store transition from `authenticated` into `anonymous`
 *   (dropToLogin/logout) also bumps `resetKey`; `bootGate` answers that
 *   replay instantly from the store, so the login screen appears with
 *   zero round-trips. A `checking → anonymous` landing needs no bump —
 *   that verdict already came from the boot itself.
 * - A successful sign-in on `LoginScreen` bumps `resetKey` too; the
 *   replayed boot re-verifies the fresh session and renders the app.
 *
 * The demo badge (§13) rides outside the gate so it renders in every
 * state, before login too.
 */
export function SessionGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const status = useAuthStore((s) => s.status);
  const [epoch, setEpoch] = useState(0);
  const recheck = useCallback(() => setEpoch((e) => e + 1), []);

  // Mid-session 401 (failed refresh): re-run the machine through boot().
  useEffect(() => {
    window.addEventListener(UNAUTHENTICATED_EVENT, recheck);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, recheck);
  }, [recheck]);

  // Store-decided drops (dropToLogin/logout) re-run the machine;
  // bootGate answers that replay from the store verdict without a
  // round-trip. A boot's own anonymous landing (from `checking`) is
  // already rendered — re-bumping it would double the machine cycle.
  const prevStatus = useRef(status);
  useEffect(() => {
    if (prevStatus.current === status) return;
    const dropped = status === "anonymous" && prevStatus.current === "authenticated";
    prevStatus.current = status;
    if (dropped) recheck();
  }, [status, recheck]);

  return (
    <>
      <DemoBanner />
      <AuthGate
        boot={bootGate}
        resetKey={epoch}
        login={<LoginScreen onSignedIn={recheck} />}
        checking={
          <div className="flex min-h-screen items-center justify-center bg-slate-50 text-sm text-slate-500">
            {t("auth.checking")}
          </div>
        }
      >
        {children}
      </AuthGate>
    </>
  );
}
