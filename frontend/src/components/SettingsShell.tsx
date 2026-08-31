import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { settingsNav } from "@/config/settingsNav";
import { useAuthStore } from "@/stores/authStore";
import { SettingsShell as LibrarySettingsShell } from "@neuronection/assistant-ui";

/**
 * Two-pane settings shell: sticky left nav + right content outlet.
 * Route/role glue over the library `SettingsShell` (adminOnly entries
 * hidden for non-admins).
 */
export function SettingsShell() {
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const location = useLocation();
  const visibleNav = settingsNav.filter((item) => !item.adminOnly || user?.is_admin);

  const items = visibleNav.map(({ to, icon, label, description }) => ({
    id: to,
    icon,
    label,
    description,
  }));

  // Exact-or-subpath match; longest id wins so nested routes highlight right.
  const active =
    items
      .filter((item) => location.pathname === item.id || location.pathname.startsWith(item.id + "/"))
      .sort((a, b) => b.id.length - a.id.length)[0]?.id ?? items[0]!.id;

  return (
    <div className="max-w-6xl mx-auto">
      <button
        onClick={() => navigate("/")}
        className="text-sm text-slate-400 hover:text-slate-600 inline-flex items-center gap-1 mb-4"
      >
        <ChevronLeft className="w-4 h-4" /> Back to app
      </button>
      <LibrarySettingsShell
        nav={items}
        active={active}
        onNavigate={(id) => navigate(id)}
        header={{ title: "Settings" }}
      >
        <Outlet />
      </LibrarySettingsShell>
    </div>
  );
}
