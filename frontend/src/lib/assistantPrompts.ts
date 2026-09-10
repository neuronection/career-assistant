const STORAGE_KEY = "ca:cv-assistant:custom-prompts";
const MAX_PROMPTS = 20;

/** Predefined CV copilot prompts (kind-aware); shown as the chat's
 *  empty-state suggestions whenever the active session is CV-bound. */
export const CV_PROMPTS: Record<"resume" | "cover_letter", string[]> = {
  resume: [
    "Review this CV and fix any layout or overflow issues",
    "Rewrite my summary to be sharper and more specific",
    "Switch to a modern template with a sidebar",
    "Fit everything on one page",
    "Hide interests and shorten experience descriptions",
    "Which sections are dragging my ATS score down?",
  ],
  cover_letter: [
    "Tighten the letter to under 300 words",
    "Make the opening paragraph more specific to the role",
    "Which profile evidence is missing from the letter?",
  ],
};

export function loadCustomPrompts(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((p): p is string => typeof p === "string") : [];
  } catch {
    return [];
  }
}

function persist(prompts: string[]): string[] {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prompts));
  return prompts;
}

export function saveCustomPrompt(prompt: string): string[] {
  const trimmed = prompt.trim().slice(0, 300);
  if (!trimmed) return loadCustomPrompts();
  const next = [trimmed, ...loadCustomPrompts().filter((p) => p !== trimmed)];
  return persist(next.slice(0, MAX_PROMPTS));
}

export function removeCustomPrompt(prompt: string): string[] {
  return persist(loadCustomPrompts().filter((p) => p !== prompt));
}

export type CvPromptChip = {
  prompt: string;
  custom: boolean;
};

export function cvPromptChips(kind: "resume" | "cover_letter"): CvPromptChip[] {
  const custom = loadCustomPrompts();
  return [...CV_PROMPTS[kind].map((prompt) => ({ prompt, custom: false })), ...custom.map((prompt) => ({ prompt, custom: true }))];
}

export const GENERIC_SUGGESTIONS = [
  "Find entry-level roles that fit my profile",
  "Compare two job offers side by side",
  "Which skills should I build next?",
];
