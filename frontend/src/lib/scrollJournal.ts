const journal = new Map<string, number>();
const MAX_ENTRIES = 200;

export function recordScroll(key: string, top: number): void {
  journal.delete(key);
  journal.set(key, top);
  if (journal.size > MAX_ENTRIES) {
    const oldest = journal.keys().next().value;
    if (oldest !== undefined) journal.delete(oldest);
  }
}

export function journaledScroll(key: string): number {
  return journal.get(key) ?? 0;
}

export function resetScrollJournal(): void {
  journal.clear();
}
