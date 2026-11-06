const STORAGE_KEY = "ca:applications:seen";

type SeenMap = Record<string, string>;

function load(): SeenMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string"
      )
    );
  } catch {
    return {};
  }
}

export function seenAt(applicationId: string): string | null {
  return load()[applicationId] ?? null;
}

export function markSeen(applicationId: string, stamp: string): void {
  const map = load();
  if (map[applicationId] && map[applicationId] >= stamp) return;
  map[applicationId] = stamp;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    undefined;
  }
}

export function isUnread(applicationId: string, updatedAt: string): boolean {
  const seen = seenAt(applicationId);
  return seen === null || updatedAt > seen;
}
