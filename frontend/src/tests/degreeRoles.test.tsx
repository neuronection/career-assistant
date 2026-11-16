import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DegreeRolesBanner } from "@/features/catalog/components/DegreeRolesBanner";
import { DEFAULT_FILTERS } from "@/features/catalog/exploreParams";
import { fetchDegreeRoles } from "@/api/discipline";

vi.mock("@/api/discipline", () => ({ fetchDegreeRoles: vi.fn() }));

const DATA = {
  matches: [
    {
      family_key: "technology-software",
      family_title: "Software Development",
      matched_terms: ["computer science"],
      reason: "matched" as const,
      depth: 0,
    },
    {
      family_key: "technology",
      family_title: "Technology & IT",
      matched_terms: ["computer science"],
      reason: "parent" as const,
      depth: 1,
    },
    {
      family_key: "technology-data",
      family_title: "Data & AI",
      matched_terms: ["computer science"],
      reason: "family_expansion" as const,
      depth: 1,
    },
  ],
};

describe("DegreeRolesBanner", () => {
  beforeEach(() => {
    vi.mocked(fetchDegreeRoles).mockResolvedValue(DATA);
  });

  it("shows mapped families and applies them as an opt-in filter", async () => {
    const onApply = vi.fn();
    render(<DegreeRolesBanner filters={DEFAULT_FILTERS} onApply={onApply} />);
    expect(await screen.findByTestId("degree-roles")).toHaveTextContent(
      "Software Development"
    );
    fireEvent.click(screen.getByTestId("degree-roles-apply"));
    expect(onApply).toHaveBeenCalledWith(
      ["technology-software", "technology", "technology-data"],
      "apply"
    );
  });

  it("clears only the degree families when already applied", async () => {
    const onApply = vi.fn();
    const filters = {
      ...DEFAULT_FILTERS,
      mappedFamily: ["technology-software", "technology", "technology-data", "business"],
    };
    render(<DegreeRolesBanner filters={filters} onApply={onApply} />);
    await screen.findByTestId("degree-roles");
    fireEvent.click(screen.getByTestId("degree-roles-apply"));
    expect(onApply).toHaveBeenCalledWith(
      ["technology-software", "technology", "technology-data"],
      "clear"
    );
  });

  it("renders nothing when the profile has no matching education", async () => {
    vi.mocked(fetchDegreeRoles).mockResolvedValue({ matches: [] });
    const { container } = render(
      <DegreeRolesBanner filters={DEFAULT_FILTERS} onApply={vi.fn()} />
    );
    await waitFor(() => expect(fetchDegreeRoles).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders nothing when the request fails", async () => {
    vi.mocked(fetchDegreeRoles).mockRejectedValue(new Error("offline"));
    const { container } = render(
      <DegreeRolesBanner filters={DEFAULT_FILTERS} onApply={vi.fn()} />
    );
    await waitFor(() => expect(fetchDegreeRoles).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
