/**
 * Collapse runs of newlines to a single break — the display-side twin
 * of the backend `normalize_rich_text` cap (descriptions honor hard
 * line breaks, at most one). Also heals prose stored before the cap.
 */
export function normalizeProse(text: string): string {
  return text.replace(/\s*\n\s*/g, "\n").trim();
}
