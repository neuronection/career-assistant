import type { LucideIcon } from "lucide-react";
import {
  Briefcase,
  Building2,
  CalendarRange,
  ClipboardList,
  Globe,
  Info,
  LayoutDashboard,
  Route,
  Search,
  Settings2,
  Sparkles,
  Trophy,
  UserRound,
} from "lucide-react";

export interface AppNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  studentOnly: boolean;
}

/** Primary top-nav registry — single source for the app shell. */
export const NAV: AppNavItem[] = [
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
