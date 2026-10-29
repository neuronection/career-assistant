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
  /** Rail group label (library `SettingsNavItem.section`): the tab list
   * renders as contiguous runs — Personal, AI & tools, Automation,
   * Administration. Derived from the settings-map contract groups
   * (app+user → personal, ai/tools → aiTools, automations, app+admin →
   * administration); settingsMap.test.ts pins the alignment. */
  sectionKey: "personal" | "aiTools" | "automation" | "administration";
}

/** Settings sections — add future general settings here. */
export const settingsNav: SettingsNavItem[] = [
  {
    to: "/settings/account",
    icon: CircleUser,
    labelKey: "settingsNav.account.label",
    descriptionKey: "settingsNav.account.description",
    sectionKey: "personal",
  },
  {
    to: "/settings/radar",
    icon: Radar,
    labelKey: "settingsNav.radar.label",
    descriptionKey: "settingsNav.radar.description",
    sectionKey: "personal",
  },
  {
    to: "/settings/notifications",
    icon: Bell,
    labelKey: "settingsNav.notifications.label",
    descriptionKey: "settingsNav.notifications.description",
    sectionKey: "personal",
  },
  {
    to: "/settings/ai",
    icon: Cpu,
    labelKey: "settingsNav.ai.label",
    descriptionKey: "settingsNav.ai.description",
    sectionKey: "aiTools",
  },
  {
    to: "/settings/tools",
    icon: Wrench,
    labelKey: "settingsNav.tools.label",
    descriptionKey: "settingsNav.tools.description",
    adminOnly: true,
    sectionKey: "aiTools",
  },
  {
    to: "/settings/automations",
    icon: CalendarClock,
    labelKey: "settingsNav.automations.label",
    descriptionKey: "settingsNav.automations.description",
    sectionKey: "automation",
  },
  {
    to: "/settings/taxonomy",
    icon: ListTree,
    labelKey: "settingsNav.taxonomy.label",
    descriptionKey: "settingsNav.taxonomy.description",
    adminOnly: true,
    sectionKey: "administration",
  },
  {
    to: "/settings/companies",
    icon: Building2,
    labelKey: "settingsNav.companies.label",
    descriptionKey: "settingsNav.companies.description",
    adminOnly: true,
    sectionKey: "administration",
  },
  {
    to: "/settings/users",
    icon: Users,
    labelKey: "settingsNav.users.label",
    descriptionKey: "settingsNav.users.description",
    adminOnly: true,
    sectionKey: "administration",
  },
  {
    to: "/settings/audit",
    icon: ScrollText,
    labelKey: "settingsNav.audit.label",
    descriptionKey: "settingsNav.audit.description",
    adminOnly: true,
    sectionKey: "administration",
  },
];
