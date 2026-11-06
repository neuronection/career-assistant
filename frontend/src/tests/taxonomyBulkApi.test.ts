import { afterEach, describe, expect, it, vi } from "vitest";
import { apiDetail } from "@/api/client";
import { bulkInterestAction, bulkSkillAction } from "@/api/taxonomy";

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return { ...actual, api: { ...actual.api, post: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});

const { api } = await import("@/api/client");
const postMock = vi.mocked(api.post);
const putMock = vi.mocked(api.put);
const deleteMock = vi.mocked(api.delete);

afterEach(() => {
  postMock.mockReset();
  putMock.mockReset();
  deleteMock.mockReset();
});

describe("bulkSkillAction chunking", () => {
  it("splits selections over the 200-id server cap into sequential calls and merges the results", async () => {
    const ids = Array.from({ length: 220 }, (_, i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`);
    postMock
      .mockResolvedValueOnce({ data: { affected: ids.slice(0, 200), failed: [] } })
      .mockResolvedValueOnce({ data: { affected: [], failed: [{ id: ids[219], key: "k", reason: "Skill not found" }] } });

    const result = await bulkSkillAction(ids, "promote");

    expect(postMock).toHaveBeenCalledTimes(2);
    expect((postMock.mock.calls[0][1] as { ids: string[] }).ids).toHaveLength(200);
    expect((postMock.mock.calls[1][1] as { ids: string[] }).ids).toHaveLength(20);
    expect(result.affected).toHaveLength(200);
    expect(result.failed).toEqual([{ id: ids[219], key: "k", reason: "Skill not found" }]);
  });

  it("sends a single request under the cap and passes the merge target through", async () => {
    postMock.mockResolvedValueOnce({ data: { affected: ["a"], failed: [] } });

    await bulkSkillAction(["a", "b"], "merge", "target-1");

    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock.mock.calls[0]).toEqual([
      "/admin/skills/bulk",
      { ids: ["a", "b"], action: "merge", target_id: "target-1" },
    ]);
  });
});

describe("bulkInterestAction", () => {
  it("flips the deprecated flag per id and keeps per-item failures", async () => {
    putMock
      .mockResolvedValueOnce({ data: {} })
      .mockRejectedValueOnce(new Error("referenced"));

    const result = await bulkInterestAction(["i-1", "i-2"], "deprecate");

    expect(putMock).toHaveBeenNthCalledWith(1, "/taxonomy/interests/i-1", {
      deprecated: true,
    });
    expect(result.affected).toEqual(["i-1"]);
    expect(result.failed.map((failure) => failure.id)).toEqual(["i-2"]);
  });

  it("restores and deletes through the per-id endpoints", async () => {
    putMock.mockResolvedValueOnce({ data: {} });
    deleteMock.mockResolvedValueOnce({ data: {} });

    const restored = await bulkInterestAction(["i-1"], "restore");
    const removed = await bulkInterestAction(["i-2"], "delete");

    expect(putMock).toHaveBeenCalledWith("/taxonomy/interests/i-1", { deprecated: false });
    expect(deleteMock).toHaveBeenCalledWith("/taxonomy/interests/i-2");
    expect(restored.affected).toEqual(["i-1"]);
    expect(removed.affected).toEqual(["i-2"]);
  });
});

describe("apiDetail", () => {
  const axiosError = (detail: unknown) =>
    Object.assign(new Error("Request failed"), {
      isAxiosError: true,
      response: { status: 422, data: { detail } },
    });

  it("renders FastAPI 422 arrays as readable location + message text", () => {
    const text = apiDetail(
      axiosError([
        { type: "too_long", loc: ["body", "ids"], msg: "String should have at most 200 items", input: [], ctx: {} },
        { type: "uuid_parsing", loc: ["body", "ids", 2], msg: "Input should be a valid UUID", input: "x" },
      ]),
    );
    expect(text).toContain("body.ids: String should have at most 200 items");
    expect(text).toContain("body.ids.2: Input should be a valid UUID");
  });

  it("renders object details as JSON instead of crashing", () => {
    const text = apiDetail(axiosError({ message: "nope" }));
    expect(text).toContain("nope");
  });

  it("passes string details through", () => {
    expect(apiDetail(axiosError("Skill not found"))).toBe("Skill not found");
    expect(apiDetail(new Error("boom"))).toBe("Error: boom");
  });
});
