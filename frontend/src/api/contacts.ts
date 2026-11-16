import { api } from "@/api/client";

export interface Contact {
  id: string;
  name: string;
  org: string;
  role: string;
  email: string;
  profile_url: string;
  notes: string;
  tags: string[];
  last_contacted_at: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface ContactInteraction {
  id: string;
  contact_id: string;
  application_id: string | null;
  kind: string;
  at: string;
  channel: string;
  notes: string;
  created_at: string;
}

export interface ContactDetail extends Contact {
  interactions: ContactInteraction[];
}

export interface ContactInput {
  name: string;
  org?: string;
  role?: string;
  email?: string;
  profile_url?: string;
  notes?: string;
  tags?: string[];
}

export interface OutreachDraft {
  kind: string;
  subject: string;
  body: string;
  evidence_refs: { source: string; label: string; quote: string }[];
  model: string;
  generated_at: string;
  draft_only: boolean;
}

export async function fetchContacts(params?: {
  q?: string;
  org?: string;
  application_id?: string;
}): Promise<Contact[]> {
  const { data } = await api.get<Contact[]>("/me/contacts", { params });
  return data;
}

export async function fetchContact(id: string): Promise<ContactDetail> {
  const { data } = await api.get<ContactDetail>(`/me/contacts/${id}`);
  return data;
}

export async function createContact(body: ContactInput): Promise<Contact> {
  const { data } = await api.post<Contact>("/me/contacts", body);
  return data;
}

export async function updateContact(
  id: string,
  body: Partial<ContactInput>,
): Promise<Contact> {
  const { data } = await api.patch<Contact>(`/me/contacts/${id}`, body);
  return data;
}

export async function deleteContact(id: string): Promise<void> {
  await api.delete(`/me/contacts/${id}`);
}

export async function addContactInteraction(
  id: string,
  body: {
    kind: string;
    at: string;
    channel: string;
    notes?: string;
    application_id?: string | null;
  },
): Promise<ContactInteraction> {
  const { data } = await api.post<ContactInteraction>(
    `/me/contacts/${id}/interactions`,
    body,
  );
  return data;
}

export async function deleteContactInteraction(
  id: string,
  interactionId: string,
): Promise<void> {
  await api.delete(`/me/contacts/${id}/interactions/${interactionId}`);
}

export async function draftOutreach(
  id: string,
  body: { kind: string; application_id?: string | null },
): Promise<OutreachDraft> {
  const { data } = await api.post<OutreachDraft>(`/me/contacts/${id}/draft`, body);
  return data;
}

export async function setApplicationContact(
  applicationId: string,
  contactId: string | null,
): Promise<void> {
  await api.post(`/me/applications/${applicationId}/contact`, {
    contact_id: contactId,
  });
}
