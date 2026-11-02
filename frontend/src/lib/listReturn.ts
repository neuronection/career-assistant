export interface ListReturnState {
  listReturn: true;
}

export const LIST_RETURN_STATE: ListReturnState = { listReturn: true };

export function isListReturn(state: unknown): boolean {
  return (
    typeof state === "object" &&
    state !== null &&
    (state as ListReturnState).listReturn === true
  );
}

const remembered = new Map<string, string>();
const MAX_REMEMBERED = 16;

export function rememberListSearch(path: string, search: string): void {
  remembered.delete(path);
  remembered.set(path, search);
  if (remembered.size > MAX_REMEMBERED) {
    const oldest = remembered.keys().next().value;
    if (oldest !== undefined) remembered.delete(oldest);
  }
}

export function listReturnHref(path: string): string {
  const search = remembered.get(path);
  return search ? `${path}?${search}` : path;
}

export function resetListReturn(): void {
  remembered.clear();
}
