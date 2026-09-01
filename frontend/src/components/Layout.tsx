import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Briefcase, Building2, CalendarRange, ClipboardList, Globe, Info, LayoutDashboard, Route, Search, Settings2, Sparkles, Trophy, UserRound } from "lucide-react";

import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { ChatWidget } from "@/components/ChatWidget";
import { NotificationBell } from "@/components/NotificationBell";
import { ToastHost } from "@/components/ToastHost";
import { DesktopNotifications } from "@/components/DesktopNotifications";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, studentOnly: false },
  { to: "/catalog", label: "Catalog", icon: Briefcase, studentOnly: false },
  { to: "/generate", label: "Generate", icon: Sparkles, studentOnly: false },
  { to: "/rankings", label: "Rankings", icon: Trophy, studentOnly: false },
  { to: "/postings", label: "Live", icon: Globe, studentOnly: false },
  { to: "/explore", label: "Explore", icon: Search, studentOnly: false },
  { to: "/growth", label: "Growth", icon: Route, studentOnly: false },
  { to: "/assessment", label: "Assessment", icon: ClipboardList, studentOnly: false },
  { to: "/universities", label: "Universities", icon: Building2, studentOnly: true },
  { to: "/profile", label: "Profile", icon: UserRound, studentOnly: false },
  { to: "/experience", label: "Experience", icon: CalendarRange, studentOnly: false },
  { to: "/about", label: "About", icon: Info, studentOnly: false },
  { to: "/settings/ai", label: "Settings", icon: Settings2, studentOnly: false },
];

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
              <button
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
                className="text-sm text-slate-500 hover:text-slate-800"
              >
                {user.email} · Sign out
              </button>
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
