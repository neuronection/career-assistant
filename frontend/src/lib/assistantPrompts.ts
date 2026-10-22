/** CV copilot prompt keys (kind-aware) for the chat empty state. */
export const CV_PROMPT_KEYS: Record<"resume" | "cover_letter", string[]> = {
  resume: [
    "chat.prompts.cvLayout",
    "chat.prompts.cvSummary",
    "chat.prompts.cvTemplate",
    "chat.prompts.cvOnePage",
    "chat.prompts.cvHideInterests",
    "chat.prompts.cvAts",
  ],
  cover_letter: [
    "chat.prompts.letterShorten",
    "chat.prompts.letterOpening",
    "chat.prompts.letterEvidence",
  ],
};

export const GENERIC_SUGGESTION_KEYS = [
  "chat.prompts.entryLevel",
  "chat.prompts.compareOffers",
  "chat.prompts.nextSkills",
];
