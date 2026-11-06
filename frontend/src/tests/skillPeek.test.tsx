import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { PostingCard } from "@/features/postings/components/PostingCard";
import { SkillChip } from "@/features/postings/components/posting-detail/SkillChip";
import {
  skillAddress,
  type NormalizedSkill,
} from "@/features/postings/components/posting-detail/skills";
import { SkillPeekModal, clearSkillPeekCache, useSkillPeek } from "@/components/skills/SkillPeekModal";
import { fetchSkill, fetchSkillRelations } from "@/api/skills";
import type { PostingOut, SkillDetail, SkillRelationsResponse } from "@/types/wire";

vi.mock("@/api/skills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
    fetchSkillRelations: vi.fn(),
  };
});

const mocked = {
  fetchSkill: vi.mocked(fetchSkill),
  fetchSkillRelations: vi.mocked(fetchSkillRelations),
};

const DETAIL: SkillDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  key: "sql",
  label: "SQL",
  category: "general",
  description: "Structured query language.",
  parent_id: null,
  level_anchors: [
    { level: 3, label: "Guided", description: "Writes simple queries." },
    { level: 7, label: "Independent", description: "Designs schemas and tunes plans." },
  ],
  aliases: ["Sequel"],
  status: "active",
  children_keys: [],
  jobs: [],
  stats: {
    demand_count: 12,
    level_histogram: [],
    avg_required_level: 6.5,
    user_count: 4,
    first_seen: null,
    last_seen: null,
    corroboration: null,
  },
  merged_into: null,
  origin: "bank",
  parent_key: null,
};

const DETAIL_QL: SkillDetail = { ...DETAIL, key: "query-lang", label: "Query Language" };

const RELATIONS: SkillRelationsResponse = {
  nodes: [
    { id: "1", key: "sql", label: "SQL", status: "active" },
    { id: "2", key: "query-lang", label: "Query Language", status: "active" },
  ],
  edges: [{ id: "e1", source: "2", target: "1", relation: "is_a" }],
};

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
    source_key: "greenhouse",
    ref: "DE-0042",
    skills: [
      { key: "typescript", label: "TypeScript", required_level: 8, priority: "must_have" },
      { key: "postgres", label: "PostgreSQL", required_level: 5, priority: "nice_to_have" },
    ],
    ...overrides,
  } as PostingOut;
}

function detailSkill(overrides: Partial<NormalizedSkill> = {}): NormalizedSkill {
  return {
    key: "key:sql",
    label: "sql",
    unmapped: false,
    level: 7,
    priority: "must_have",
    priorityRank: 2,
    count: 1,
    evidence: "",
    confidence: 0.9,
    ...overrides,
  };
}

/** Mirrors the PostingDetailPage wiring (chip → useSkillPeek → modal). */
function DetailHarness({ skill }: { skill: NormalizedSkill }) {
  const peek = useSkillPeek();
  return (
    <MemoryRouter>
      <SkillChip
        skill={skill}
        onPeek={(trigger) => peek.open(skillAddress(skill), trigger, skill.level)}
      />
      <SkillPeekModal
        skillKey={peek.skillKey}
        highlightLevel={peek.highlightLevel}
        onClose={peek.close}
        returnFocusRef={peek.returnFocusRef}
      />
    </MemoryRouter>
  );
}

function renderCard(item: PostingOut, onOpen?: (value: PostingOut) => void) {
  return render(
    <MemoryRouter>
      <PostingCard posting={item} onOpen={onOpen} />
    </MemoryRouter>,
  );
}

