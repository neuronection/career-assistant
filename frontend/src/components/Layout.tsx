import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LogOut, Settings2, UserRound } from "lucide-react";

import { UserMenu } from "@neuronection/assistant-ui";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { ChatWidget } from "@/components/ChatWidget";
import { NotificationBell } from "@/components/NotificationBell";
import { ToastHost } from "@/components/ToastHost";
import { DesktopNotifications } from "@/components/DesktopNotifications";
import { NAV } from "@/config/nav";

export function Layout() {
  const { user, loadUser, logout } = useAuthStore();
  const { bootstrap, load: loadBootstrap } = useBootstrapStore();
  const navigate = useNavigate();

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  useEffect(() => {
    if (user) void loadBootstrap();
  }, [user, loadBootstrap]);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-6">
          <span className="flex items-center gap-2.5 shrink-0">
            <img src="/icon-light.svg" alt="Career Assistant logo" className="w-8 h-8 rounded-lg" />
            <span className="font-bold text-slate-900 text-[15px]">
              Career <span className="text-primary-600">Assistant</span>
            </span>
          </span>
          <nav className="flex gap-1 flex-1" aria-label="Main navigation">
            {NAV.map(({ to, label, icon: Icon, studentOnly }) => {
              if (studentOnly && bootstrap && !bootstrap.features.universities) {
                return null;
              }
              return (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    `px-3 py-2 rounded-lg text-sm flex items-center gap-1.5 ${
                      isActive ? "bg-primary-50 text-primary-700 font-medium" : "text-slate-600 hover:bg-slate-100"
                    }`
                  }
                >
                  <Icon className="w-4 h-4" /> {label}
                </NavLink>
              );
            })}
          </nav>
          <div className="flex items-center gap-2">
            {user && <NotificationBell />}
            {user && (
              <UserMenu
                email={user.email}
                items={[
                  { id: "/profile", label: "Profile", icon: UserRound },
                  { id: "/settings/ai", label: "Settings", icon: Settings2 },
                  { id: "signout", label: "Sign out", icon: LogOut, tone: "danger" },
                ]}
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
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-slate-100 mt-10 py-5">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-400">
          <span>
            Part of{" "}
            <a
              href="https://neuronection.com"
              target="_blank"
              rel="noreferrer"
              className="font-medium text-slate-500 hover:text-primary-600"
            >
              Neuronection
            </a>{" "}
            · intelligent assistants for life&rsquo;s big decisions
          </span>
          <span className="flex items-center gap-3">
            <a href="https://health-assistant.io" className="hover:text-primary-600">
              Health Assistant
            </a>
          </span>
        </div>
      </footer>
      <ChatWidget />
      <ToastHost />
      <DesktopNotifications />
    </div>
  );
}
