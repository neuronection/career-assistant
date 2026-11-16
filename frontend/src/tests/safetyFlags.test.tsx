import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SafetyFlagsCard } from "@/features/postings/components/posting-detail/SafetyFlagsCard";

describe("SafetyFlagsCard", () => {
  it("renders factual flags with evidence and no-verdict copy", () => {
    render(
      <SafetyFlagsCard
        flags={[
          {
            key: "fee_requested",
            label: "Payment or fee mentioned",
            evidence: "There is a registration fee to apply.",
          },
          {
            key: "messaging_app_contact",
            label: "Messaging-app contact",
            evidence: "Message us on WhatsApp.",
          },
          { key: "personal_email_domain", label: "Personal email domain", evidence: "hr@gmail.com" },
          { key: "vague_org", label: "Organisation is vague", evidence: "Private company" },
          { key: "salary_outlier", label: "Pay far above the catalog band", evidence: "Posted range starts at 200,000 EUR" },
          { key: "url_mismatch", label: "Shortened or personal link", evidence: "https://bit.ly/x" },
        ]}
      />
    );
    expect(screen.getByTestId("posting-safety")).toHaveTextContent(
      "Check before applying"
    );
    expect(screen.getByTestId("posting-safety-fee_requested")).toHaveTextContent(
      "registration fee"
    );
    expect(screen.getByTestId("posting-safety-messaging_app_contact")).toHaveTextContent(
      "WhatsApp"
    );
    expect(screen.getByTestId("posting-safety")).toHaveTextContent("not a verdict");
    expect(screen.getByTestId("posting-safety")).not.toHaveTextContent("scam");
  });

  it("renders nothing without flags", () => {
    const { container } = render(<SafetyFlagsCard flags={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
