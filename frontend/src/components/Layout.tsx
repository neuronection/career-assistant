import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { LogOut, Menu } from "lucide-react";

import { SidebarNav, UserMenu } from "@neuronection/assistant-ui";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useIsShortViewport } from "@/hooks/useMediaQuery";
import { ChatWidget } from "@/components/ChatWidget";
import { NotificationBell } from "@/components/NotificationBell";
import { SidebarFooter } from "@/components/SidebarFooter";
import { ToastHost } from "@/components/ToastHost";
import { DesktopNotifications } from "@/components/DesktopNotifications";
import { NAV, resolveActiveId } from "@/config/nav";

export function Layout() {
  const { user, loadUser, logout } = useAuthStore();
  const { bootstrap, load: loadBootstrap } = useBootstrapStore();
  const navigate = useNavigate();
  const location = useLocation();

  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const isShort = useIsShortViewport();

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  useEffect(() => {
    if (user) void loadBootstrap();
  }, [user, loadBootstrap]);

  // Close the mobile drawer on navigation (desktop is unaffected — the
  // sidebar is permanently visible at lg+).
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname, location.search]);

  const enabled = (item: (typeof NAV)[number]) =>
    !(item.studentOnly && bootstrap && !bootstrap.features.universities);
  const toNavItem = ({ to, label, icon, section }: (typeof NAV)[number]) => ({
    id: to,
    label,
    icon,
    ...(section ? { section } : {}),
  });

  const items = NAV.filter(enabled).map(toNavItem);

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Skip to content — first focusable element for keyboard users */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-primary-600 focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        Skip to content
      </a>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* Sidebar — off-canvas drawer below lg, permanent panel above */}
      <div
        className={`fixed inset-y-0 left-0 z-50 transition-transform duration-200 ease-in-out lg:relative lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        <SidebarNav
          items={items}
          activeId={resolveActiveId(location.pathname)}
          onNavigate={(id) => navigate(id)}
          collapsed={collapsed}
          onCollapsedChange={setCollapsed}
          collapsible
          compact={isShort}
          className="h-full border-slate-200 bg-white shadow-lg lg:shadow-none"
          header={
            <div className={`flex h-14 items-center border-b border-slate-100 ${collapsed ? "justify-center px-2" : "gap-2.5 px-4"}`}>
              <img src="/icon-light.svg" alt="Career Assistant logo" className="h-8 w-8 shrink-0 rounded-lg" />
              {!collapsed && (
                <span className="truncate text-[15px] font-bold text-slate-900">
                  Career <span className="text-primary-600">Assistant</span>
                </span>
              )}
            </div>
          }
          footer={<SidebarFooter collapsed={collapsed} compact={isShort} />}
        />
      </div>

      {/* Content column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-4">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            {user && <NotificationBell />}
            {user && (
              <UserMenu
                name={user.full_name || undefined}
                email={user.email}
                items={[{ id: "signout", label: "Sign out", icon: LogOut, tone: "danger" }]}
                onItemSelect={(id) => {
                  if (id === "signout") {
                    logout();
                    navigate("/login");
                    return;
                  }
                  navigate(id);
                }}
              />
            )}
          </div>
        </header>
        <main id="main" className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-4 py-6">
            <Outlet />
          </div>
        </main>
      </div>

      <ChatWidget />
      <ToastHost />
      <DesktopNotifications />
    </div>
  );
}
