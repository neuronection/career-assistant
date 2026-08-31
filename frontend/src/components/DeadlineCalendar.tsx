import { useMemo, useState } from "react";
import {
  addDays,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface Deadline {
  date: string;
  label: string;
}

interface DeadlineCalendarProps {
  deadlines: Deadline[];
  initialDate?: string;
  className?: string;
}

const WEEKDAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

/**
 * Compact month calendar that highlights days carrying deadlines.
 * Click a highlighted day to see its deadline labels.
 */
export function DeadlineCalendar({ deadlines, initialDate, className = "" }: DeadlineCalendarProps) {
  const parsedInitial = initialDate ? parseISO(initialDate) : new Date();
  const [month, setMonth] = useState(() => startOfMonth(isValidDate(parsedInitial) ? parsedInitial : new Date()));
  const [selected, setSelected] = useState<string | null>(null);

  const byDay = useMemo(() => {
    const map = new Map<string, Deadline[]>();
    for (const d of deadlines) {
      const list = map.get(d.date) ?? [];
      list.push(d);
      map.set(d.date, list);
    }
    return map;
  }, [deadlines]);

  const cells = useMemo(() => {
    const monthStart = startOfMonth(month);
    const monthEnd = endOfMonth(monthStart);
    const start = startOfWeek(monthStart, { weekStartsOn: 1 });
    const end = endOfWeek(monthEnd, { weekStartsOn: 1 });
    const out: Date[] = [];
    let day = start;
    while (day <= end) {
      out.push(day);
      day = addDays(day, 1);
    }
    return out;
  }, [month]);

  const selectedDeadlines = selected ? (byDay.get(selected) ?? []) : [];

  return (
    <div className={`bg-white border border-slate-200 rounded-xl p-4 ${className}`} data-testid="deadline-calendar">
      <div className="flex items-center justify-between mb-3">
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => setMonth(subMonths(month, 1))}
          className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-sm font-semibold text-slate-700">{format(month, "MMMM yyyy")}</span>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}
          className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAY_LABELS.map((d, i) => (
          <div key={i} className="text-center text-[10px] font-medium text-slate-400 py-1">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day) => {
          const iso = format(day, "yyyy-MM-dd");
          const hasDeadline = byDay.has(iso);
          const inMonth = isSameMonth(day, month);
          const isToday = isSameDay(day, new Date());
          return (
            <button
              key={iso}
              type="button"
              onClick={() => setSelected(hasDeadline ? iso : null)}
              className={`relative h-8 w-full rounded-lg text-xs flex items-center justify-center transition-colors
                ${inMonth ? "text-slate-700" : "text-slate-300"}
                ${hasDeadline ? "bg-amber-100 text-amber-800 font-semibold hover:bg-amber-200" : "hover:bg-slate-100"}
                ${isToday && !hasDeadline ? "ring-1 ring-primary-400" : ""}
                ${selected === iso ? "outline outline-2 outline-amber-500" : ""}`}
              title={hasDeadline ? byDay.get(iso)!.map((d) => d.label).join(", ") : undefined}
            >
              {format(day, "d")}
              {hasDeadline && (
                <span className="absolute bottom-0.5 w-1 h-1 rounded-full bg-amber-500" aria-hidden="true" />
              )}
            </button>
          );
        })}
      </div>

      {selectedDeadlines.length > 0 && (
        <ul className="mt-3 pt-3 border-t border-slate-100 space-y-1">
          {selectedDeadlines.map((d, i) => (
            <li key={i} className="text-xs text-slate-600 flex items-start gap-1.5">
              <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" aria-hidden="true" />
              {d.label}
            </li>
          ))}
        </ul>
      )}
      {deadlines.length === 0 && (
        <p className="text-xs text-slate-400 text-center mt-2">No deadlines recorded yet.</p>
      )}
    </div>
  );
}

function isValidDate(d: Date): boolean {
  return !Number.isNaN(d.getTime());
}
