import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PostingHygieneSection } from "@/components/settings/PostingHygieneSection";
import {
  clearPostingHygiene,
  fetchPostingHygiene,
  mergePostingHygiene,
  scanPostingHygiene,
} from "@/api/postingHygiene";

vi.mock("@/api/postingHygiene", () => ({
  fetchPostingHygiene: vi.fn(),
  scanPostingHygiene: vi.fn(),
  mergePostingHygiene: vi.fn(),
  clearPostingHygiene: vi.fn(),
}));

const OVERVIEW = {
  canonical: [
    {
      id: "c1",
      ref: "C1",
      title: "Backend Engineer",
      org: "Acme",
      repost_count: 2,
      last_verified_at: "2026-11-11T00:00:00Z",
    },
  ],
  duplicates: [
    {
      id: "d1",
      ref: "D1",
      title: "Backend Engineer (m/f/d)",
      org: "Acme",
      duplicate_of_id: "c1",
    },
  ],
  candidates: [
    {
      id: "p1",
      ref: "P1",
      title: "Backend Engineer Python",
      org: "Acme",
      candidates: [
        { posting_id: "c1", ref: "C1", title: "Backend Engineer", org: "Acme", score: 0.67, reason: "title_location" },
      ],
    },
  ],
  counts: { canonical: 1, duplicates: 1, candidates: 1 },
};

describe("PostingHygieneSection", () => {
  beforeEach(() => {
    vi.mocked(fetchPostingHygiene).mockResolvedValue(OVERVIEW);
    vi.mocked(scanPostingHygiene).mockResolvedValue({});
    vi.mocked(mergePostingHygiene).mockResolvedValue();
    vi.mocked(clearPostingHygiene).mockResolvedValue();
  });

  it("shows proposals, merges one and clears a merge", async () => {
    render(<PostingHygieneSection />);
    expect(await screen.findByTestId("hygiene-candidate-p1")).toHaveTextContent(
      "Backend Engineer Python",
    );
    fireEvent.click(screen.getByTestId("hygiene-merge-p1"));
    await waitFor(() => expect(mergePostingHygiene).toHaveBeenCalledWith("p1", "c1"));

    fireEvent.click(screen.getByTestId("hygiene-clear-d1"));
    await waitFor(() => expect(clearPostingHygiene).toHaveBeenCalledWith("d1"));
  });

  it("runs the deterministic scan", async () => {
    render(<PostingHygieneSection />);
    await screen.findByTestId("hygiene-scan");
    fireEvent.click(screen.getByTestId("hygiene-scan"));
    await waitFor(() => expect(scanPostingHygiene).toHaveBeenCalled());
  });
});
