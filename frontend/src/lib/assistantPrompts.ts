/** Predefined CV copilot prompts (kind-aware); shown as the chat's
 *  empty-state suggestions while a CV is open in Studio. */
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

export function cvPromptChips(kind: "resume" | "cover_letter"): string[] {
  return CV_PROMPTS[kind];
}

export const GENERIC_SUGGESTIONS = [
  "Find entry-level roles that fit my profile",
  "Compare two job offers side by side",
  "Which skills should I build next?",
];
