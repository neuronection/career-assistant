import axios from "axios";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  changeMyPassword,
  deleteMyAccount,
  listMySessions,
  revokeMySession,
  type UserSession,
} from "@/api/admin";
import { Button, Card, ConfirmationModal, Spinner } from "@/components/ui";
import { useAuthStore } from "@/stores/authStore";

const MIN_PASSWORD_LENGTH = 10;

function errorText(error: unknown, wrongPassword: string, generic: string): string {
  if (axios.isAxiosError(error)) {
    // The kit answers 403 "Invalid password" on a wrong confirmation
    // (identity-auth §12) — everything else is a detail or generic.
    if (error.response?.status === 403) return wrongPassword;
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail;
    return detail ?? generic;
  }
  return generic;
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

/** Account self-service (identity-auth §12, `/api/v1/me`): the caller's
 * sessions with per-device revocation (revoking the current one drops to
 * the login screen), password change (caller stays signed in, every other
 * session dies) and account deletion behind password confirmation. */
export function Account() {
  const { t } = useTranslation();
  const dropToLogin = useAuthStore((s) => s.dropToLogin);
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<UserSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [deletePassword, setDeletePassword] = useState("");

  const load = useCallback(async () => {
    try {
      setSessions(await listMySessions());
    } catch {
      // keep the last known list; the actions report their own errors
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async () => {
    const target = pendingRevoke;
    if (!target) return;
    setBusy(true);
    try {
      await revokeMySession(target.id);
      setPendingRevoke(null);
      if (target.current) {
        dropToLogin();
        return;
      }
      setError(null);
      setMessage(t("account.revoked"));
      await load();
    } catch (err) {
      setPendingRevoke(null);
      setError(
        errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")),
      );
    } finally {
      setBusy(false);
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword.length < MIN_PASSWORD_LENGTH) return;
    setBusy(true);
    try {
      await changeMyPassword(currentPassword, newPassword);
      setError(null);
      setMessage(t("account.passwordChanged"));
      setCurrentPassword("");
      setNewPassword("");
      await load();
    } catch (err) {
      setError(
        errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")),
      );
    } finally {
      setBusy(false);
    }
  };

  const deleteAccount = async (event: FormEvent) => {
    event.preventDefault();
    if (deletePassword.length === 0) return;
    setBusy(true);
    try {
      await deleteMyAccount(deletePassword);
      dropToLogin();
    } catch (err) {
      setError(
        errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="settings-account">
      <Card className="space-y-6 p-4">
          {error ? (
            <p className="text-sm text-rose-600" role="alert">
              {error}
            </p>
          ) : null}
          {message ? <p className="text-xs text-emerald-600">{message}</p> : null}

          <section aria-label={t("account.sessionsTitle")} className="space-y-2">
            <div>
              <h3 className="text-sm font-medium">{t("account.sessionsTitle")}</h3>
              <p className="text-xs text-slate-500">{t("account.sessionsDescription")}</p>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 py-4 text-xs text-slate-400">
                <Spinner size="sm" />
                {t("account.sessionsLoading")}
              </div>
            ) : sessions.length === 0 ? (
              <p className="text-xs text-slate-400">{t("account.sessionsEmpty")}</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {sessions.map((session) => (
                  <li
                    key={session.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2"
                    data-testid="account-session"
                  >
                    <div className="min-w-0">
                      <p className="text-sm">
                        {session.client_label || "—"}
                        {session.current ? (
                          <span className="ml-2 text-xs text-slate-400">
                            ({t("account.sessionCurrent")})
                          </span>
                        ) : null}
                      </p>
                      <p className="text-xs text-slate-500">
                        {session.created_at
                          ? t("account.sessionCreated", {
                              when: formatDate(session.created_at),
                            })
                          : "—"}
                        {" · "}
                        {t("account.sessionExpires", {
                          when: formatDate(session.expires_at),
                        })}
                      </p>
                    </div>
                    {session.revoked_at ? (
                      <span className="text-xs text-slate-400">
                        {t("account.sessionRevoked")}
                      </span>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPendingRevoke(session)}
                        aria-label={`${t("account.revoke")} — ${session.client_label || session.id}`}
                      >
                        {t("account.revoke")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label={t("account.passwordTitle")} className="space-y-2">
            <div>
              <h3 className="text-sm font-medium">{t("account.passwordTitle")}</h3>
              <p className="text-xs text-slate-500">{t("account.passwordDescription")}</p>
            </div>
            <form
              className="max-w-sm space-y-2"
              onSubmit={(event) => void changePassword(event)}
            >
              <label className="block space-y-1 text-sm">
                <span className="text-slate-600">{t("account.currentPassword")}</span>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                />
              </label>
              <label className="block space-y-1 text-sm">
                <span className="text-slate-600">{t("account.newPassword")}</span>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                />
              </label>
              <p className="text-xs text-slate-500">
                {t("account.newPasswordHint", { minLength: MIN_PASSWORD_LENGTH })}
              </p>
              <Button
                type="submit"
                size="sm"
                disabled={busy || newPassword.length < MIN_PASSWORD_LENGTH}
              >
                {t("account.changePassword")}
              </Button>
            </form>
          </section>

          <section aria-label={t("account.deleteTitle")} className="space-y-2">
            <div>
              <h3 className="text-sm font-medium text-rose-600">
                {t("account.deleteTitle")}
              </h3>
              <p className="text-xs text-slate-500">{t("account.deleteDescription")}</p>
            </div>
            <form
              className="max-w-sm space-y-2"
              onSubmit={(event) => void deleteAccount(event)}
            >
              <label className="block space-y-1 text-sm">
                <span className="text-slate-600">{t("account.deletePasswordLabel")}</span>
                <input
                  className="w-full rounded-md border border-slate-300 px-3 py-2"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={deletePassword}
                  onChange={(event) => setDeletePassword(event.target.value)}
                />
              </label>
              <Button
                type="submit"
                size="sm"
                variant="destructive"
                disabled={busy || deletePassword.length === 0}
              >
                {t("account.deleteAccount")}
              </Button>
            </form>
          </section>
      </Card>
      {pendingRevoke ? (
        <ConfirmationModal
          open
          title={t("account.revokeConfirmTitle")}
          description={
            pendingRevoke.current
              ? t("account.revokeCurrentBody")
              : t("account.revokeConfirmBody")
          }
          confirmLabel={t("account.revoke")}
          cancelLabel={t("common.cancel")}
          destructive
          busy={busy}
          onConfirm={() => void revoke()}
          onOpenChange={(open) => (open ? undefined : setPendingRevoke(null))}
        />
      ) : null}
    </div>
  );
}
