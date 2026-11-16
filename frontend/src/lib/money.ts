/** Locale-aware money formatting for surfaces that show amounts in a currency.
 *
 * Returns an em dash for a missing or non-finite value so a partial payload
 * never prints "undefined EUR"; amounts are not converted between currencies.
 */

export function formatMoney(
  value: number | null | undefined,
  currency: string,
  locale?: string
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(locale || undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toLocaleString(locale || undefined)} ${currency}`;
  }
}
