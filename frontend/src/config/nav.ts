import type { LucideIcon } from "lucide-react";
import {
  Building2,
  ChartNoAxesCombined,
  Puzzle,
  Radar,

  Bot,
  Briefcase,
  GraduationCap,
  MessageCircle,
  Milestone,
  FileText,
  Globe,
  KanbanSquare,
  LayoutDashboard,
  Route,
  Settings2,
  Trophy,
  UserRound,
} from "lucide-react";

import { featureFor, isVisible } from "@/config/features";

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
  { to: "/chat", labelKey: "nav.chat", icon: MessageCircle, studentOnly: false },
  { to: "/catalog", labelKey: "nav.catalog", icon: Briefcase, studentOnly: false, section: "nav.sectionJobHunt" },
  { to: "/rankings", labelKey: "nav.rankings", icon: Trophy, studentOnly: false },
  { to: "/postings", labelKey: "nav.postings", icon: Globe, studentOnly: false },
  { to: "/companies", labelKey: "nav.companies", icon: Building2, studentOnly: false },
  {
    to: "/postings/stats",
    labelKey: "nav.marketStats",
    icon: ChartNoAxesCombined,
    studentOnly: false,
  },
  { to: "/applications", labelKey: "nav.applications", icon: KanbanSquare, studentOnly: false },
  { to: "/radar", labelKey: "nav.radar", icon: Radar, studentOnly: false },
  { to: "/autopilot", labelKey: "nav.autopilot", icon: Bot, studentOnly: false },
  { to: "/interviews", labelKey: "nav.interviews", icon: GraduationCap, studentOnly: false },
  { to: "/growth", labelKey: "nav.growth", icon: Route, studentOnly: false, section: "nav.sectionPrepare" },
  { to: "/paths", labelKey: "nav.paths", icon: Milestone, studentOnly: false },
  { to: "/cv", labelKey: "nav.cvStudio", icon: FileText, studentOnly: false },
  { to: "/profile", labelKey: "nav.profile", icon: UserRound, studentOnly: false, section: "nav.sectionAccount" },
  { to: "/settings/ai", labelKey: "nav.settings", icon: Settings2, studentOnly: false, matchPrefix: "/settings" },
];


/**
 * The nav entries the feature registry currently allows. One place decides
 * page visibility — `hidden` surfaces stay deep-linkable but leave the
 * sidebar (and the demo tour, see `scripts/ui-capture/scenes.mjs`).
 */
export function visibleNav(): AppNavItem[] {
  return NAV.filter((item) => isVisible(item.to));
}

/**
 * Map a registry entry onto the library SidebarNav item shape. The
 * Profile entry carries the pending HITL-proposal badge (plan 77) when
 * the count is positive.
 */
export function toNavItem(
  item: AppNavItem,
  t: (key: string) => string,
  pendingProposals = 0,
): { id: string; label: string; icon: LucideIcon; section?: string; badge?: string | number } {
  // The beta badge rides the same pill slot as the profile's pending
  // count — a route can't be both, and the proposals count wins.
  const proposalsBadge =
    item.to === "/profile" && pendingProposals > 0 ? pendingProposals : undefined;
  const feature = featureFor(item.to);
  const betaBadge =
    feature?.state === "beta" && proposalsBadge === undefined
      ? t("featureState.betaChip")
      : undefined;
  return {
    id: item.to,
    label: t(item.labelKey),
    icon: item.icon,
    ...(item.section ? { section: t(item.section) } : {}),
    ...(proposalsBadge !== undefined ? { badge: proposalsBadge } : {}),
    ...(betaBadge !== undefined ? { badge: betaBadge } : {}),
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

/**
 * Dynamic nav top-up (plan 32 Phase 4): installed + ENABLED mini-app
 * extensions contribute one nav row per page surface — the kill switch
 * hides the route because the registry only lists enabled installs.
 */
export interface ExtensionNavItem {
  extensionId: string;
  title: string;
}

export function extensionNavItems(
  cards: { extensionId: string; title: string; routes: string | null }[],
  t: (key: string) => string,
): Extract<ReturnType<typeof toNavItem>, { id: string }>[] {
  return cards
    .filter((card) => card.routes)
    .map((card) => ({
      id: card.routes as string,
      label: card.title || card.extensionId,
      icon: Puzzle,
      section: t("nav.sectionExtensions"),
    }));
}
