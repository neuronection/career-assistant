import type { LucideIcon } from "lucide-react";
import {
  Bot,
  Briefcase,
  GraduationCap,
  MessageCircle,
  FileText,
  Globe,
  LayoutDashboard,
  Route,
  Settings2,
  Trophy,
  UserRound,
} from "lucide-react";

export interface AppNavItem {
  to: string
  labelKey: string
  icon: LucideIcon
  studentOnly: boolean
  /**
   * Page still under development: hidden from the sidebar unless dev
   * mode is unlocked (see `stores/devModeStore`). Deep links keep
   * working and `resolveActiveId` still resolves these routes.
   */
  inDev?: boolean
  /** Divider label rendered above this item (first occurrence only). */
  section?: string
  /** Prefix used for active matching when it differs from `to`. */
  matchPrefix?: string
}

/**
 * Primary sidebar registry — single source for the app shell. Sections
 * group the list visually; every destination stays one click away.
 * About lives in the sidebar footer promo block.
 */
export const NAV: AppNavItem[] = [
  { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard, studentOnly: false },
  { to: "/chat", labelKey: "nav.chat", icon: MessageCircle, studentOnly: false, section: "nav.sectionJobHunt" },
  { to: "/catalog", labelKey: "nav.catalog", icon: Briefcase, studentOnly: false },
  { to: "/rankings", labelKey: "nav.rankings", icon: Trophy, studentOnly: false },
  { to: "/postings", labelKey: "nav.postings", icon: Globe, studentOnly: false, inDev: true },
  { to: "/autopilot", labelKey: "nav.autopilot", icon: Bot, studentOnly: false, inDev: true },
  { to: "/interviews", labelKey: "nav.interviews", icon: GraduationCap, studentOnly: false, inDev: true },
  { to: "/growth", labelKey: "nav.growth", icon: Route, studentOnly: false, inDev: true, section: "nav.sectionPrepare" },
  { to: "/cv", labelKey: "nav.cvStudio", icon: FileText, studentOnly: false },
  { to: "/profile", labelKey: "nav.profile", icon: UserRound, studentOnly: false, section: "nav.sectionAccount" },
  { to: "/settings/ai", labelKey: "nav.settings", icon: Settings2, studentOnly: false, matchPrefix: "/settings" },
];


/**
 * Map a registry entry onto the library SidebarNav item shape. The
 * Profile entry carries the pending HITL-proposal badge (plan 77) when
 * the count is positive.
 */
export function toNavItem(
  item: AppNavItem,
  t: (key: string) => string,
  pendingProposals = 0,
): { id: string; label: string; icon: LucideIcon; section?: string; badge?: number } {
  return {
    id: item.to,
    label: t(item.labelKey),
    icon: item.icon,
    ...(item.section ? { section: t(item.section) } : {}),
    ...(item.to === "/profile" && pendingProposals > 0
      ? { badge: pendingProposals }
      : {}),
  };
}

/**
 * Resolve the active nav id for a pathname: the root matches only
 * exactly, everything else matches by prefix (using `matchPrefix` when
 * set) with the longest prefix winning.
 */
export function resolveActiveId(
  pathname: string,
  nav: AppNavItem[] = NAV,
): string | null {
  const matchPath = (item: AppNavItem) => item.matchPrefix ?? item.to;
  const exact = nav.find((item) => item.to === "/" && pathname === "/");
  if (exact) return exact.to;
  const prefix = nav
    .filter((item) => item.to !== "/" && pathname.startsWith(matchPath(item)))
    .sort((a, b) => matchPath(b).length - matchPath(a).length)[0];
  return prefix?.to ?? null;
}
