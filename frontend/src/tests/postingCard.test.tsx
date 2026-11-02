import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import { markPostingsSeen } from "@/api/postings";
import { fetchSkill, fetchSkillRelations } from "@/api/skills";
import { clearSkillPeekCache } from "@/components/skills/SkillPeekModal";
import { PostingCard } from "@/features/postings/components/PostingCard";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/postings", () => ({
  markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
  savePosting: vi.fn().mockResolvedValue(undefined),
  hidePosting: vi.fn().mockResolvedValue(undefined),
  markApplied: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/skills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skills")>();
  return {
    ...actual,
    fetchSkill: vi.fn(),
    fetchSkillRelations: vi.fn(),
  };
});

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

describe("PostingCard entity menu (plan 188)", () => {
  function LocationProbe() {
    const location = useLocation();
    return (
      <span data-testid="probe-path">
        {location.pathname}
        {location.search}
      </span>
    );
  }

  const DETAIL_TS = {
    id: "22222222-2222-4222-8222-222222222222",
    key: "typescript",
    label: "TypeScript",
    category: "general",
    description: "Typed JavaScript.",
    parent_id: null,
    level_anchors: [],
    aliases: [],
    status: "active",
    children_keys: [],
    jobs: [],
    stats: {
      demand_count: 9,
      level_histogram: [],
      avg_required_level: 6,
      user_count: 2,
      first_seen: null,
      last_seen: null,
      corroboration: null,
    },
    merged_into: null,
    origin: "bank",
    parent_key: null,
  };

  const cardFilterMenu = (state: "include" | "exclude" | null = null) => ({
    stateOf: vi.fn(() => state),
    apply: vi.fn(),
  });

  function renderMenuCard(
    item: PostingOut,
    menu: ReturnType<typeof cardFilterMenu> | undefined,
  ) {
    return render(
      <MemoryRouter>
        <PostingCard posting={item} filterMenu={menu} />
      </MemoryRouter>
    );
  }

  beforeEach(() => {
    clearSkillPeekCache();
    vi.mocked(fetchSkill).mockResolvedValue(DETAIL_TS as never);
    vi.mocked(fetchSkillRelations).mockResolvedValue({ nodes: [], edges: [] } as never);
  });

  it("clicking a skill chip opens the menu and include applies the target", async () => {
    const user = userEvent.setup();
    const menu = cardFilterMenu();
    renderMenuCard(posting(), menu);
    await user.click(screen.getAllByTestId("skill-tag")[0]);
    const include = await screen.findByRole("menuitem", { name: /Include “TypeScript”/ });
    await user.click(include);
    expect(menu.apply).toHaveBeenCalledWith(
      { axis: "skills", value: "typescript", label: "TypeScript", pageTo: "/skills/typescript" },
      "include"
    );
  });

  it("right-click opens the menu on a skill chip and on a spec value", async () => {
    const menu = cardFilterMenu();
    const { container } = renderMenuCard(posting(), menu);
    fireEvent.contextMenu(screen.getAllByTestId("skill-tag")[0]);
    expect(await screen.findByRole("menuitem", { name: /Exclude “TypeScript”/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: /Exclude “TypeScript”/ }));
    await waitFor(() => expect(screen.queryByRole("menuitem")).not.toBeInTheDocument());

    fireEvent.contextMenu(container.querySelector('[data-spec="mode"]')!);
    const remoteExclude = await screen.findByRole("menuitem", { name: /Exclude/ });
    fireEvent.click(remoteExclude);
    expect(menu.apply).toHaveBeenCalledWith(
      expect.objectContaining({ axis: "remotePolicy", value: "remote" }),
      "exclude"
    );
  });

  it("an active value gains the remove entry, which clears it", async () => {
    const menu = cardFilterMenu("include");
    renderMenuCard(posting(), menu);
    fireEvent.contextMenu(screen.getAllByTestId("skill-tag")[0]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove from filters" }));
    expect(menu.apply).toHaveBeenCalledWith(
      expect.objectContaining({ axis: "skills", value: "typescript" }),
      "clear"
    );
  });

  it("skill details opens the peek from the menu", async () => {
    const user = userEvent.setup();
    renderMenuCard(posting(), cardFilterMenu());
    await user.click(screen.getAllByTestId("skill-tag")[0]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Skill details" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByText("TypeScript").length).toBeGreaterThanOrEqual(1);
  });

  it("the company name opens the menu; the page entry navigates; ctrl-click stays native", async () => {
    const user = userEvent.setup();
    const menu = cardFilterMenu();
    render(
      <MemoryRouter initialEntries={["/postings"]}>
        <PostingCard posting={posting()} filterMenu={menu} />
        <LocationProbe />
      </MemoryRouter>
    );
    const link = screen.getByText("Acme GmbH");
    await user.click(link);
    fireEvent.click(await screen.findByRole("menuitem", { name: /Include “Acme GmbH”/ }));
    expect(menu.apply).toHaveBeenCalledWith(
      { axis: "orgs", value: "Acme GmbH", label: "Acme GmbH", pageTo: "/companies/acme" },
      "include"
    );
    expect(screen.getByTestId("probe-path")).toHaveTextContent("/postings");

    fireEvent.contextMenu(link);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Open company page" }));
    await waitFor(() =>
      expect(screen.getByTestId("probe-path")).toHaveTextContent("/companies/acme")
    );
    expect(menu.apply).toHaveBeenCalledTimes(1);

    fireEvent.click(link, { metaKey: true });
    expect(menu.apply).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  it("an org without a key offers the filter menu but no company page", async () => {
    const menu = cardFilterMenu();
    renderMenuCard(posting({ org_key: undefined }), menu);
    fireEvent.contextMenu(screen.getByText("Acme GmbH"));
    await screen.findByRole("menuitem", { name: /Include “Acme GmbH”/ });
    expect(screen.queryByRole("menuitem", { name: "Open company page" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: /Include “Acme GmbH”/ }));
    expect(menu.apply).toHaveBeenCalledWith(
      { axis: "orgs", value: "Acme GmbH", label: "Acme GmbH" },
      "include"
    );
  });

  it("without a filter api the card renders exactly as before", () => {
    renderMenuCard(posting(), undefined);
    fireEvent.contextMenu(screen.getAllByTestId("skill-tag")[0]);
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });
});
