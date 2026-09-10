import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bookmark, Search } from "lucide-react";

export function Postings() {
  const { t } = useTranslation();

  const tabs = [
    { to: "/postings", label: t("postings.tabFeed"), icon: Bookmark, end: true, testid: "postings-tab-feed" },
    { to: "/postings/search", label: t("postings.tabSearch"), icon: Search, end: false, testid: "postings-tab-search" },
  ];

  return (
    <div className="space-y-6" data-testid="postings-page">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">{t("postings.title")}</h1>
        <div className="flex rounded-lg border border-slate-200 overflow-hidden">
          {tabs.map(({ to, label, icon: Icon, end, testid }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={testid}
              className={({ isActive }) =>
                `text-sm px-3 py-2 flex items-center gap-1 ${isActive ? "bg-primary-600 text-white" : "bg-white"}`
              }
            >
              <Icon className="w-4 h-4" /> {label}
            </NavLink>
          ))}
        </div>
      </div>

      <Outlet />
    </div>
  );
}
