import type { LucideIcon } from "lucide-react";
import {
  Bell,
  Building2,
  CalendarClock,
  CircleUser,
  Cpu,
  ListTree,
  Radar,
  ScrollText,
  Users,
  Wrench,
} from "lucide-react";

export interface SettingsNavItem {
  to: string;
  icon: LucideIcon;
  labelKey: string;
  descriptionKey?: string;
  /** When true, only admins see the entry. */
  adminOnly?: boolean;
}

/** Settings sections — add future general settings here. */
export const settingsNav: SettingsNavItem[] = [
  {
    to: "/settings/account",
    icon: CircleUser,
    labelKey: "settingsNav.account.label",
    descriptionKey: "settingsNav.account.description",
  },
  {
    to: "/settings/radar",
    icon: Radar,
    labelKey: "settingsNav.radar.label",
    descriptionKey: "settingsNav.radar.description",
  },
  {
    to: "/settings/ai",
    icon: Cpu,
    labelKey: "settingsNav.ai.label",
    descriptionKey: "settingsNav.ai.description",
  },
  {
    to: "/settings/tools",
    icon: Wrench,
    labelKey: "settingsNav.tools.label",
    descriptionKey: "settingsNav.tools.description",
    adminOnly: true,
  },
  {
    to: "/settings/automations",
    icon: CalendarClock,
    labelKey: "settingsNav.automations.label",
    descriptionKey: "settingsNav.automations.description",
  },
  {
    to: "/settings/notifications",
    icon: Bell,
    labelKey: "settingsNav.notifications.label",
    descriptionKey: "settingsNav.notifications.description",
  },
  {
    to: "/settings/taxonomy",
    icon: ListTree,
    labelKey: "settingsNav.taxonomy.label",
    descriptionKey: "settingsNav.taxonomy.description",
    adminOnly: true,
  },
  {
    to: "/settings/companies",
    icon: Building2,
    labelKey: "settingsNav.companies.label",
    descriptionKey: "settingsNav.companies.description",
    adminOnly: true,
  },
  {
    to: "/settings/users",
    icon: Users,
    labelKey: "settingsNav.users.label",
    descriptionKey: "settingsNav.users.description",
    adminOnly: true,
  },
  {
    to: "/settings/audit",
    icon: ScrollText,
    labelKey: "settingsNav.audit.label",
    descriptionKey: "settingsNav.audit.description",
    adminOnly: true,
  },
];
