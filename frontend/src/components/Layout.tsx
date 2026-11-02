import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Menu } from "lucide-react";

import { SidebarNav, TooltipProvider, UserMenu } from "@neuronection/assistant-ui";
import { useAuthStore } from "@/stores/authStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useIsShortViewport } from "@/hooks/useMediaQuery";
import { ChatDock, ChatWidget } from "@/features/chat/components/chat/ChatWidget";
import { effectiveChatMode, useChatStore } from "@/stores/chatStore";
import { NotificationBell } from "@/components/NotificationBell";
import { loadUpdateCheck } from "@/components/UpdateBadge";
import { currentLocale, isSupportedLocale, setAppLocale } from "@/lib/i18n";
import { ProfileSwitcherMenu } from "@/components/ProfileSwitcherMenu";
import { SidebarFooter } from "@/components/SidebarFooter";
import { ToastHost } from "@/components/ToastHost";
import { CompareTray } from "@/features/catalog/components/CompareTray";
import { DesktopNotifications } from "@/components/DesktopNotifications";
import {
  extensionNavItems,
  resolveActiveId,
  toNavItem,
  visibleNav,
  type AppNavItem,
} from "@/config/nav";
import { useExtensionSurfacesStore } from "@/stores/extensionSurfacesStore";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";
import { useProfilesStore } from "@/stores/profilesStore";
import { BetaBanner } from "@/components/BetaBanner";
import { FirstRunSetupGate } from "@/features/profile/components/onboarding/FirstRunSetupGate";
import { AiMockChip } from "@/components/ai/AiSetupPrompt";
import { useMainScrollRestoration } from "@/hooks/useMainScrollRestoration";

export function Layout() {
  const { t } = useTranslation();
  const { user, loadUser } = useAuthStore();
  const { bootstrap, load: loadBootstrap } = useBootstrapStore();
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLElement | null>(null);
  useMainScrollRestoration(mainRef);

  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [updateCheck, setUpdateCheck] = useState<Awaited<
    ReturnType<typeof loadUpdateCheck>
  >>(null);
  useEffect(() => {
    let alive = true;
    void loadUpdateCheck().then((value) => {
      if (alive) setUpdateCheck(value);
    });
    return () => {
      alive = false;
    };
  }, []);
  const isAdmin = useAuthStore((state) => state.user?.is_admin ?? false);
  const isShort = useIsShortViewport();
  const isBuilderRoute = useMatch("/cv/:id") !== null;
  const isTemplateRoute = useMatch("/cv/templates/:id") !== null;
  const isExperienceRoute = useMatch("/profile/experience") !== null;
  const isEducationRoute = useMatch("/profile/education") !== null;
  const isApplicationsRoute = useMatch("/applications") !== null;
  const isPathsRoute = useMatch("/paths") !== null;
  const chatMode = useChatStore((state) => state.chatMode);
  const chatModeChosen = useChatStore((state) => state.chatModeChosen);
  const profileEpoch = useProfilesStore((state) => state.epoch);
  const isSettingsRoute = location.pathname.startsWith("/settings");
  const fullBleed =
    isBuilderRoute ||
    isTemplateRoute ||
    isExperienceRoute ||
    isEducationRoute ||
    isApplicationsRoute ||
    isPathsRoute ||
    isSettingsRoute ||
    location.pathname === "/onboarding" ||
    location.pathname === "/onboarding/setup" ||
    location.pathname === "/chat";

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  useEffect(() => {
    if (user) void loadBootstrap();
  }, [user, loadBootstrap]);

  useEffect(() => {
    const locale = bootstrap?.locale;
    if (locale && isSupportedLocale(locale) && locale !== currentLocale()) {
      void setAppLocale(locale);
    }
  }, [bootstrap?.locale]);

  // Close the mobile drawer on navigation (desktop is unaffected — the
  // sidebar is permanently visible at lg+).
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname, location.search]);

  const enabled = (item: AppNavItem) =>
    !(item.studentOnly && bootstrap && !bootstrap.features.universities);
  const pendingProposals = useProfileProposalsStore((state) => state.pendingCount);

  useEffect(() => {
    // Pending HITL cards (plan 77) badge the Profile nav entry app-wide —
    // the chat surfaces keep the count fresh afterwards.
    void useProfileProposalsStore.getState().hydrate();
  }, []);

  const surfaceCards = useExtensionSurfacesStore((state) => state.cards);
  const items = [
    ...visibleNav().filter(enabled).map((item) => toNavItem(item, t, pendingProposals)),
    ...extensionNavItems(surfaceCards, t),
  ];

  return (
    <TooltipProvider>
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Skip to content — first focusable element for keyboard users */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-primary-600 focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        {t("shell.skipToContent")}
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
            <button
              type="button"
              onClick={() => navigate("/")}
              aria-label={t("nav.dashboard")}
              className={`flex h-14 w-full items-center border-b border-slate-100 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-600 ${
                collapsed ? "justify-center px-2" : "gap-2.5 px-4"
              }`}
            >
              <img src="/icon-light.svg" alt="Career Assistant logo" className="h-8 w-8 shrink-0 rounded-lg" />
              {!collapsed && (
                <span className="truncate text-[15px] font-bold text-slate-900">
                  Career <span className="text-primary-600">Assistant</span>
                </span>
              )}
            </button>
          }
          footer={
            <SidebarFooter collapsed={collapsed} compact={isShort} />
          }
        />
      </div>

      {/* Content column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-4">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label={t("shell.openNavigation")}
            aria-expanded={mobileOpen}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-600 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <AiMockChip />
            {user && <ProfileSwitcherMenu />}
            {user && <NotificationBell />}
            {user && (
              <UserMenu
                user={
                  user.full_name
                    ? { name: user.full_name, email: user.email }
                    : { email: user.email }
                }
                status={
                  updateCheck?.update_available && updateCheck.latest_version
                    ? {
                        label: t("update.tooltip", {
                          version: updateCheck.latest_version,
                        }),
                        tone: "info",
                      }
                    : undefined
                }
                items={
                  isAdmin && updateCheck?.update_available
                    ? [
                        {
                          id: "release-notes",
                          label: t("update.releaseNotes"),
                        },
                      ]
                    : undefined
                }
                onItemSelect={(id) => {
                  if (id === "release-notes" && updateCheck) {
                    window.open(updateCheck.release_url, "_blank", "noreferrer");
                  }
                }}
                onLogout={() => void useAuthStore.getState().logout()}
                logoutLabel={t("auth.signOut")}
              />
            )}
          </div>
        </header>
        <main id="main" ref={mainRef} className="min-h-0 flex-1 overflow-y-auto">
          <div
            className={
              fullBleed
                ? "flex min-h-0 flex-col px-4 py-4 lg:h-full lg:px-5"
                : "mx-auto max-w-7xl px-4 py-6"
            }
          >
            {/* Profile switch (§6) re-mounts the page subtree so every
                route refetches under the new X-Profile-Id scope (§15). */}
            <BetaBanner pathname={location.pathname} />
            <Outlet key={profileEpoch} />
          </div>
        </main>
      </div>

      {effectiveChatMode({ chatMode, chatModeChosen }, location.pathname) === "docked" && <ChatDock />}

      <FirstRunSetupGate />
      <ChatWidget />
      <CompareTray />
      <ToastHost />
      <DesktopNotifications />
    </div>
    </TooltipProvider>
  );
}
