/**
 * Guard for rendering user-supplied links: returns the url only when it
 * is an absolute http(s) URL, otherwise null — blocks `javascript:`,
 * `data:`, relative and malformed values. Consumers must still add
 * `rel="noopener noreferrer"` when opening in a new tab.
 */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}
