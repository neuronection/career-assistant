# First-run AI setup

Career Assistant's AI features (matching, CV generation, parsing, chat and
Autopilot) run on a provider you connect. On a fresh install nothing is
configured, so the app opens a setup step instead of showing features that
would fail — and every surface that needs a provider keeps offering the way
back to it until one is configured.

## What the setup step does

`/onboarding/setup` is one wizard over the same AI settings the settings page
exposes:

1. **Connect a provider** — pick a preset (OpenAI, Gemini, OpenRouter,
   TypeSafe, Groq, Mistral, DeepSeek, Ollama or a manual/custom endpoint) and
   paste the key. Local presets need no key. The guided form validates the
   key against the provider before anything is saved.
2. **Choose defaults** — pick which curated models to register and which
   empty capability defaults they fill: **Text** (the default that turns AI
   on), **Vision**, **Transcription**, **Embeddings** where the preset
   offers one, and the single **Decision** default. Nothing existing is
   ever removed. The wizard assigns defaults only — it never asks a
   per-task question.
3. **Test the connection** — a tiny completion round-trips through the new
   provider. Failures are explained by cause (rejected key, no credit,
   rate-limited new key, unavailable region, timeout, local server not
   running) rather than by a raw error string.
4. **Continue to task assignments** — the finish action opens the Tasks tab
   for the same scope. Defaults are what every task falls back to;
   per-task overrides (specialist tasks and decision kinds) sit under
   **Advanced — per-task overrides**, collapsed until you need them. If no
   default could be set, the step asks for at least a chat model and offers
   **Open models**; you can finish later.

The connection is stored in the database, encrypted, and there are
deliberately no AI environment variables.

## Skipping

**Skip for now** records the choice on your profile and takes you to the
regular onboarding paths. You are never asked twice, but the setup prompt
stays on chat, the CV builder's AI actions, generate-with-AI and Autopilot
until a provider is configured — and `Settings → My AI Configuration` always
works as the manual route. The wizard keeps its scope picker: an admin may
create an instance provider or a personal one. After setup, the **Settings**
link opens the surface for the provider you created — My AI Configuration
for a personal provider, Instance AI Configuration for an instance provider.

On the desktop app the tray menu carries **Configure AI provider** as the
same entry point, so the window can stay closed.

## Seeing the state of your AI setup

- The setup prompt appears on every surface that needs a provider and
  disappears the moment a chat default resolves.
- A **Mock provider active — dev only** chip sits in the app header whenever
  the built-in deterministic mock is serving your calls. The mock is opt-in
  in development (`./scripts/run-dev.sh --mock-ai` or `CAREER_MOCK_AI=1`) and
  can never serve production.
- Failures are typed: an unconfigured instance, an exhausted token budget and
  a rate limit each get their own explanation, with the settings affordance
  on the unconfigured case.

## Related

- [Settings reference](settings.md) — the AI Configuration tabs in detail.
- [Getting started](getting-started.md) — install and first steps.
- [Desktop app](desktop-app.md) — tray behaviour and first launch.
