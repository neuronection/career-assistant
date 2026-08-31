import { useCallback, useEffect, useState } from "react";
import {
  fetchUsers,
  forceLogout,
  patchUser,
  resetUserPassword,
  type AdminUser,
} from "@/api/admin";
import { apiDetail } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { EmptyState, Spinner } from "@/components/ui";

/** Admin user management: activate/deactivate, promote/demote, reset, revoke. */
export function Users() {
  const me = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await fetchUsers());
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = async (user: AdminUser, body: { is_active?: boolean; is_admin?: boolean }) => {
    setError("");
    try {
      await patchUser(user.id, body);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const doReset = async () => {
    if (!resetting) return;
    setError("");
    try {
      await resetUserPassword(resetting.id, newPassword);
      setNote(`Password reset for ${resetting.email} — share it out-of-band.`);
      setResetting(null);
      setNewPassword("");
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="space-y-4" data-testid="settings-users">
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {note && <p className="text-xs text-emerald-600">{note}</p>}
      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">Loading…</p>
        </div>
      ) : users.length === 0 ? (
        <EmptyState title="No users" />
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Matches</th>
                <th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = me?.id === u.id;
                return (
                  <tr key={u.id} className="border-t border-slate-100">
                    <td className="px-4 py-2">
                      {u.email}
                      {isSelf && <span className="text-xs text-slate-400"> (you)</span>}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{u.insight_count}</td>
                    <td className="px-4 py-2">
                      {u.is_admin ? (
                        <span className="text-primary-700">admin</span>
                      ) : (
                        "user"
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {u.is_active ? (
                        <span className="text-emerald-600">active</span>
                      ) : (
                        <span className="text-rose-600">disabled</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                      {!isSelf && (
                        <>
                          <button
                            onClick={() => void patch(u, { is_admin: !u.is_admin })}
                            className="text-xs text-slate-500 hover:text-primary-700"
                          >
                            {u.is_admin ? "Demote" : "Promote"}
                          </button>
                          <button
                            onClick={() => void patch(u, { is_active: !u.is_active })}
                            className="text-xs text-slate-500 hover:text-amber-700"
                          >
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                          <button
                            onClick={() => setResetting(u)}
                            className="text-xs text-slate-500 hover:text-primary-700"
                          >
                            Reset password
                          </button>
                          <button
                            onClick={() => void forceLogout(u.id).then(load)}
                            className="text-xs text-slate-400 hover:text-rose-600"
                          >
                            Force logout
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {resetting && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 space-y-2 max-w-md">
          <p className="text-sm font-medium">New password for {resetting.email}</p>
          <input
            type="text"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="min 10 characters"
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <button
              onClick={() => void doReset()}
              disabled={newPassword.length < 10}
              className="bg-primary-600 text-white rounded-lg px-3 py-1.5 text-sm disabled:opacity-50"
            >
              Set password
            </button>
            <button
              onClick={() => setResetting(null)}
              className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
