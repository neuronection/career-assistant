import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Postings } from "@/pages/Postings";
import {
  fetchPostings,
  fetchPostingDetail,
  markPostingsSeen,
  markApplied,
  savePosting,
  searchPostings,
} from "@/api/postings";
import type { JobPostingItem } from "@/types";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    savePosting: vi.fn().mockResolvedValue(undefined),
    hidePosting: vi.fn().mockResolvedValue(undefined),
    searchPostings: vi.fn(),
    fetchPostingDetail: vi.fn(),
  };
});

vi.mock("@/api/skills", () => ({
  fetchSkillOntology: vi.fn().mockResolvedValue([
    { key: "programming", label: "Programming", status: "active" },
    { key: "sql", label: "SQL", status: "active" },
  ]),
}));

vi.mock("@/components/ui", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/components/ui")>();
  const FakeCombobox = (props: { value?: string; onChange: (v: string) => void }) => (
    <input
      data-testid="skill-combobox"
      value={props.value ?? ""}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
  return { ...mod, SearchableDropdown: FakeCombobox };
});

const mockFetchPostings = vi.mocked(fetchPostings);
const mockSearchPostings = vi.mocked(searchPostings);
const mockFetchDetail = vi.mocked(fetchPostingDetail);

function posting(overrides: Partial<JobPostingItem> = {}): JobPostingItem {
  return {
    id: "p1",
    source_id: "s1",
    external_id: "ext-1",
    title: "Backend Engineer",
    org: "ACME",
    location: { city: "Athens", country: "GR", remote: true },
    url: "https://jobs.example/1",
    seniority: "mid",
    posted_at: "2026-08-20T00:00:00Z",
    status: "mapped",
    fit: 7.5,
    seen: false,
    saved: false,
    notes: "",
    source_key: "synth",
    ...overrides,
  };
}

describe("Postings live tab", () => {
  beforeEach(() => {
    mockFetchPostings.mockResolvedValue({
      items: [posting()],
      total: 1,
      unseen: 1,
    });
  });

  it("renders posting cards with source badge, fit and unseen count", async () => {
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("postings")).toBeInTheDocument();
    expect(screen.getByTestId("posting-title")).toHaveTextContent("Backend Engineer");
    expect(screen.getByText("synth")).toBeInTheDocument();
    expect(screen.getByText(/1 new/)).toBeInTheDocument();
    expect(screen.getByText(/fit 7\.5/)).toBeInTheDocument();
  });

  it("marks seen and applied when opening the original url", async () => {
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("posting-title"));
    await waitFor(() => expect(markPostingsSeen).toHaveBeenCalledWith(["p1"]));
    expect(markApplied).toHaveBeenCalledWith("p1", "https://jobs.example/1");
  });

  it("toggles save and reloads", async () => {
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByText("Save"));
    await waitFor(() => expect(savePosting).toHaveBeenCalledWith("p1", true));
    await waitFor(() =>
      expect(mockFetchPostings).toHaveBeenCalledWith(
        expect.objectContaining({ saved: false, sort: "fit" })
      )
    );
  });

  it("switches to the saved view", async () => {
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("postings-saved-toggle"));
    await waitFor(() =>
      expect(mockFetchPostings).toHaveBeenCalledWith(
        expect.objectContaining({ saved: true })
      )
    );
  });
});

describe("Skill-level search & provenance (plan 31)", () => {
  beforeEach(() => {
    mockFetchPostings.mockResolvedValue({
      items: [posting()],
      total: 1,
      unseen: 1,
    });
    mockSearchPostings.mockResolvedValue({
      items: [posting({ id: "p2", coverage: 8.2 })],
      total: 1,
      unseen: 0,
    });
  });

  it("shows the provenance chip (raw / fast-mapped / extracted)", async () => {
    const first = render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    const chip = await screen.findByTestId("posting-provenance");
    expect(chip).toHaveTextContent("raw"); // no mapping yet in this fixture
    first.unmount();

    mockFetchPostings.mockResolvedValue({
      items: [
        posting({ id: "p9", mapping_method: "skill_overlap", extract_version: 1 }),
      ],
      total: 1,
      unseen: 0,
    });
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    const extracted = await screen.findByTestId("posting-provenance");
    expect(extracted).toHaveTextContent("extracted");
  });

  it("adds a skill filter and searches with level + profile ranking", async () => {
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    await screen.findByTestId("postings");

    fireEvent.change(screen.getByTestId("skill-combobox"), {
      target: { value: "programming" },
    });
    fireEvent.change(screen.getByTestId("level-select"), {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByTestId("add-skill-filter"));

    const chip = await screen.findByTestId("skill-chip-programming");
    expect(chip).toHaveTextContent("programming ≥ 4");
    await waitFor(() =>
      expect(mockSearchPostings).toHaveBeenCalledWith(
        expect.objectContaining({ skills: "programming:4", mode: "all" })
      )
    );

    fireEvent.change(screen.getByTestId("match-mode"), {
      target: { value: "any" },
    });
    await waitFor(() =>
      expect(mockSearchPostings).toHaveBeenLastCalledWith(
        expect.objectContaining({ mode: "any" })
      )
    );

    fireEvent.change(screen.getByTestId("priority-select"), {
      target: { value: "must_have" },
    });
    await waitFor(() =>
      expect(mockSearchPostings).toHaveBeenLastCalledWith(
        expect.objectContaining({ priority: "must_have" })
      )
    );

    fireEvent.click(screen.getByTestId("match-profile-toggle"));
    await waitFor(() =>
      expect(mockSearchPostings).toHaveBeenLastCalledWith(
        expect.objectContaining({ match_profile: true })
      )
    );
    expect(await screen.findByTestId("posting-coverage")).toHaveTextContent(
      "coverage 8.2"
    );
  });

  it("opens the detail modal with the structured extract", async () => {
    mockFetchDetail.mockResolvedValue(
      posting({
        extract_version: 1,
        extract: {
          skills: [
            {
              skill_key: "programming",
              required_level: 5,
              priority: "must_have",
              evidence_quote: "strong programming background required",
              confidence: 0.95,
            },
          ],
          responsibilities: [
            { text: "Build dashboards", time_pct: 40, optional: false },
          ],
          benefits: ["Remote budget"],
        },
      })
    );
    render(
      <MemoryRouter>
        <Postings />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("posting-details"));
    const detail = await screen.findByTestId("posting-detail");
    expect(detail).toBeInTheDocument();
    expect(await screen.findByTestId("provenance")).toHaveTextContent("extracted");
    expect(screen.getByText(/40% of time/)).toBeInTheDocument();
    expect(screen.getByText("Remote budget")).toBeInTheDocument();
    // evidence quotes render on tap
    fireEvent.click(screen.getByLabelText("Show evidence"));
    expect(screen.getByTestId("skill-evidence")).toHaveTextContent(
      "strong programming background required"
    );
  });
});
