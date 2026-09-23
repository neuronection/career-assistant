# Chat and proposals

The assistant is grounded in your own catalog, profile and postings through
tool-calling. It can search jobs, pull job details, look up your matches and
answer questions — and it can help you *change* things, carefully.

Open it at `/chat`.

## Grounded answers

The chatbot searches jobs, pulls job details and looks up your matches through
tool-calling over your own data. Answers cite what they used, and long AI runs
show a progress trace you can read (the notes and timeline behind a reply).

## Proposals, never auto-apply

When you ask the assistant to change your profile, it does not just do it. It
proposes the change as a **proposal card**:

- The assistant **opens the item's full content before editing** (a
  server-enforced read-before-edit gate), so it edits what is actually there.
- Edits are **anchored and granular** — unique-anchor replacements, additive
  appends, per-item skill/achievement add/remove — never full-blob rewrites.
- Cards show a rendered **before/after preview** with the changed span
  highlighted.
- After you approve, you can **revert in one click**. Every change stays a
  signed review card.

Nothing is applied without your approval.

## Contextual "Ask AI" buttons

Throughout the UI, one-click **Ask AI** buttons open quick-assist actions
grounded in the surface you are on (a job, a posting, a CV section), so you
do not have to re-explain the context.

## The builder copilot

The main chat takes CVs as **per-message reference attachments** and hands off
to the builder copilot on build intent. The copilot:

- Applies templates, restyles tokens, edits sections and rewrites items as
  **validated operations** on one audited path shared with the UI buttons.
- **Sees the rendered output** — template previews and page screenshots are
  attached to its context, with a self-review critique round.
- Compiles an **automatic restorable snapshot per turn**, so every change is
  recoverable.

See [CV Studio overview](cv-studio.md) for the workspace it operates.

## Postings in chat

Every posting has a short **ref id** the chatbot understands. You can ask for
open roles by board and recency, open a posting by reference, and get "Open in
Explore" deep-links straight from chat replies.

## MCP access

Your career data is drivable from external MCP clients (Claude Desktop, IDE
agents):

- The tool registry's **read-scope tools** expose over Streamable HTTP at
  `/mcp` with a locally generated token (admin rotation), per-host rate
  limiting and read-only defaults.
- Admins can also register **external MCP servers** — tools are namespaced,
  disabled by default, enabled per tool, and every invocation is audited and
  budgeted.

## Bring your own LLM

Any OpenAI-compatible endpoint works (OpenAI, OpenRouter, Ollama, LM Studio).
Providers, models and per-task assignments live in **Settings → AI
Configuration** — stored in the database, encrypted at rest, with no AI
environment variables at all.

For offline development, the built-in **mock provider** is opt-in via
`MOCK_AI=1` (or `./scripts/run-dev.sh --mock-ai`); production refuses to serve
mock results regardless.

## Related

- [Interview prep](interviews.md) — practice from the chat
- [Onboarding and your profile](onboarding-and-profile.md) — the data proposals edit
- [Feature catalog](features.md#the-assistant-chat) — the full assistant surface
