import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LoginForm } from "@/components/ui/login-form";
import { RegisterForm } from "@/components/ui/register-form";
import { useAuthStore } from "@/stores/authStore";

/**
 * Login/register surface (identity-auth §12) over the shared
 * `LoginForm`/`RegisterForm` (plan 16 Phase 5 closeout): the shell,
 * mode switch and auth-store glue stay career-local; the field markup,
 * validation, visibility toggles and the register confirm gate live in
 * the library. The instance's REGISTRATION_ENABLED flag is server
 * truth (§12/§16); it becomes visible here through the 403 the
 * register route answers, and the register action then stays hidden.
 * `onSignedIn` fires after a successful login *or* registration — the
 * SessionGate bumps its resetKey on it so the shared AuthGate re-runs
 * its boot and renders the app.
 */
export function LoginScreen({ onSignedIn }: { onSignedIn?: () => void }) {
  const { t } = useTranslation();
  const { login, register, loading } = useAuthStore();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [registerDisabled, setRegisterDisabled] = useState(false);

  async function submitLogin(email: string, password: string) {
    const ok = await login(email, password);
    if (!ok) {
      setError(t("auth.loginError"));
      return;
    }
    onSignedIn?.();
  }

  async function submitRegister(email: string, password: string, fullName?: string) {
    const outcome = await register(email, password, fullName ?? "");
    if (outcome === "ok") {
      onSignedIn?.();
      return;
    }
    if (outcome === "disabled") {
      setRegisterDisabled(true);
      setMode("login");
      return;
    }
    setError(t("auth.registerError"));
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-lg">
        <div className="space-y-1 text-center">
          <h1 className="text-lg font-semibold text-slate-900">
            {mode === "login" ? t("auth.signIn") : t("auth.register")}
          </h1>
          <p className="text-sm text-slate-500">
            {mode === "login" ? t("auth.loginTagline") : t("auth.registerTagline")}
          </p>
        </div>
        {mode === "login" ? (
          <LoginForm
            loading={loading}
            error={error}
            labels={{ submit: t("auth.signIn"), register: t("auth.noAccount") }}
            fields={{
              email: { label: t("auth.email") },
              password: { label: t("auth.password") },
            }}
            onSubmit={submitLogin}
            onRegister={
              registerDisabled
                ? undefined
                : () => {
                    setMode("register");
                    setError(null);
                  }
            }
          />
        ) : (
          <RegisterForm
            showFullName
            loading={loading}
            error={error}
            labels={{
              submit: t("auth.register"),
              passwordHint: t("auth.passwordHint"),
              mismatch: t("auth.passwordMismatch"),
              login: t("auth.haveAccount"),
            }}
            fields={{
              fullName: { label: t("auth.fullName") },
              email: { label: t("auth.email") },
              password: { label: t("auth.password") },
              confirmPassword: { label: t("auth.confirmPassword") },
            }}
            onSubmit={submitRegister}
            onLogin={() => {
              setMode("login");
              setError(null);
            }}
          />
        )}
        {registerDisabled ? (
          <p className="text-center text-xs text-slate-500">
            {t("auth.registrationDisabled")}
          </p>
        ) : null}
      </div>
    </div>
  );
}
