import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useCompareStore } from "@/stores/compareStore";

export function CompareTray() {
  const { items, remove, clear } = useCompareStore();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  if (items.length === 0 || location.pathname === "/compare") return null;

  return (
    <div
      className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-lg"
      data-testid="compare-tray"
    >
      {items.map((item) => (
        <span
          key={item.id}
          className="flex items-center gap-1 rounded-full bg-primary-50 py-1 pl-2.5 pr-1.5 text-xs text-primary-700"
          data-testid={`compare-chip-${item.id}`}
        >
          <span className="max-w-36 truncate">{item.title}</span>
          <button
            type="button"
            onClick={() => remove(item.id)}
            aria-label={t("tray.removeAria", { title: item.title })}
            title={t("tray.remove")}
            className="rounded-full p-0.5 hover:bg-primary-100"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={clear}
        className="px-1 text-xs text-slate-400 hover:text-slate-600"
        data-testid="compare-clear"
      >
        {t("tray.clear")}
      </button>
      <button
        type="button"
        onClick={() => navigate(`/compare?jobs=${items.map((i) => i.id).join(",")}`)}
        disabled={items.length < 2}
        className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs text-white hover:bg-primary-700 disabled:opacity-50"
        data-testid="compare-open"
      >
        {t("tray.open", { count: items.length })}
      </button>
    </div>
  );
}
