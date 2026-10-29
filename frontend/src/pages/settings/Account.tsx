import axios from "axios";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  CircleUser,
  Download,
  FileArchive,
  KeyRound,
  Languages,
  Laptop,
  LogOut,
  Monitor,
  ShieldX,
  Smartphone,
  Tablet,
  UserPlus,
} from "lucide-react";

import {
  changeMyPassword,
  deleteMyAccount,
  listMySessions,
  logoutAllDevices,
  revokeMySession,
  type UserSession,
} from "@/api/admin";
import {
  fetchBackgroundJob,
  isTerminal,
  requestExport,
  downloadExport,
} from "@/api/backgroundJobs";
import {
  fetchInstanceLocale,
  fetchLocale,
  setInstanceLocale,
  setMyLocale,
} from "@/api/i18n";
import { createProfile, listProfiles, patchProfile } from "@/api/profiles";
import { LOCALE_LABELS, SUPPORTED_LOCALES, setAppLocale } from "@/lib/i18n";
import { formatDateTime } from "@/lib/format";
import {
  Badge,
  Button,
  ConfirmationModal,
} from "@/components/ui";
import { Input } from "@neuronection/assistant-ui";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import type { SettingsSaveState } from "@/components/settings/saveState";
import { useAuthStore } from "@/stores/authStore";
import { useProfilesStore } from "@/stores/profilesStore";

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
  return iso ? formatDateTime(iso) : "—";
}

function deviceIcon(label: string) {
  const lower = label.toLowerCase();
  if (lower.includes("phone") || lower.includes("android")) return Smartphone;
  if (lower.includes("ipad") || lower.includes("tablet")) return Tablet;
  if (lower.includes("linux") || lower.includes("mac") || lower.includes("windows")) return Laptop;
  return Monitor;
}

/** Account self-service (identity-auth §12, plan 148 phase 4): identity
 * header with the profile surface, appearance, signed-in devices with
 * sign-out-everywhere, password change, the GDPR data export and the
 * deletion danger zone (armed two-step confirm). */
export function Account() {
  const { t } = useTranslation();
  const dropToLogin = useAuthStore((s) => s.dropToLogin);
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);

  const sections = useMemo(
    () => [
      { id: "s-identity", label: t("account.profilesTitle") },
      { id: "s-appearance", label: t("account.appearanceTitle") },
      { id: "s-sessions", label: t("account.sessionsTitle") },
      { id: "s-security", label: t("account.securityTitle") },
      { id: "s-data", label: t("account.dataTitle") },
      { id: "s-delete", label: t("account.deleteTitle") },
    ],
    [t]
  );

  return (
    <SettingsPage
      icon={CircleUser}
      title={t("settingsNav.account.label")}
      description={t("settingsNav.account.description")}
      sections={sections}
    >
      <div className="space-y-4" data-testid="account-page">
      <IdentityCard />
      <section id="s-appearance" className="mt-4 scroll-mt-4">
        <AppearanceCard isAdmin={isAdmin} />
      </section>
      <section id="s-sessions" className="mt-4 scroll-mt-4">
        <SessionsCard dropToLogin={dropToLogin} />
      </section>
      <section id="s-security" className="mt-4 scroll-mt-4">
        <SecurityCard />
      </section>
      <section id="s-data" className="mt-4 scroll-mt-4">
        <DataExportCard />
      </section>
      <section id="s-delete" className="mt-4 scroll-mt-4">
        <DeleteAccountCard dropToLogin={dropToLogin} />
      </section>
      </div>
    </SettingsPage>
  );
}

