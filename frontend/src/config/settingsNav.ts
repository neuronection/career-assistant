import type { LucideIcon } from "lucide-react";
import {
  Bell,
  CalendarClock,
  CircleUser,
  Cpu,
  ListTree,
  ScrollText,
  Users,
  Wrench,
} from "lucide-react";

export interface SettingsNavItem {
  to: string;
  icon: LucideIcon;
  label: string;
  description?: string;
  /** When true, only admins see the entry. */
  adminOnly?: boolean;
}

/** Settings sections — add future general settings here. */
export const settingsNav: SettingsNavItem[] = [
  {
    to: "/settings/account",
    icon: CircleUser,
    label: "Account",
    description: "Sessions, password and account deletion",
  },
  {
    to: "/settings/ai",
    icon: Cpu,
    label: "AI Configuration",
    description: "Providers, models and task assignments",
  },
  {
    to: "/settings/tools",
    icon: Wrench,
    label: "Tools",
    description: "Web search and external connectors",
    adminOnly: true,
  },
  {
    to: "/settings/automations",
    icon: CalendarClock,
    label: "Automations",
    description: "Scheduled searches, digests and system rhythm",
  },
  {
    to: "/settings/notifications",
    icon: Bell,
    label: "Notifications",
    description: "Kinds, channels and quiet hours",
  },
  {
    to: "/settings/taxonomy",
    icon: ListTree,
    label: "Taxonomy",
    description: "Interest & skill vocabularies",
    adminOnly: true,
  },
  {
    to: "/settings/users",
    icon: Users,
    label: "Users",
    description: "Roles, access and forced sign-out",
    adminOnly: true,
  },
  {
    to: "/settings/audit",
    icon: ScrollText,
    label: "AI Audit",
    description: "Every AI call, with tokens and latency",
    adminOnly: true,
  },
];
