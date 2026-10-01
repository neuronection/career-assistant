import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  fetchUsers,
  forceLogout,
  updateInstanceMode,
  patchUser,
  resetUserPassword,
  type AdminUser,
} from "@/api/admin";
import { getInstanceConfig } from "@/api/instance";
import {
  AdminUserTable,
  type AdminUserTableLabels,
} from "@/components/ui/admin-user-table";
import {
  InstanceModeControl,
  type InstanceModeControlLabels,
} from "@/components/ui/instance-mode-control";
import { useAuthStore } from "@/stores/authStore";

/** Admin user management (identity-auth §12): the shared
 * `AdminUserTable` (`@neuronection/assistant-ui`) fed by the kit's
 * `/api/v1/admin/users` API — career's local table is gone (the two-app
 * same-commit delete). Actions persist through the api layer and
 * re-supply the list; guard-rail 403s surface through the table's error
 * mapping. Admin-only — the settings nav hides the entry for everyone
 * else. */
export function Users() {
  const { t } = useTranslation();
  const me = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<unknown>(null);
  const [authMode, setAuthMode] = useState<string>("authenticated");
  const [instanceError, setInstanceError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setUsers(await fetchUsers());
      setListError(null);
    } catch (error) {
      setListError(error);
    } finally {
      setLoading(false);
    }
    try {
      setAuthMode((await getInstanceConfig()).auth_mode);
      setInstanceError(null);
    } catch (error) {
      setInstanceError(error);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const labels: AdminUserTableLabels = {
    tableCaption: t("users.tableCaption"),
    you: t("users.you"),
    email: t("users.email"),
    activity: t("users.activity"),
    role: t("users.role"),
    status: t("users.status"),
    actions: t("users.actions"),
    adminRole: t("users.adminRole"),
    userRole: t("users.userRole"),
    activeStatus: t("users.activeStatus"),
    disabledStatus: t("users.disabledStatus"),
    promote: t("users.promote"),
    demote: t("users.demote"),
    activate: t("users.activate"),
    deactivate: t("users.deactivate"),
    resetPassword: t("users.resetPassword"),
    forceLogout: t("users.forceLogout"),
    loading: t("users.loading"),
    empty: t("users.empty"),
    resetTitle: (email: string) => t("users.newPasswordFor", { email }),
    newPassword: t("users.newPassword"),
    passwordHint: (minLength: number) => t("users.minChars", { minLength }),
    setPassword: t("users.setPassword"),
    cancel: t("common.cancel"),
    resetNote: (email: string) => t("users.resetNote", { email }),
    errorGeneric: t("users.errorGeneric"),
    errorForbidden: t("users.errorForbidden"),
    errorSelf: t("users.errorSelf"),
    errorLastAdmin: t("users.errorLastAdmin"),
  };

  const instanceLabels: InstanceModeControlLabels = {
    title: t("instance.title"),
    modeOpen: t("instance.modeOpen"),
    modeAuthenticated: t("instance.modeAuthenticated"),
    modeOpenHint: t("instance.modeOpenHint"),
    modeAuthenticatedHint: t("instance.modeAuthenticatedHint"),
    enableLogin: t("instance.enableLogin"),
    enableLoginNote: (minLength: number) => t("instance.enableLoginNote", { minLength }),
    disableLogin: t("instance.disableLogin"),
    disableLoginNote: t("instance.disableLoginNote"),
    password: t("instance.password"),
    confirmPassword: t("instance.confirmPassword"),
    passwordMismatch: t("instance.passwordMismatch"),
    passwordTooShort: (minLength: number) => t("instance.passwordTooShort", { minLength }),
    submitEnable: t("instance.submitEnable"),
    submitDisable: t("instance.submitDisable"),
    confirmAck: t("instance.confirmAck"),
    blockedServer: t("instance.blockedServer"),
    blockedUsers: (count: number) => t("instance.blockedUsers", { count }),
    auditNote: t("instance.auditNote"),
    errorGeneric: t("instance.errorGeneric"),
    errorForbidden: t("instance.errorForbidden"),
  };

  return (
    <div data-testid="settings-users" className="space-y-6">
      <InstanceModeControl
        mode={authMode === "open" ? "open" : "authenticated"}
        otherUserCount={Math.max(0, users.length - 1)}
        loading={loading}
        error={instanceError === null ? null : t("instance.errorGeneric")}
        onSetAuthenticated={async (password: string) => {
          await updateInstanceMode("authenticated", password);
          await load();
        }}
        onSetOpen={async (password: string) => {
          await updateInstanceMode("open", password);
          await load();
        }}
        labels={instanceLabels}
      />
      <AdminUserTable
        users={users}
        currentUserId={me?.id ?? ""}
        loading={loading}
        error={listError === null ? null : t("users.errorGeneric")}
        onPatch={async (user, patch) => {
          await patchUser(user.id, patch);
          await load();
        }}
        onResetPassword={async (user, newPassword) => {
          await resetUserPassword(user.id, newPassword);
          await load();
        }}
        onForceLogout={async (user) => {
          await forceLogout(user.id);
          await load();
        }}
        labels={labels}
      />
    </div>
  );
}
