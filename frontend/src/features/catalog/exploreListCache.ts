import type { ExploreFacets, PostingOut } from "@/types/wire";

export interface ExploreListSnapshot {
  items: PostingOut[];
  total: number;
  facets: ExploreFacets;
  nextCursor: string | null;
}

const snapshots = new Map<string, ExploreListSnapshot>();
const MAX_SNAPSHOTS = 8;

function put(key: string, snapshot: ExploreListSnapshot): void {
  snapshots.delete(key);
  snapshots.set(key, snapshot);
  if (snapshots.size > MAX_SNAPSHOTS) {
    const oldest = snapshots.keys().next().value;
    if (oldest !== undefined) snapshots.delete(oldest);
  }
}

export function peekExploreList(key: string): ExploreListSnapshot | null {
  return snapshots.get(key) ?? null;
}

export function rememberExploreList(
  key: string,
  snapshot: ExploreListSnapshot
): void {
  put(key, snapshot);
}

export function dropExploreListPosting(postingId: string): void {
  for (const snapshot of snapshots.values()) {
    const next = snapshot.items.filter((item) => item.id !== postingId);
    if (next.length === snapshot.items.length) continue;
    snapshot.items = next;
    snapshot.total = Math.max(0, snapshot.total - 1);
  }
}

export function patchExploreListPosting(
  postingId: string,
  patch: Partial<Pick<PostingOut, "seen" | "saved">>
): void {
  for (const snapshot of snapshots.values()) {
    const item = snapshot.items.find((entry) => entry.id === postingId);
    if (item) Object.assign(item, patch);
  }
}

export function resetExploreListCache(): void {
  snapshots.clear();
}
