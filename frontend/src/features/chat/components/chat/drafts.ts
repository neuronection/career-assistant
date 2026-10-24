const KEY = "ca-chat-drafts";

type Drafts = Record<string, string>;

function load(): Drafts {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}") as Drafts;
  } catch {
    return {};
  }
}

function save(drafts: Drafts): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(drafts));
  } catch {
    // Storage full or unavailable — drafts are best-effort.
  }
}

/** Unsent text per session. */
export function getDraft(sessionId: string | null): string {
  if (sessionId === null) {
    return "";
  }
  return load()[sessionId] ?? "";
}

export function writeDraft(sessionId: string | null, value: string): void {
  if (sessionId === null) {
    return;
  }
  const drafts = load();
  if (value === "") {
    delete drafts[sessionId];
  } else {
    drafts[sessionId] = value;
  }
  save(drafts);
}
