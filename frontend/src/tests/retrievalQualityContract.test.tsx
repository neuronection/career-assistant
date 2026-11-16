import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  fetchRetrievalQuality,
  fetchRetrievalSpaces,
  type RetrievalQuality,
  type RetrievalSpacesResponse,
} from "@/api/retrieval";
import { RetrievalQualitySection } from "@/components/audit/retrieval/RetrievalQualitySection";

vi.mock("@/api/retrieval", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/retrieval")>();
  return {
    ...actual,
    fetchRetrievalSpaces: vi.fn(),
    fetchRetrievalQuality: vi.fn(),
  };
});

const contract = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../contracts/retrieval-quality-compare.fields.json"),
    "utf8"
  )
) as { fields: string[]; query_fields: string[] };

const VALUES: Record<string, unknown> = {
  baseline_space_id: "space-active",
  new_space_id: "space-build",
  set_version: 3,
  k: 5,
  baseline_recall_at_k: 0.9,
  baseline_precision_at_k: 0.7,
  new_recall_at_k: 0.5,
  new_precision_at_k: 0.5,
  passed: false,
  floor_recall: 0.8,
  floor_precision: 0.5,
  required_for_activation: true,
  queries: [],
  generated_at: "2026-11-11T09:00:00Z",
};

function comparePayload(): Record<string, unknown> {
  expect(contract.fields.filter((field) => !(field in VALUES))).toEqual([]);
  return Object.fromEntries(
    contract.fields.map((field) => [field, VALUES[field]])
  );
}

beforeEach(() => {
  vi.mocked(fetchRetrievalSpaces).mockResolvedValue({
    state: "ok",
    count: 1,
    spaces: [{ space_id: "space-active", name: "active", status: "active" }],
    backend: "pgvector",
  } as unknown as RetrievalSpacesResponse);
  vi.mocked(fetchRetrievalQuality).mockResolvedValue({
    state: "ok",
    space_id: "space-active",
    name: "active",
    sampled: true,
    set: {
      space_id: "space-active",
      set_version: 3,
      k: 5,
      floor_recall: 0.8,
      floor_precision: 0.5,
      query_count: contract.query_fields.length,
      query_ids: [],
      revision_key: "rev-3",
    },
    quality: null,
    compare: comparePayload(),
    window: {
      preset: "24h",
      start: "2026-11-11T00:00:00Z",
      end: "2026-11-11T23:59:59Z",
    },
  } as unknown as RetrievalQuality);
});

describe("retrieval quality wire contract", () => {
  it("renders the compare panel from the shared field list", async () => {
    render(
      <MemoryRouter>
        <RetrievalQualitySection
          window="24h"
          detailId={null}
          onOpenDetail={() => {}}
          onCloseDetail={() => {}}
        />
      </MemoryRouter>
    );

    const panel = await screen.findByTestId("retrieval-quality-compare");
    expect(panel.textContent).toContain("space-ac");
    expect(panel.textContent).toContain("90.0%");
    expect(panel.textContent).not.toContain("NaN");
    expect(panel.textContent).not.toContain("undefined");
  });
});
