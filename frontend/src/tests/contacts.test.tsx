import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Contacts } from "@/features/contacts/pages/Contacts";
import {
  createContact,
  draftOutreach,
  fetchContact,
  fetchContacts,
} from "@/api/contacts";

vi.mock("@/api/contacts", () => ({
  fetchContacts: vi.fn(),
  fetchContact: vi.fn(),
  createContact: vi.fn(),
  updateContact: vi.fn(),
  deleteContact: vi.fn(),
  addContactInteraction: vi.fn(),
  deleteContactInteraction: vi.fn(),
  draftOutreach: vi.fn(),
}));

const CONTACT = {
  id: "c1",
  name: "Ada Recruiter",
  org: "Acme",
  role: "Talent",
  email: "ada@example.com",
  profile_url: "",
  notes: "",
  tags: [],
  last_contacted_at: null,
  source: "manual",
  created_at: "2026-11-12T00:00:00Z",
  updated_at: "2026-11-12T00:00:00Z",
};

describe("Contacts page", () => {
  beforeEach(() => {
    vi.mocked(fetchContacts).mockResolvedValue([]);
    vi.mocked(createContact).mockResolvedValue(CONTACT);
    vi.mocked(fetchContact).mockResolvedValue({ ...CONTACT, interactions: [] });
    vi.mocked(draftOutreach).mockResolvedValue({
      kind: "intro",
      subject: "Intro — Talent",
      body: "Hi Ada, I would value a short conversation.",
      evidence_refs: [{ source: "contact", label: "contact", quote: "Ada" }],
      model: "assist",
      generated_at: "2026-11-12T00:00:00Z",
      draft_only: true,
    });
  });

  it("creates a contact and opens its detail", async () => {
    render(
      <MemoryRouter>
        <Contacts />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("contacts-page")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("contacts-new"));
    fireEvent.change(screen.getByTestId("contact-name"), {
      target: { value: "Ada Recruiter" },
    });
    fireEvent.change(screen.getByTestId("contact-email"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.click(screen.getByTestId("contact-save"));
    await waitFor(() =>
      expect(createContact).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Ada Recruiter", email: "ada@example.com" })
      )
    );
  });

  it("shows a grounded copy-only draft", async () => {
    vi.mocked(fetchContacts).mockResolvedValue([CONTACT]);
    render(
      <MemoryRouter>
        <Contacts />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("contact-c1"));
    expect(await screen.findByTestId("contact-detail")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("contact-draft"));
    const result = await screen.findByTestId("contact-draft-result");
    expect(result).toHaveTextContent("Intro — Talent");
    expect(result).toHaveTextContent("evidence");
    expect(draftOutreach).toHaveBeenCalledWith("c1", { kind: "intro" });
  });
});