describe("SkillPeekModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearSkillPeekCache();
    mocked.fetchSkill.mockImplementation(async (key: string) => {
      if (key === "quantum weaving") {
        throw new Error(`Request failed with status code 404: ${key}`);
      }
      if (key === "query-lang") return DETAIL_QL;
      if (key === "sql") return DETAIL;
      return { ...DETAIL, key, label: key };
    });
    mocked.fetchSkillRelations.mockResolvedValue(RELATIONS);
  });

  it("opens from a posting card chip with stopPropagation — the card does not navigate", async () => {
    const onOpen = vi.fn();
    renderCard(posting(), onOpen);

    fireEvent.click(screen.getAllByTestId("skill-tag")[0]);
    expect(onOpen).not.toHaveBeenCalled();

    expect(await screen.findByTestId("skill-peek")).toHaveAttribute("data-key", "typescript");
    expect(mocked.fetchSkill).toHaveBeenCalledWith("typescript");
    await waitFor(() =>
      expect(screen.getByTestId("skill-peek-stats")).toBeInTheDocument(),
    );
    // the card keeps rendering behind the modal
    expect(screen.getByTestId("posting-card")).toBeInTheDocument();
  });

  it("closing the peek never opens the posting — modal clicks stay contained (plan 188)", async () => {
    const onOpen = vi.fn();
    renderCard(posting(), onOpen);

    fireEvent.click(screen.getAllByTestId("skill-tag")[0]);
    expect(await screen.findByTestId("skill-peek")).toBeInTheDocument();

    // the peek footer's open-page link closes the peek AND navigates to the
    // skill page — its click must not bubble into the card's root onOpen
    fireEvent.click(screen.getByTestId("skill-peek-open-page"));
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.queryByTestId("skill-peek")).not.toBeInTheDocument();
    expect(screen.getByTestId("posting-card")).toBeInTheDocument();
  });

  it("opens from a detail chip under the bare taxonomy slug", async () => {
    render(<DetailHarness skill={detailSkill()} />);

    fireEvent.click(screen.getByRole("button", { name: /^sql/ }));
    expect(await screen.findByTestId("skill-peek")).toHaveAttribute("data-key", "sql");
    expect(mocked.fetchSkill).toHaveBeenCalledWith("sql");
    await waitFor(() => expect(screen.getByTestId("skill-peek-stats")).toBeInTheDocument());
    expect(screen.getByTestId("skill-peek-aliases")).toHaveTextContent("Sequel");
    expect(screen.getByTestId("skill-peek-status")).toHaveTextContent("active");
  });

  it("renders the pending-review state on 404 (raw labels never entered the taxonomy)", async () => {
    render(
      <DetailHarness
        skill={detailSkill({
          key: "raw:quantum weaving",
          label: "quantum weaving",
          unmapped: true,
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /quantum weaving/ }));
    const pending = await screen.findByTestId("skill-peek-pending");
    expect(pending).toHaveTextContent("Not in the catalog yet");
    expect(pending).toHaveTextContent("quantum weaving");
    expect(screen.queryByTestId("skill-peek-stats")).not.toBeInTheDocument();
  });

  it("highlights the anchor matching the chip's required level", async () => {
    render(<DetailHarness skill={detailSkill({ level: 7 })} />);

    fireEvent.click(screen.getByRole("button", { name: /^sql/ }));
    await screen.findByTestId("skill-peek");
    await waitFor(() => expect(screen.getByTestId("skill-peek-anchors")).toBeInTheDocument());
    expect(screen.getAllByTestId("skill-peek-anchor")).toHaveLength(2);
    const active = screen
      .getAllByTestId("skill-peek-anchor")
      .find((row) => row.dataset.active === "true");
    expect(active).toHaveAttribute("data-level", "7");  });

  it("switches to a related skill's key instead of stacking", async () => {
    render(<DetailHarness skill={detailSkill()} />);

    fireEvent.click(screen.getByRole("button", { name: /^sql/ }));
    const related = await screen.findByTestId("skill-peek-related-query-lang");
    fireEvent.click(related);

    expect(await screen.findByTestId("skill-peek")).toHaveAttribute("data-key", "query-lang");
    expect(mocked.fetchSkill).toHaveBeenCalledWith("query-lang");
    expect(await screen.findByTestId("skill-peek-status")).toBeInTheDocument();
    expect(screen.getByTestId("skill-peek-open-page")).toHaveAttribute(
      "href",
      "/skills/query-lang",
    );
  });

  it("caches per session — reopening a chip does not refetch", async () => {
    const { unmount } = renderCard(posting());
    fireEvent.click(screen.getAllByTestId("skill-tag")[0]);
    await screen.findByTestId("skill-peek");
    await waitFor(() => expect(screen.getByTestId("skill-peek-stats")).toBeInTheDocument());
    expect(mocked.fetchSkill).toHaveBeenCalledTimes(1);
    unmount();

    renderCard(posting());
    fireEvent.click(screen.getAllByTestId("skill-tag")[0]);
    await screen.findByTestId("skill-peek");
    await waitFor(() => expect(screen.getByTestId("skill-peek-stats")).toBeInTheDocument());
    expect(mocked.fetchSkill).toHaveBeenCalledTimes(1); // still one
  });

  it("closes on Escape and returns focus to the chip", async () => {
    const user = userEvent.setup();
    render(<DetailHarness skill={detailSkill()} />);

    const chip = screen.getByRole("button", { name: /^sql/ });
    await user.click(chip); // real focus, so both restore paths agree
    await screen.findByTestId("skill-peek");
    await waitFor(() => expect(screen.getByTestId("skill-peek-stats")).toBeInTheDocument());

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByTestId("skill-peek-body")).not.toBeInTheDocument(),
    );
    expect(chip).toHaveFocus();
  });
});
