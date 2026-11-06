import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaxonomyCatalogHygieneCard } from "@/components/settings/TaxonomyCatalogHygieneCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return {
    ...actual,
    fetchDuplicateJobTypes: vi.fn(),
    mergeJobTypes: vi.fn(),
  };
});

const { fetchDuplicateJobTypes, mergeJobTypes } = await import("@/api/taxonomy");
const fetchMock = vi.mocked(fetchDuplicateJobTypes);
const mergeMock = vi.mocked(mergeJobTypes);

const group = {
  normalized_title: "software engineer",
  jobs: [
    {
      id: "j-1",
      code: "software-engineer",
      title: "Software Engineer",
      family_key: "tech",
      created_at: "2026-01-01T00:00:00Z",
      posting_count: 2,
    },
    {
      id: "j-2",
      code: "software-engineer-2",
      title: "software engineer",
      family_key: "tech",
      created_at: "2026-02-01T00:00:00Z",
      posting_count: 6,
    },
  ],
};

afterEach(() => {
  fetchMock.mockReset();
  mergeMock.mockReset();
});

describe("TaxonomyCatalogHygieneCard", () => {
  it("lists duplicate groups and merges into the chosen survivor", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({ groups: [group] });
    mergeMock.mockResolvedValue({
      postings: 6,
      remap_queued: 6,
      skills: 1,
      tags: 1,
      relations: 0,
      departments: 0,
      match_insights: 0,
      career_paths: 0,
      growth_plans: 0,
      snapshots: 0,
      audit_event: "audit-1",
    });
    const onDone = vi.fn();
    render(<TaxonomyCatalogHygieneCard onDone={onDone} />);

    await screen.findByTestId("catalog-hygiene");
    expect(screen.getByTestId("catalog-hygiene-survivor-software-engineer")).toBeTruthy();
    await user.click(screen.getByTestId("catalog-hygiene-merge-software-engineer-2"));
    const confirms = await screen.findAllByRole("button", {
      name: "taxonomy.catalogHygiene.confirm",
    });
    fireEvent.click(confirms[confirms.length - 1]);
    await waitFor(() => expect(mergeMock).toHaveBeenCalledWith("j-2", "j-1"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("renders nothing when no duplicates exist", async () => {
    fetchMock.mockResolvedValue({ groups: [] });
    render(<TaxonomyCatalogHygieneCard />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId("catalog-hygiene")).toBeNull();
  });
});
