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
  { to: "/postings", labelKey: "nav.postings", icon: Globe, studentOnly: false },
  { to: "/autopilot", labelKey: "nav.autopilot", icon: Bot, studentOnly: false },
  { to: "/interviews", labelKey: "nav.interviews", icon: GraduationCap, studentOnly: false },
  { to: "/growth", labelKey: "nav.growth", icon: Route, studentOnly: false },
  { to: "/cv", labelKey: "nav.cvStudio", icon: FileText, studentOnly: false },
  { to: "/profile", labelKey: "nav.profile", icon: UserRound, studentOnly: false, section: "nav.sectionAccount" },
  { to: "/settings/ai", labelKey: "nav.settings", icon: Settings2, studentOnly: false, matchPrefix: "/settings" },
];

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
