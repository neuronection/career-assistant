import i18next from "i18next";

function activeLocale(): string {
  return i18next.language || "en";
}

export function formatNumber(
  value: number,
  options: Intl.NumberFormatOptions = {},
): string {
  return new Intl.NumberFormat(activeLocale(), options).format(value);
}

export function formatDate(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
  },
): string {
  return new Intl.DateTimeFormat(activeLocale(), options).format(new Date(value));
}

export function formatDateTime(value: string | number | Date): string {
  return new Intl.DateTimeFormat(activeLocale(), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatCurrency(
  value: number,
  currency: string,
  maximumFractionDigits = 0,
): string {
  return new Intl.NumberFormat(activeLocale(), {
    style: "currency",
    currency,
    maximumFractionDigits,
  }).format(value);
}
