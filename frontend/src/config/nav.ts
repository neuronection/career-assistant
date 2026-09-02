import type { LucideIcon } from "lucide-react";
import {
  Briefcase,
  Building2,
  CalendarRange,
  ClipboardList,
  Globe,
  LayoutDashboard,
  Route,
  Search,
  Settings2,
  Sparkles,
  Trophy,
  UserRound,
} from "lucide-react";

export interface AppNavItem {
  to: string
  label: string
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
  { to: "/", label: "Dashboard", icon: LayoutDashboard, studentOnly: false },
  { to: "/catalog", label: "Catalog", icon: Briefcase, studentOnly: false, section: "Job hunt" },
  { to: "/generate", label: "Generate", icon: Sparkles, studentOnly: false },
  { to: "/rankings", label: "Rankings", icon: Trophy, studentOnly: false },
  { to: "/postings", label: "Live", icon: Globe, studentOnly: false },
  { to: "/explore", label: "Explore", icon: Search, studentOnly: false },
  { to: "/growth", label: "Growth", icon: Route, studentOnly: false },
  { to: "/assessment", label: "Assessment", icon: ClipboardList, studentOnly: false },
  { to: "/universities", label: "Universities", icon: Building2, studentOnly: true },
  { to: "/profile", label: "Profile", icon: UserRound, studentOnly: false, section: "Account" },
  { to: "/experience", label: "Experience", icon: CalendarRange, studentOnly: false },
  { to: "/settings/ai", label: "Settings", icon: Settings2, studentOnly: false, matchPrefix: "/settings" },
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
