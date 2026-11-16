# Contacts and outreach

Career Assistant keeps the people around your applications in one flat,
user-owned list. A contact is a person — recruiter, hiring manager,
referrer, alum — not a pipeline stage and not an enriched profile.

## The contacts page

`/contacts` lists your contacts with their organisation, role and last
interaction. Create one manually or link it from an application; an
application can point at exactly one contact and a contact can point at
many applications. Deleting a contact clears the application link but never
deletes the application.

## The interaction log

Each contact has a flat log of moments: an intro, follow-up, thank-you,
referral or informational conversation, logged as email, call, meeting or
message. `last_contacted_at` is derived from the newest log entry; the log
schedules nothing. Application follow-ups stay on the application's own
`next_followup_at` cadence — this page never creates a second one.

## Drafts — copy only

**Draft message** asks the assistant for one short intro, follow-up,
thank-you, referral or informational message, grounded in the contact,
the linked application, the posting and your profile. The result lists
its evidence refs; it is a draft only. Copy it or open your mail app with
`mailto:` — Career Assistant never sends the message, never scrapes a
mailbox and never enriches a contact from an external directory. When you
request a draft, the contact name/role/org/notes and the linked
application/posting context are sent to your configured AI provider; that
is AI processing, not sending the message.

## Privacy

Contacts are third-party personal data. The records stay in your instance,
are included in your account export, and are deleted with your account (or
one contact at a time); only a draft request sends the selected facts to
your configured AI provider. Do not paste sensitive third-party notes you would
not want in your own export.
