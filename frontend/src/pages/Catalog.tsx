import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, LayoutGrid, Network, Sparkles } from "lucide-react";
import { useBootstrapStore } from "@/stores/bootstrapStore";

export function Catalog() {
  const { t } = useTranslation();
  const { bootstrap } = useBootstrapStore();
  const universitiesEnabled = !bootstrap || bootstrap.features.universities;

  const tabs = [
    { to: "/catalog", label: t("catalog.tree"), icon: LayoutGrid, end: true, testid: "catalog-tab-tree" },
    { to: "/catalog/graph", label: t("catalog.graph"), icon: Network, end: false, testid: "catalog-tab-graph" },
    { to: "/catalog/generate", label: t("catalog.generate"), icon: Sparkles, end: false, testid: "catalog-tab-generate" },
    ...(universitiesEnabled
      ? [{ to: "/catalog/universities", label: t("catalog.universities"), icon: Building2, end: false, testid: "catalog-tab-universities" }]
      : []),
  ];

  return (
    <div className="space-y-6" data-testid="catalog">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">{t("catalog.title")}</h1>
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
