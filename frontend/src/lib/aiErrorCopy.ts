/** Typed AI failure copy (plan 118.3).
 *
 * The chat stream never shows a raw provider/domain message for AI
 * failures: the backend sends a stable code (`ai_not_configured`,
 * `ai_budget`, `ai_rate_limit`, `ai_unavailable`, `ai_error`) and the SPA
 * renders translated copy. Unknown codes keep the server message, which is
 * already sanitized app-side.
 */
export type AiFailureKind =
  | "unconfigured"
  | "budget"
  | "rate_limit"
  | "unavailable"
  | "error";

const CODE_TO_KIND: Record<string, AiFailureKind> = {
  ai_not_configured: "unconfigured",
  ai_budget: "budget",
  ai_rate_limit: "rate_limit",
  ai_unavailable: "unavailable",
  ai_error: "error",
};

/** Map a stream error code onto its copy kind (null = not an AI failure). */
export function aiFailureKind(code: string | null | undefined): AiFailureKind | null {
  if (!code) return null;
  return CODE_TO_KIND[code] ?? null;
}

/** The i18n key carrying the typed copy for a failure kind. */
export function aiFailureCopyKey(kind: AiFailureKind): string {
  return `chat.aiError.${kind}`;
}
