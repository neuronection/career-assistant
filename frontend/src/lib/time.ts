/**
 * Relative + absolute time formatting for posting surfaces.
 * `formatRelativeTime` is pure and takes an injectable `now` so tests are
 * deterministic; it returns an i18n key + count, never formatted text
 * (the caller runs it through `t(key, { count })`).
 */

export interface RelativeTime {
  key: string;
  count: number;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

const KEYS = {
  justNow: "common.time.justNow",
  inAMoment: "common.time.inAMoment",
  minutesAgo: "common.time.minutesAgo",
  hoursAgo: "common.time.hoursAgo",
  daysAgo: "common.time.daysAgo",
  monthsAgo: "common.time.monthsAgo",
  yearsAgo: "common.time.yearsAgo",
  inMinutes: "common.time.inMinutes",
  inHours: "common.time.inHours",
  inDays: "common.time.inDays",
  inMonths: "common.time.inMonths",
  inYears: "common.time.inYears",
} as const;

export function formatRelativeTime(
  iso: string | null | undefined,
  now: Date = new Date()
): RelativeTime | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const seconds = Math.round((now.getTime() - then) / 1000);
  const magnitude = Math.abs(seconds);
  const future = seconds < 0;
  if (magnitude < 45) {
    return { key: future ? KEYS.inAMoment : KEYS.justNow, count: 0 };
  }
  if (magnitude < HOUR) {
    return {
      key: future ? KEYS.inMinutes : KEYS.minutesAgo,
      count: Math.max(1, Math.round(magnitude / MINUTE)),
    };
  }
  if (magnitude < DAY) {
    return {
      key: future ? KEYS.inHours : KEYS.hoursAgo,
      count: Math.round(magnitude / HOUR),
    };
  }
  if (magnitude < MONTH) {
    return {
      key: future ? KEYS.inDays : KEYS.daysAgo,
      count: Math.round(magnitude / DAY),
    };
  }
  if (magnitude < YEAR) {
    return {
      key: future ? KEYS.inMonths : KEYS.monthsAgo,
      count: Math.round(magnitude / MONTH),
    };
  }
  return {
    key: future ? KEYS.inYears : KEYS.yearsAgo,
    count: Math.round(magnitude / YEAR),
  };
}

export function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}
