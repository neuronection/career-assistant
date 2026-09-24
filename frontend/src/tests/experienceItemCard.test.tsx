import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  ExperienceItemCard,
  type ExperienceItemCardData,
} from "@/components/experience/ExperienceItemCard";
import { safeExternalUrl } from "@/lib/url";

const ITEM: ExperienceItemCardData = {
  id: "e1",
  title: "Backend intern",
  kind: "internship",
  org_name: "Siemens",
  start: "2025-01-01",
  end: "2025-07-01",
  open_ended: false,
  hours_per_week: 20,
  onsite_policy: "hybrid",
  status: "active",
  description: "A long description that should be clamped in compact density.",
  links: [
    { label: "Repo", url: "https://github.com/example/repo", kind: "github" },
    { label: "Evil", url: "javascript:alert(1)", kind: "web" },
  ],
  skills: [
    { skill_key: "python", skill_label: "Python", role_in_item: "primary", level_claim: 4 },
    { skill_key: "docker", skill_label: "Docker", role_in_item: "secondary", level_claim: 3 },
    { skill_key: "sql", skill_label: "SQL", role_in_item: "exposure" },
    { skill_key: "git", skill_label: "Git", role_in_item: "primary" },
  ],
  achievements: [{ text: "Cut build time by 40%" }],
};

function renderCard(density: "compact" | "full") {
  return render(
    <MemoryRouter>
      <ExperienceItemCard item={ITEM} density={density} />
    </MemoryRouter>,
  );
}

describe("ExperienceItemCard density", () => {
  it("compact shows the first three skills and no links/achievements", () => {
    renderCard("compact");
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.queryByText("Git")).not.toBeInTheDocument();
    expect(screen.queryByText(/Cut build time by 40%/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("experience-item-link")).not.toBeInTheDocument();
  });

  it("full shows all skills with role/level, achievements and safe links", () => {
    renderCard("full");
    expect(screen.getByText("Git · primary")).toBeInTheDocument();
    expect(screen.getByText("Python · primary · lvl 4")).toBeInTheDocument();
    expect(screen.getByText(/Cut build time by 40%/)).toBeInTheDocument();

    const links = screen.getAllByTestId("experience-item-link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://github.com/example/repo");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText("Evil")).not.toBeInTheDocument();
    expect(screen.getByText(/Hybrid/i)).toBeInTheDocument();
  });
});

describe("safeExternalUrl", () => {
  it("allows only absolute http(s) urls", () => {
    expect(safeExternalUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeExternalUrl("http://example.com")).toBe("http://example.com/");
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("data:text/html,x")).toBeNull();
    expect(safeExternalUrl("/relative")).toBeNull();
    expect(safeExternalUrl("")).toBeNull();
    expect(safeExternalUrl(null)).toBeNull();
  });
});