function IdentityCard() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const currentId = useProfilesStore((s) => s.currentId);
  const [profiles, setProfiles] = useState(useProfilesStore.getState().profiles);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProfiles(await listProfiles());
    } catch {
      setProfiles([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const initials = useMemo(() => {
    const base = user?.full_name || user?.email || "?";
    return base
      .split(/[\s@._]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]!.toUpperCase())
      .join("");
  }, [user?.full_name, user?.email]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (newName.trim().length === 0) return;
    setBusy(true);
    try {
      await createProfile(newName.trim());
      setNewName("");
      await refresh();
    } catch {
      setNotice(t("account.profileCreateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const setDefault = async (id: string) => {
    setBusy(true);
    try {
      await patchProfile(id, { is_default: true });
      await refresh();
    } catch {
      setNotice(t("account.profileUpdateFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsSectionCard
      name="identity"
      title={t("account.profilesTitle")}
      description={t("account.profilesDescription")}
      icon={CircleUser}
      footer={
        <form className="flex w-full flex-wrap items-center gap-2" onSubmit={(event) => void create(event)}>
          <Input
            value={newName}
            placeholder={t("account.newProfilePlaceholder")}
            aria-label={t("account.newProfilePlaceholder")}
            onChange={(event) => setNewName(event.target.value)}
            className="max-w-60 flex-1"
            data-testid="new-profile-name"
          />
          <Button type="submit" size="sm" variant="outline" disabled={busy || newName.trim().length === 0} data-testid="create-profile">
            <UserPlus className="h-3.5 w-3.5" /> {t("account.createProfile")}
          </Button>
          {notice ? <span className="text-xs text-[var(--as-danger)]">{notice}</span> : null}
        </form>
      }
    >
      <div className="mb-3 flex items-center gap-3">
        <span
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--as-primary)_14%,var(--as-surface-raised))] text-sm font-bold text-[var(--as-primary)]"
          aria-hidden
        >
          {initials}
        </span>
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
            <span data-testid="account-identity-name">{user?.full_name || user?.email}</span>
            {user?.is_admin ? (
              <Badge variant="outline" data-testid="account-admin-badge">
                {t("settingsKit.adminBadge")}
              </Badge>
            ) : null}
          </p>
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="account-identity-email">
            {user?.email}
          </p>
        </div>
      </div>
      <ul className="divide-y divide-[var(--as-border)]" data-testid="account-profiles">
        {profiles.map((profile) => (
          <li key={profile.id} className="flex flex-wrap items-center gap-2 py-2" data-testid={`account-profile-${profile.id}`}>
            <span className="text-sm font-medium text-[var(--as-fg)]">{profile.name}</span>
            {profile.is_default ? (
              <Badge variant="secondary">{t("account.defaultProfile")}</Badge>
            ) : null}
            {profile.id === currentId ? (
              <Badge variant="success">{t("account.activeProfile")}</Badge>
            ) : null}
            {!profile.is_default ? (
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto"
                disabled={busy}
                onClick={() => void setDefault(profile.id)}
              >
                {t("account.makeDefault")}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </SettingsSectionCard>
  );
}

function AppearanceCard({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useTranslation();
  const [locale, setLocaleState] = useState("en");
  const [instanceLocale, setInstanceLocaleState] = useState("en");
  const [localeBusy, setLocaleBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchLocale()
      .then((state) => setLocaleState(state.locale))
      .catch(() => undefined);
    if (isAdmin) {
      fetchInstanceLocale()
        .then((state) => setInstanceLocaleState(state.locale))
        .catch(() => undefined);
    }
  }, [isAdmin]);

  const chooseLocale = async (next: string) => {
    setLocaleBusy(true);
    setSaved(false);
    try {
      const state = await setMyLocale(next);
      setLocaleState(state.locale);
      await setAppLocale(state.locale as (typeof SUPPORTED_LOCALES)[number]);
      setError(null);
      setSaved(true);
    } catch {
      setError(t("account.localeError"));
    } finally {
      setLocaleBusy(false);
    }
  };

  const chooseInstanceLocale = async (next: string) => {
    setLocaleBusy(true);
    try {
      const state = await setInstanceLocale(next);
      setInstanceLocaleState(state.locale);
      setError(null);
    } catch {
      setError(t("account.localeError"));
    } finally {
      setLocaleBusy(false);
    }
  };

  return (
    <SettingsSectionCard
      name="appearance"
      title={t("account.appearanceTitle")}
      description={t("account.appearanceDescription")}
      icon={Languages}
      saveState={saved ? "saved" : error ? "error" : "idle"}
      saveError={error ?? undefined}
    >
      <div className="flex flex-wrap gap-1.5" data-testid="account-appearance">
        {SUPPORTED_LOCALES.map((code) => (
          <Button
            key={code}
            variant={locale === code ? "default" : "outline"}
            size="sm"
            disabled={localeBusy}
            data-testid={`locale-${code}`}
            aria-pressed={locale === code}
            onClick={() => void chooseLocale(code)}
          >
            {LOCALE_LABELS[code]}
          </Button>
        ))}
      </div>
      {isAdmin ? (
        <div className="mt-3 space-y-1.5 border-t border-[var(--as-border)] pt-3">
          <p className="text-xs font-semibold text-[var(--as-fg)]">
            {t("account.instanceLocaleTitle")}
          </p>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("account.instanceLocaleDescription")}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {SUPPORTED_LOCALES.map((code) => (
              <Button
                key={code}
                variant={instanceLocale === code ? "default" : "outline"}
                size="sm"
                disabled={localeBusy}
                data-testid={`instance-locale-${code}`}
                aria-pressed={instanceLocale === code}
                onClick={() => void chooseInstanceLocale(code)}
              >
                {LOCALE_LABELS[code]}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
    </SettingsSectionCard>
  );
}

function SessionsCard({ dropToLogin }: { dropToLogin: () => void }) {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<UserSession | null>(null);
  const [pendingLogoutAll, setPendingLogoutAll] = useState(false);
  const [busy, setBusy] = useState(false);

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
      setError(errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")));
    } finally {
      setBusy(false);
    }
  };

  const logoutEverywhere = async () => {
    setBusy(true);
    try {
      await logoutAllDevices();
      dropToLogin();
    } catch (err) {
      setPendingLogoutAll(false);
      setError(errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsSectionCard
      name="sessions"
      title={t("account.sessionsTitle")}
      description={t("account.sessionsDescription")}
      icon={LogOut}
      badges={
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => setPendingLogoutAll(true)}
          data-testid="logout-all"
        >
          {t("account.signOutEverywhere")}
        </Button>
      }
    >
      {error ? (
        <p className="mb-2 text-xs text-[var(--as-danger)]" role="alert">
          {error}
        </p>
      ) : null}
      {message ? (
        <p className="mb-2 text-xs text-emerald-600" data-testid="sessions-message">
          {message}
        </p>
      ) : null}
      {loading ? (
        <p className="py-2 text-xs text-[var(--as-muted-fg)]">{t("account.sessionsLoading")}</p>
      ) : sessions.length === 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]">{t("account.sessionsEmpty")}</p>
      ) : (
        <ul className="divide-y divide-[var(--as-border)]">
          {sessions.map((session) => {
            const Glyph = deviceIcon(session.client_label);
            return (
              <li
                key={session.id}
                className="flex flex-wrap items-center gap-2 py-2"
                data-testid="account-session"
                data-current={session.current ? "true" : undefined}
              >
                <Glyph className="h-4 w-4 shrink-0 text-[var(--as-muted-fg)]" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm text-[var(--as-fg)]">
                    <span className="font-medium">{session.client_label || "—"}</span>
                    {session.current ? (
                      <Badge variant="success">{t("account.sessionCurrent")}</Badge>
                    ) : null}
                    {session.revoked_at ? (
                      <Badge variant="outline">{t("account.sessionRevoked")}</Badge>
                    ) : null}
                  </p>
                  <p className="text-xs text-[var(--as-muted-fg)]">
                    {session.created_at
                      ? t("account.sessionCreated", { when: formatDate(session.created_at) })
                      : "—"}
                    {" · "}
                    {t("account.sessionExpires", { when: formatDate(session.expires_at) })}
                  </p>
                </div>
                {!session.revoked_at ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPendingRevoke(session)}
                    aria-label={`${t("account.revoke")} — ${session.client_label || session.id}`}
                  >
                    {t("account.revoke")}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmationModal
        open={pendingRevoke !== null}
        title={t("account.revokeConfirmTitle")}
        description={
          pendingRevoke?.current
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
      <ConfirmationModal
        open={pendingLogoutAll}
        title={t("account.logoutAllConfirmTitle")}
        description={t("account.logoutAllConfirmBody")}
        confirmLabel={t("account.signOutEverywhere")}
        cancelLabel={t("common.cancel")}
        destructive
        busy={busy}
        onConfirm={() => void logoutEverywhere()}
        onOpenChange={(open) => (open ? undefined : setPendingLogoutAll(false))}
      />
    </SettingsSectionCard>
  );
}

function SecurityCard() {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<SettingsSaveState>("idle");

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (newPassword.length < MIN_PASSWORD_LENGTH) return;
    setBusy(true);
    setState("saving");
    try {
      await changeMyPassword(currentPassword, newPassword);
      setError(null);
      setMessage(t("account.passwordChanged"));
      setCurrentPassword("");
      setNewPassword("");
      setState("saved");
    } catch (err) {
      setMessage(null);
      setError(errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")));
      setState("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsSectionCard
      name="security"
      title={t("account.securityTitle")}
      description={t("account.passwordDescription")}
      icon={KeyRound}
      saveState={state === "error" ? "idle" : state}
    >
      {error ? (
        <p className="text-xs text-[var(--as-danger)]" role="alert">
          {error}
        </p>
      ) : null}
      <form
        className="max-w-sm space-y-2"
        onSubmit={(event) => void changePassword(event)}
        data-testid="account-password-form"
      >
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--as-muted-fg)]">{t("account.currentPassword")}</span>
          <input
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
            type="password"
            autoComplete="current-password"
            required
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </label>
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--as-muted-fg)]">{t("account.newPassword")}</span>
          <input
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD_LENGTH}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </label>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t("account.newPasswordHint", { minLength: MIN_PASSWORD_LENGTH })}
        </p>
        {message ? (
          <p className="text-xs text-emerald-600" data-testid="password-message">
            {message}
          </p>
        ) : null}
        <Button
          type="submit"
          size="sm"
          disabled={busy || newPassword.length < MIN_PASSWORD_LENGTH}
        >
          {t("account.changePassword")}
        </Button>
      </form>
    </SettingsSectionCard>
  );
}

function DataExportCard() {
  const { t } = useTranslation();
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = async () => {
    setBusy(true);
    setError(null);
    try {
      const id = await requestExport();
      setJobId(id);
      setStatus(t("account.exportPreparing"));
      void poll(id);
    } catch (err) {
      setError(errorText(err, t("account.exportFailed"), t("account.exportFailed")));
    } finally {
      setBusy(false);
    }
  };

  const poll = async (id: string) => {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      try {
        const job = await fetchBackgroundJob(id);
        if (isTerminal(job)) {
          if (job.status === "succeeded") {
            setStatus(t("account.exportReady"));
            setReady(true);
          } else {
            setStatus(t("account.exportFailed"));
          }
          return;
        }
      } catch {
        // transient poll errors keep the loop going
      }
    }
    setStatus(t("account.exportFailed"));
  };

  return (
    <SettingsSectionCard
      name="data"
      title={t("account.dataTitle")}
      description={t("account.dataDescription")}
      icon={FileArchive}
      footer={
        <>
          {!ready ? (
            <Button size="sm" variant="outline" disabled={busy || jobId !== null} onClick={() => void request()} data-testid="export-request">
              {t("account.exportRequest")}
            </Button>
          ) : (
            <Button size="sm" onClick={() => jobId && void downloadExport(jobId)} data-testid="export-download">
              <Download className="h-3.5 w-3.5" /> {t("account.exportDownload")}
            </Button>
          )}
          {status ? (
            <span className="text-xs text-[var(--as-muted-fg)]" data-testid="export-status">
              {status}
            </span>
          ) : null}
          {error ? <span className="text-xs text-[var(--as-danger)]">{error}</span> : null}
        </>
      }
    >
      <p className="text-xs text-[var(--as-muted-fg)]">{t("account.exportNote")}</p>
    </SettingsSectionCard>
  );
}

function DeleteAccountCard({ dropToLogin }: { dropToLogin: () => void }) {
  const { t } = useTranslation();
  const [deletePassword, setDeletePassword] = useState("");
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const execute = async (event: FormEvent) => {
    event.preventDefault();
    if (!armed || deletePassword.length === 0) return;
    setBusy(true);
    try {
      await deleteMyAccount(deletePassword);
      dropToLogin();
    } catch (err) {
      setError(errorText(err, t("account.errorWrongPassword"), t("account.errorGeneric")));
      setArmed(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsSectionCard
      name="delete-account"
      title={t("account.deleteTitle")}
      description={t("account.deleteDescription")}
      icon={ShieldX}
      variant="danger"
      footer={
        <form className="flex w-full max-w-sm flex-wrap items-center gap-2" onSubmit={(event) => void execute(event)}>
          <label className="block w-full text-xs text-[var(--as-muted-fg)]">
            {t("account.deletePasswordLabel")}
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={deletePassword}
              aria-label={t("account.deletePasswordLabel")}
              onChange={(event) => {
                setDeletePassword(event.target.value);
                setArmed(false);
              }}
              className="mt-1 w-full"
            />
          </label>
          <div className="flex items-center gap-2">
            {armed ? (
              <>
                <Button type="submit" size="sm" disabled={busy} data-testid="delete-account-confirm">
                  {t("account.deleteConfirm")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setArmed(false)}
                  data-testid="delete-account-cancel"
                >
                  {t("common.cancel")}
                </Button>
              </>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={busy || deletePassword.length === 0}
                onClick={() => setArmed(true)}
                data-testid="delete-account-arm"
              >
                {t("account.deleteAccount")}
              </Button>
            )}
            {error ? <span className="text-xs text-[var(--as-danger)]">{error}</span> : null}
          </div>
        </form>
      }
    >
      <p className="text-xs text-[var(--as-muted-fg)]">{t("account.deleteArmedNote")}</p>
    </SettingsSectionCard>
  );
}
