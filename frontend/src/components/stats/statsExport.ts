/** Client-side CSV export for the market-stats payloads (plan 170 slice 4).
 *
 * Generated cells are neutralized against spreadsheet formula injection —
 * a value whose first character is ``=``, ``+``, ``-`` or ``@`` is prefixed
 * with a single quote so it cannot execute as a formula (the ca-dev
 * `_csv_safe` rule). Quoting follows CSV-2000: wrap cells holding
 * separators, quotes or newlines and double embedded quotes.
 */

export type CsvValue = string | number | boolean | null | undefined;
export type CsvRows = CsvValue[][];

const FORMULA_LEADERS = new Set(["=", "+", "-", "@"]);

export function csvSafeCell(value: CsvValue): string {
  const text = value === null || value === undefined ? "" : String(value);
  if (text.length > 0 && FORMULA_LEADERS.has(text[0])) {
    return `'${text}`;
  }
  return text;
}

export function csvCell(value: CsvValue): string {
  const text = csvSafeCell(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function toCsv(rows: CsvRows): string {
  return `${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

export function downloadStatsCsv(name: string, rows: CsvRows): void {
  const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `market-stats-${name}-${new Date().toISOString().slice(0, 10)}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}
