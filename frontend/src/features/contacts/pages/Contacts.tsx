import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Mail, Plus, Search, Trash2, UserRound } from "lucide-react";

import {
  Button,
  ConfirmationModal,
  EmptyState,
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
  Spinner,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  addContactInteraction,
  createContact,
  deleteContact,
  deleteContactInteraction,
  draftOutreach,
  fetchContact,
  fetchContacts,
  updateContact,
  type Contact,
  type ContactDetail,
  type ContactInput,
  type OutreachDraft,
} from "@/api/contacts";

const EMPTY: ContactInput = { name: "", org: "", role: "", email: "", notes: "" };
const DRAFT_KINDS = ["intro", "follow_up", "thank_you", "referral", "informational"] as const;

export function Contacts() {
  const { t, i18n } = useTranslation();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<ContactInput>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [logKind, setLogKind] = useState<string>("follow_up");
  const [draftKind, setDraftKind] = useState<string>("intro");
  const [draftResult, setDraftResult] = useState<OutreachDraft | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => {
      const id = ++requestId.current;
      setLoading(true);
      fetchContacts({ q: query.trim() || undefined })
        .then((rows) => {
          if (id !== requestId.current) return;
          setContacts(rows);
          setError("");
        })
        .catch((err) => {
          if (id === requestId.current) setError(apiDetail(err));
        })
        .finally(() => {
          if (id === requestId.current) setLoading(false);
        });
    }, 200);
    return () => clearTimeout(timer);
  }, [query, reloadKey]);

  const reload = () => setReloadKey((value) => value + 1);

  const openDetail = async (id: string) => {
    setError("");
    setDraftResult(null);
    try {
      setDetail(await fetchContact(id));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    setBusy(true);
    setError("");
    try {
      if (editingId) {
        await updateContact(editingId, draft);
        if (detail?.id === editingId) setDetail(await fetchContact(editingId));
      } else await createContact(draft);
      setFormOpen(false);
      setDraft(EMPTY);
      setEditingId(null);
      reload();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteContact(id);
      setDetail(null);
      reload();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const addInteraction = async (kind: string, channel: string) => {
    if (!detail) return;
    setBusy(true);
    try {
      await addContactInteraction(detail.id, {
        kind,
        channel,
        at: new Date().toISOString(),
        notes: "",
      });
      setDetail(await fetchContact(detail.id));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const removeInteraction = async (interactionId: string) => {
    if (!detail) return;
    setBusy(true);
    try {
      await deleteContactInteraction(detail.id, interactionId);
      setDetail(await fetchContact(detail.id));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const makeDraft = async () => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      setDraftResult(await draftOutreach(detail.id, { kind: draftKind }));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ca-workspace mx-auto max-w-5xl space-y-4" data-testid="contacts-page">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
          <UserRound className="size-5 text-[var(--as-accent)]" aria-hidden />
          {t("contacts.title")}
        </h1>
        <span className="text-sm text-[var(--as-muted-fg)]">
          {t("contacts.count", { count: contacts.length })}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <label className="relative">
            <Search className="pointer-events-none absolute left-2 top-2 size-3.5 text-[var(--as-muted-fg)]" aria-hidden />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("contacts.search")}
              aria-label={t("contacts.search")}
              className="w-48 rounded border border-[var(--as-border)] bg-[var(--as-surface)] py-1.5 pl-7 pr-2 text-sm"
              data-testid="contacts-search"
            />
          </label>
          <Button
            data-testid="contacts-new"
            onClick={() => {
              setEditingId(null);
              setDraft(EMPTY);
              setFormOpen(true);
            }}
          >
            <Plus className="mr-1 size-3.5" aria-hidden />
            {t("contacts.new")}
          </Button>
        </div>
      </div>

      {error !== "" && contacts.length > 0 && (
        <p role="alert" className="text-sm text-[var(--as-danger)]" data-testid="contacts-error">
          {error}
        </p>
      )}

      {loading && contacts.length === 0 ? (
        <div className="flex justify-center p-8" data-testid="contacts-loading">
          <Spinner />
        </div>
      ) : error !== "" && contacts.length === 0 ? (
        <div data-testid="contacts-error-state">
          <EmptyState
            title={t("contacts.errorTitle")}
            description={error}
            action={
              <Button variant="outline" onClick={reload}>
                {t("contacts.retry")}
              </Button>
            }
          />
        </div>
      ) : contacts.length === 0 ? (
        <EmptyState title={t("contacts.emptyTitle")} description={t("contacts.emptyBody")} />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2" data-testid="contacts-list">
          {contacts.map((contact) => (
            <button
              key={contact.id}
              type="button"
              onClick={() => void openDetail(contact.id)}
              className="rounded-[var(--as-radius-lg)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-left hover:border-[var(--as-accent)]"
              data-testid={`contact-${contact.id}`}
            >
              <p className="text-sm font-medium text-[var(--as-fg)]">{contact.name}</p>
              <p className="text-xs text-[var(--as-muted-fg)]">
                {[contact.role, contact.org].filter(Boolean).join(" · ") || t("contacts.noOrg")}
              </p>
              <p className="mt-1 text-[10px] text-[var(--as-muted-fg)]">
                {contact.last_contacted_at
                  ? t("contacts.lastContacted", {
                      date: new Date(contact.last_contacted_at).toLocaleDateString(
                        i18n.language
                      ),
                    })
                  : t("contacts.neverContacted")}
              </p>
            </button>
          ))}
        </div>
      )}

      <Modal open={formOpen} onOpenChange={setFormOpen}>
        <ModalContent data-testid="contact-form" aria-describedby={undefined}>
          <ModalHeader>
            <ModalTitle>{editingId ? t("contacts.edit") : t("contacts.new")}</ModalTitle>
          </ModalHeader>
          <div className="space-y-2">
            {([
              ["name", "contacts.name"],
              ["org", "contacts.org"],
              ["role", "contacts.role"],
              ["email", "contacts.email"],
              ["notes", "contacts.notes"],
            ] as const).map(([field, label]) => (
              <label key={field} className="block space-y-1 text-xs text-[var(--as-muted-fg)]">
                <span>{t(label)}</span>
                <input
                  value={String(draft[field] ?? "")}
                  onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                  className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm"
                  data-testid={`contact-${field}`}
                />
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setFormOpen(false)} disabled={busy}>
                {t("common.cancel")}
              </Button>
              <Button onClick={() => void save()} disabled={busy || !draft.name.trim()} data-testid="contact-save">
                {t("common.save")}
              </Button>
            </div>
          </div>
        </ModalContent>
      </Modal>

      <Modal open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <ModalContent size="xl" data-testid="contact-detail" aria-describedby={undefined}>
          {detail && (
            <>
              <ModalHeader>
                <ModalTitle>{detail.name}</ModalTitle>
              </ModalHeader>
              <div className="space-y-3">
                <p className="text-sm text-[var(--as-muted-fg)]">
                  {[detail.role, detail.org, detail.email].filter(Boolean).join(" · ")}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditingId(detail.id);
                      setDraft({
                        name: detail.name,
                        org: detail.org,
                        role: detail.role,
                        email: detail.email,
                        notes: detail.notes,
                      });
                      setFormOpen(true);
                    }}
                  >
                    {t("contacts.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setPendingDelete(detail.id)} data-testid="contact-delete">
                    <Trash2 className="mr-1 size-3.5" aria-hidden />
                    {t("common.delete")}
                  </Button>
                </div>

                <section className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("contacts.interactions")}
                  </h3>
                  {detail.interactions.length === 0 && (
                    <p className="text-xs text-[var(--as-muted-fg)]">{t("contacts.noInteractions")}</p>
                  )}
                  {detail.interactions.map((row) => (
                    <div key={row.id} className="flex items-start gap-2 rounded border border-[var(--as-border)] p-2 text-xs">
                      <div className="min-w-0 flex-1">
                        <p className="text-[var(--as-fg)]">
                          {t(`contacts.kind.${row.kind}`)} · {row.channel}
                        </p>
                        <p className="text-[var(--as-muted-fg)]">
                          {new Date(row.at).toLocaleString(i18n.language)}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-label={t("common.delete")}
                        onClick={() => void removeInteraction(row.id)}
                        className="text-[var(--as-muted-fg)] hover:text-[var(--as-danger)]"
                      >
                        <Trash2 className="size-3.5" aria-hidden />
                      </button>
                    </div>
                  ))}
                  <div className="flex flex-wrap items-center gap-1">
                    <select
                      value={logKind}
                      onChange={(event) => setLogKind(event.target.value)}
                      aria-label={t("contacts.logKindLabel")}
                      className="rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-xs"
                      data-testid="contact-log-kind"
                    >
                      {DRAFT_KINDS.map((kind) => (
                        <option key={kind} value={kind}>
                          {t(`contacts.draftKind.${kind}`)}
                        </option>
                      ))}
                    </select>
                    {(["email", "call", "meeting", "message"] as const).map((channel) => (
                      <Button
                        key={channel}
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void addInteraction(logKind, channel)}
                        data-testid={`contact-log-${channel}`}
                      >
                        {t("contacts.log", { channel: t(`contacts.channel.${channel}`) })}
                      </Button>
                    ))}
                  </div>
                </section>

                <section className="space-y-2 rounded border border-[var(--as-border)] p-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("contacts.draft")}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={draftKind}
                      onChange={(event) => setDraftKind(event.target.value)}
                      aria-label={t("contacts.draftKindLabel")}
                      className="rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-xs"
                    >
                      {DRAFT_KINDS.map((kind) => (
                        <option key={kind} value={kind}>
                          {t(`contacts.draftKind.${kind}`)}
                        </option>
                      ))}
                    </select>
                    <Button size="sm" onClick={() => void makeDraft()} disabled={busy} data-testid="contact-draft">
                      {t("contacts.draftCta")}
                    </Button>
                  </div>
                  {draftResult && (
                    <div className="space-y-2 text-sm" data-testid="contact-draft-result">
                      <p className="font-medium text-[var(--as-fg)]">{draftResult.subject}</p>
                      <p className="whitespace-pre-wrap text-[var(--as-muted-fg)]">{draftResult.body}</p>
                      <p className="text-[10px] text-[var(--as-muted-fg)]">
                        {t("contacts.evidence", { count: draftResult.evidence_refs.length })}
                      </p>
                      <ul className="list-disc space-y-0.5 pl-5 text-[10px] text-[var(--as-muted-fg)]">
                        {draftResult.evidence_refs.map((ref) => (
                          <li key={`${ref.source}-${ref.label}`}>
                            {ref.source}: {ref.label}
                            {ref.quote ? ` — ${ref.quote}` : ""}
                          </li>
                        ))}
                      </ul>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => void navigator.clipboard?.writeText(`${draftResult.subject}\n\n${draftResult.body}`)}
                        >
                          {t("contacts.copy")}
                        </Button>
                        {detail.email && (
                          <a
                            className="inline-flex items-center gap-1 rounded border border-[var(--as-border)] px-2 py-1 text-xs"
                            href={`mailto:${encodeURIComponent(detail.email)}?subject=${encodeURIComponent(draftResult.subject)}&body=${encodeURIComponent(draftResult.body)}`}
                          >
                            <Mail className="size-3.5" aria-hidden />
                            {t("contacts.mailto")}
                          </a>
                        )}
                      </div>
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
        </ModalContent>
      </Modal>

      <ConfirmationModal
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title={t("contacts.deleteTitle")}
        description={t("contacts.deleteConfirm")}
        confirmLabel={t("common.delete")}
        destructive
        busy={busy}
        onConfirm={() => {
          const id = pendingDelete;
          setPendingDelete(null);
          if (id) void remove(id);
        }}
      />
    </div>
  );
}
