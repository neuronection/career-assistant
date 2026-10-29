import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { settingsNav, type SettingsNavItem } from "@/config/settingsNav";
import { useAuthStore } from "@/stores/authStore";
import { SettingsShell as LibrarySettingsShell, type SettingsNavItem as LibraryNavItem } from "@neuronection/assistant-ui";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

/** Registry rows → library nav items (pure: unit-tested without the
 * library runtime — the section labels ride the additive `section`
 * prop, which older published bundles ignore gracefully). */
export function toLibraryNav(
  items: SettingsNavItem[],
  t: TFunction
): LibraryNavItem[] {
  return items.map(({ to, icon, labelKey, descriptionKey, sectionKey }) => ({
    id: to,
    icon,
    label: t(labelKey),
    description: descriptionKey ? t(descriptionKey) : undefined,
    section: t(`settingsNav.section.${sectionKey}`),
  }));
}

/**
 * Two-pane settings shell: sticky left nav + right content outlet.
 * Route/role glue over the library `SettingsShell` (adminOnly entries
 * hidden for non-admins; nav grouped into rail sections — plan 148).
 * The wrapper centers and caps at 100rem on ultrawide displays; the
 * library's container queries and the settings kit's `ca-settings`
 * block own every width decision, so a 2K display fills and a docked
 * chat narrows correctly.
 */
export function SettingsShell() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const location = useLocation();
  const visibleNav = settingsNav.filter((item) => !item.adminOnly || user?.is_admin);

  const items = toLibraryNav(visibleNav, t);

  // Exact-or-subpath match; longest id wins so nested routes highlight right.
  const active =
    items
      .filter((item) => location.pathname === item.id || location.pathname.startsWith(item.id + "/"))
      .sort((a, b) => b.id.length - a.id.length)[0]?.id ?? items[0]!.id;

  return (
    <div className="ca-settings-shell">
      <button
        onClick={() => navigate("/")}
        className="text-sm text-slate-400 hover:text-slate-600 inline-flex items-center gap-1 mb-4"
      >
        <ChevronLeft className="w-4 h-4" /> {t("shell.backToApp")}
      </button>
      <LibrarySettingsShell
        nav={items}
        active={active}
        onNavigate={(id) => {
          navigate(id);
          document
            .getElementById("main")
            ?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
        }}
        header={{ title: t("nav.settings") }}
        navClassName="lg:top-0 lg:max-h-[calc(100vh-3.5rem)] lg:overflow-y-auto"
      >
        <Outlet />
      </LibrarySettingsShell>
    </div>
  );
}
