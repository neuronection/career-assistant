import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CardSpec } from "@/components/cards/CardSpec";
import { orderSpecs, type SpecItem } from "@/components/cards/specOrder";
import { postingSpecs } from "@/features/postings/components/PostingCard";
import type { PostingOut } from "@/types/wire";

const TEMPLATES: Record<string, string> = {
  "card.perYear": "≈ {{range}} {{currency}}/yr",
};

const t = (key: string, opts?: Record<string, unknown>) =>
  String(TEMPLATES[key] ?? opts?.defaultValue ?? key).replace(
    /\{\{(\w+)\}\}/g,
    (_, name: string) => String(opts?.[name] ?? "")
  );

function posting(overrides: Partial<PostingOut> = {}): PostingOut {
  return {
    id: "p1",
    source_id: "s1",
    external_id: "e1",
    title: "Backend Engineer",
    org: "ACME",
    location: { city: "Berlin", country: "DE", remote: false },
    url: "https://jobs.example/1",
    status: "mapped",
    mapping_reason: "",
    ...overrides,
  } as PostingOut;
}

describe("CardSpec", () => {
  it("renders the canonical order regardless of input order", () => {
    const items: SpecItem[] = [
      { key: "salary", label: "salary", value: "60–75k / yr" },
      { key: "mode", label: "mode", value: "Remote" },
      { key: "level", label: "level", value: "Senior" },
    ];
    const { container } = render(<CardSpec items={items} />);
    const order = Array.from(container.querySelectorAll("[data-spec]")).map((node) =>
      node.getAttribute("data-spec")
    );
    expect(order).toEqual(["mode", "level", "salary"]);
  });

  it("drops empty values instead of leaving holes", () => {
    render(
      <CardSpec
        items={[
          { key: "mode", label: "mode", value: "" },
          { key: "level", label: "level", value: "Senior" },
        ]}
      />
    );
    expect(screen.queryByText("mode")).not.toBeInTheDocument();
    expect(screen.getByText("level")).toBeInTheDocument();
  });

  it("orders unknown keys last", () => {
    const ordered = orderSpecs([
      { key: "closes", label: "closes", value: "in 3 d" },
      { key: "mode", label: "mode", value: "Remote" },
    ]);
    expect(ordered.map((item) => item.key)).toEqual(["mode", "closes"]);
  });
});

describe("postingSpecs", () => {
  it("maps structured fields into labeled slots", () => {
    const specs = postingSpecs(
      posting({
        onsite_policy: "hybrid",
        seniority: "senior",
        employment_type: "full_time",
        work_hours: "40 h",
        salary_currency: "EUR",
        salary_min: 60000,
        salary_max: 75000,
        salary_period: "year",
        salary_basis: "gross",
      }),
      t
    );
    const byKey = Object.fromEntries(specs.map((spec) => [spec.key, spec.value]));
    expect(byKey.mode).toBe("hybrid");
    expect(byKey.level).toBe("senior");
    expect(byKey.contract).toBe("full time");
    expect(byKey.hours).toBe("40 h");
    expect(byKey.salary).toBe("EUR 60k–75k / year gross");
  });

  it("adds the normalized annual range for non-year periods", () => {
    const specs = postingSpecs(
      posting({
        salary_currency: "EUR",
        salary_min: 3000,
        salary_max: 3500,
        salary_period: "month",
        salary_normalized_min: 36000,
        salary_normalized_max: 42000,
      }),
      t
    );
    const salary = specs.find((spec) => spec.key === "salary")?.value ?? "";
    expect(salary).toContain("3,000–3,500 / month");
    expect(salary).toContain("≈ 36k–42k EUR/yr");
  });

  it("flags a closing posting only inside the week window", () => {
    const soon = new Date(Date.now() + 3 * 86_400_000).toISOString();
    const far = new Date(Date.now() + 30 * 86_400_000).toISOString();
    const soonSpecs = postingSpecs(posting({ expires_at: soon }), t);
    expect(soonSpecs.find((spec) => spec.key === "closes")?.tone).toBe("warning");
    const farSpecs = postingSpecs(posting({ expires_at: far }), t);
    expect(farSpecs.find((spec) => spec.key === "closes")).toBeUndefined();
  });

  it("derives mode from the remote flag when no policy was extracted", () => {
    const specs = postingSpecs(
      posting({ location: { city: "Berlin", country: "DE", remote: true } }),
      t
    );
    expect(specs.find((spec) => spec.key === "mode")?.value).toBe("remote");
  });
});
