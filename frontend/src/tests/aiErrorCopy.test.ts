import { describe, expect, it } from "vitest";

import { aiFailureCopyKey, aiFailureKind } from "@/lib/aiErrorCopy";

describe("aiFailureKind", () => {
  it("maps every backend AI failure code to typed copy", () => {
    expect(aiFailureKind("ai_not_configured")).toBe("unconfigured");
    expect(aiFailureKind("ai_budget")).toBe("budget");
    expect(aiFailureKind("ai_rate_limit")).toBe("rate_limit");
    expect(aiFailureKind("ai_unavailable")).toBe("unavailable");
    expect(aiFailureKind("ai_error")).toBe("error");
  });

  it("leaves non-AI failures on their (sanitized) server message", () => {
    expect(aiFailureKind("network_error")).toBeNull();
    expect(aiFailureKind("")).toBeNull();
    expect(aiFailureKind(null)).toBeNull();
    expect(aiFailureKind(undefined)).toBeNull();
  });

  it("keys the copy under the chat section", () => {
    expect(aiFailureCopyKey("budget")).toBe("chat.aiError.budget");
  });
});
