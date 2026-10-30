import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { markPostingsSeen } from "@/api/postings";
import { PostingCard } from "@/features/postings/components/PostingCard";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/postings", () => ({
  markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
  savePosting: vi.fn().mockResolvedValue(undefined),
  hidePosting: vi.fn().mockResolvedValue(undefined),
  markApplied: vi.fn().mockResolvedValue(undefined),
}));

function posting(overrides: Partial<PostingOut> = {}): PostingOut {
  return {
    id: "p1",
    source_id: "s1",
    external_id: "e1",
    title: "Senior Backend Engineer",
    org: "Acme GmbH",
    org_key: "acme",
    location: { city: "Berlin", country: "DE", remote: true },
    url: "https://jobs.example/1",
    status: "mapped",
    mapping_reason: "",
    posted_at: "2026-10-26T00:00:00Z",
    fit: 7.5,
    coverage: 5,
    salary_currency: "EUR",
    salary_min: 60000,
    salary_max: 75000,
    salary_period: "year",
    source_key: "greenhouse",
    ref: "DE-0042",
    skills: [
      { key: "typescript", label: "TypeScript", required_level: 8, priority: "must_have" },
      { key: "postgres", label: "PostgreSQL", required_level: 5, priority: "nice_to_have" },
    ],
    ...overrides,
  } as PostingOut;
}

function renderCard(item: PostingOut, onOpen?: (value: PostingOut) => void) {
  return render(
    <MemoryRouter>
      <PostingCard posting={item} onOpen={onOpen} />
    </MemoryRouter>
  );
}

describe("PostingCard", () => {
  it("renders the structured card: score, org link, meta, spec slots", () => {
    const { container } = renderCard(posting());
    expect(screen.getByTestId("posting-title")).toHaveTextContent(
      "Senior Backend Engineer"
    );
    expect(screen.getByTestId("score-ring")).toHaveAttribute("data-score", "7.5");
    expect(screen.getByText("Acme GmbH")).toHaveAttribute("href", "/companies/acme");
    const specs = Array.from(container.querySelectorAll("[data-spec]")).map((node) =>
      node.getAttribute("data-spec")
    );
    expect(specs).toEqual(["mode", "salary"]);
    expect(screen.getByText("Berlin, DE")).toBeInTheDocument();
  });

  it("renders the skill strip with heat and level", () => {
    renderCard(posting());
    const chips = screen.getAllByTestId("skill-tag");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveAttribute("data-heat", "hot");
    expect(chips[0]).toHaveTextContent("TypeScript");
    expect(chips[0]).toHaveTextContent("8");
    expect(chips[1]).toHaveAttribute("data-heat", "warm");
  });

  it("shows the details-pending line for an unextracted posting", () => {
    renderCard(posting({ skills: [] }));
    expect(screen.getByTestId("posting-details-pending")).toHaveTextContent(
      "Details not fetched yet"
    );
  });

  it("marks a seen posting with the quiet seen icon", () => {
    renderCard(posting({ seen: true }));
    expect(screen.getByTestId("posting-seen")).toBeInTheDocument();
    expect(screen.queryByTestId("posting-mark-seen")).not.toBeInTheDocument();
  });

  it("marks a posting seen from the card without opening it", async () => {
    const onOpen = vi.fn();
    renderCard(posting(), onOpen);
    expect(screen.getByTestId("posting-card")).not.toHaveAttribute("data-seen");
    fireEvent.click(screen.getByTestId("posting-mark-seen"));
    expect(onOpen).not.toHaveBeenCalled();
    expect(markPostingsSeen).toHaveBeenCalledWith(["p1"]);
    await waitFor(() =>
      expect(screen.getByTestId("posting-card")).toHaveAttribute("data-seen", "true")
    );
    expect(screen.getByTestId("posting-seen")).toBeInTheDocument();
    expect(document.activeElement).toContainElement(screen.getByTestId("posting-seen"));
    expect(screen.queryByTestId("posting-mark-seen")).not.toBeInTheDocument();
  });

  it("rolls the seen mark back when the request fails", async () => {
    vi.mocked(markPostingsSeen).mockRejectedValueOnce(new Error("offline"));
    renderCard(posting());
    fireEvent.click(screen.getByTestId("posting-mark-seen"));
    await waitFor(() =>
      expect(screen.getByTestId("posting-mark-seen")).toBeInTheDocument()
    );
    expect(screen.getByTestId("posting-card")).not.toHaveAttribute("data-seen");
  });

  it("marks partial details instead of a needs-review chip", () => {
    renderCard(posting({ needs_review: true }));
    expect(screen.getByTestId("posting-partial")).toBeInTheDocument();
    expect(screen.queryByText(/needs review/i)).not.toBeInTheDocument();
  });

  it("renders a closed posting with the closed mark and a disabled apply", () => {
    renderCard(posting({ status: "expired" }));
    expect(screen.getByTestId("posting-card")).toHaveAttribute("data-state", "closed");
    expect(screen.getByTestId("posting-closed")).toBeInTheDocument();
    expect(screen.getByTestId("posting-apply")).toHaveAttribute("aria-disabled", "true");
  });

  it("opens the posting from the title and the card body", () => {
    const onOpen = vi.fn();
    renderCard(posting(), onOpen);
    fireEvent.click(screen.getByTestId("posting-title"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("posting-card"));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });
});
