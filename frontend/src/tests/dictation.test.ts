import { describe, expect, it } from "vitest";
import axios, { type AxiosResponse } from "axios";

import { classifyDictationError } from "@/api/ai";

function axiosErrorWith(status: number): unknown {
  return new axios.AxiosError("request failed", "ERR", undefined, undefined, {
    status,
    data: { detail: "nope" },
  } as AxiosResponse);
}

describe("classifyDictationError", () => {
  it("maps unconfigured/not-found transports to the unassigned kind", () => {
    expect(classifyDictationError(axiosErrorWith(503)).kind).toBe("unassigned");
    expect(classifyDictationError(axiosErrorWith(404)).kind).toBe("unassigned");
    expect(classifyDictationError(axiosErrorWith(409)).kind).toBe("unassigned");
  });

  it("maps unsupported-provider responses to the unsupported kind", () => {
    const error = classifyDictationError(axiosErrorWith(422));
    expect(error.kind).toBe("unsupported");
  });

  it("maps anything else to failed with the transport detail", () => {
    const error = classifyDictationError(axiosErrorWith(500));
    expect(error.kind).toBe("failed");
    expect(error.detail).toBe("nope");
    expect(classifyDictationError(new Error("boom")).detail).toContain("boom");
  });
});
