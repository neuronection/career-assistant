import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Clock, Star, X } from "lucide-react";
import { deleteSearch, fetchSearches } from "@/api/engagement";
import type { SearchRecord, SearchScope } from "@/types";

export function RecentSearches({
  scope,
  onApply,
  refreshKey = 0,
}: {
  scope: SearchScope;
  onApply: (record: SearchRecord) => void;
  refreshKey?: number;
}) {
  const { t } = useTranslation();
  const [records, setRecords] = useState<SearchRecord[]>([]);

  useEffect(() => {
    void fetchSearches({ scope })
      .then(setRecords)
      .catch(() => setRecords([]));
  }, [scope, refreshKey]);

  if (records.length === 0) return null;

  return (
    <div className="space-y-1" data-testid={`recent-searches-${scope}`}>
      <p className="text-xs font-medium text-slate-400 uppercase flex items-center gap-1">
        <Clock className="w-3 h-3" /> {t("shared.recentSearches")}
      </p>
      <ul className="space-y-1">
        {records.slice(0, 6).map((record) => (
          <li key={record.id} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onApply(record)}
              className="flex-1 text-left text-sm text-slate-600 hover:text-primary-700 truncate"
              data-testid="recent-search-item"
            >
              {record.query ? record.query : <em className="text-slate-400">{t("shared.filtersOnly")}</em>}
              <span className="text-slate-300"> · {t("shared.resultCount", { count: record.result_count })}</span>
              {record.saved && (
                <Star className="w-3 h-3 inline text-amber-400 fill-amber-400 ml-1" />
              )}
            </button>
            <button
              type="button"
              aria-label={t("shared.deleteSearch")}
              onClick={(e) => {
                e.stopPropagation();
                setRecords((prev) => prev.filter((r) => r.id !== record.id));
                void deleteSearch(record.id);
              }}
              className="p-1 text-slate-300 hover:text-rose-500"
            >
              <X className="w-3 h-3" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
