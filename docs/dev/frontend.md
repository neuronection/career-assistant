# Frontend

The frontend is a React 18 + Vite + TypeScript (strict) SPA with Tailwind and
Zustand, using `@neuronection/assistant-ui` as its shared UI library. It talks
to the backend through a thin axios client and renders a long-lived workspace
app rather than a set of pages.

## Layout

```
frontend/src/
├── App.tsx          # BrowserRouter route table (the whole app's map)
├── main.tsx         # entry: i18n init, CSS import order, RenderBeacon
├── pages/           # one component per route (settings/ for admin pages)
├── components/      # feature components (catalog, chat, cv, profile, …)
├── components/ui/   # assistant-ui re-export shims — never local implementations
├── stores/          # Zustand stores
├── api/             # one module per backend area + client.ts (axios) + chatStream.ts
├── lib/             # helpers (i18n, slug, entityLinks, fitDimensions, …)
├── config/          # nav.ts, settingsNav.ts, onboardingPaths.ts, profileScopes.ts
├── styles/motion.css
├── theme.css        # app identity overrides (--as-* tokens)
└── locales/         # i18n resources
```

## Routing

`App.tsx` is the route table. Everything is wrapped in `ProtectedRoute` →
`Layout`. Top-level areas:

| Route | Surface |
|---|---|
| `/` | Dashboard |
| `/chat` | The assistant |
| `/onboarding`, `/onboarding/express` | Wizard + express start |
| `/catalog`, `/catalog/graph`, `/catalog/generate`, `/jobs/:code` | Catalog, graph, AI generation, job detail |
| `/rankings`, `/compare` | Rankings + compare tray |
| `/postings`, `/postings/search` | Postings feed + Explore |
| `/autopilot`, `/interviews`, `/growth` | Autopilot, interview prep, growth |
| `/profile`, `/profile/experience`, `/profile/education`, `/profile/import`, `/profile/assessment` | Profile + workspaces |
| `/catalog/universities`, `/catalog/universities/:id` | University intake |
| `/cv`, `/cv/synth`, `/cv/:id`, `/cv/templates/:id` | CV Studio, variant library, builder, template editor |
| `/settings/*` | AI, taxonomy, users, scheduler, notifications, audit |

`config/nav.ts` and `config/settingsNav.ts` define the sidebar and settings
navigation — update them with the routes.

## State

Zustand stores in `stores/`:

| Store | Responsibility |
|---|---|
| `authStore` | Session/user |
| `bootstrapStore` | App bootstrap data |
| `catalogStore` | Catalog tree + graph state |
| `chatStore` | Chat sessions, streaming, turns |
| `compareStore` | The compare tray |
| `cvBuilderLinkStore` | Cross-surface CV live-sync (plan 104) |
| `profileStore`, `profileProposalsStore` | Profile + pending proposal cards |
| `templatePreviewsStore` | Template gallery previews |
| `toastStore` | Notices |

Page visibility lives outside the stores: `config/features.json` is the
feature-state table (`on`/`beta`/`hidden`) that the sidebar, the beta
banner, the demo tour and the docs-claims test all read. There is no dev
mode and no hidden unlock — see
[UI conventions → feature state](ui-conventions.md#2d-feature-state-beta-affordance).

## API client

- `api/client.ts` is the axios instance (`baseURL: "/api/v1"`) plus
  `apiDetail(error)` for extracting a human message.
- One module per area (`api/cv.ts`, `api/postings.ts`, …). Streaming has its
  own transport: `api/chatStream.ts` (SSE) and `api/notificationStream.ts`.
- **Previews are fetched authenticated and rendered in a sandboxed iframe**
  (`srcDoc` + `sandbox=""`) — iframes cannot carry the Bearer token, so the
  app fetches the HTML itself. Never weaken the CSP.

## The shared UI library

`components/ui/*` are **re-export shims** of `@neuronection/assistant-ui` — the
app is fully adopted. Never reintroduce a local implementation; extend the
library instead (see the `ca-assistant-ui` and `family-ui` skills). Styling
goes through `--as-*` tokens and `data-as-*` attributes; app identity
overrides live in `theme.css`.

**CSS import order is sacred** (`main.tsx`):

```
assistant-ui/styles.css → index.css → styles/motion.css → theme.css
```

Never reorder. Motion lives only in `styles/motion.css`.

## Internationalization

`lib/i18n.ts` initializes i18next with the three shipped locales (`en`
source, `de`, `el`); resources live in `locales/`. The active locale comes
from the caller's `users.locale` (via `/me/bootstrap`), falls back to the
instance default (`app_settings` `i18n.default_locale`), then `en`, and
sets `<html lang>`; changes apply without a reload. Number, date and
currency formatting goes through `lib/format.ts` so `Intl` follows the same
locale.

Two gates keep coverage measurable:

- **reverse lint** (`reverse-lint.test.ts`) — raw user-facing English in
  `src/pages` and `src/components` fails the suite. The allowlist is
  brands and technical tokens only; CV block `props` defaults are document
  content and therefore exempt.
- **catalog audit** (`i18n-audit.test.ts`) — every static `t()` key must
  exist in `en.json`, and every catalog key must be referenced from app
  source (dynamic `t(\`ns.${value}\`)` prefixes count).

`scripts/translations/check_translations.py` (no flags) is the CI
completeness gate for `de`/`el`; it fails on missing or extra keys.
Catalog entity labels are **not** translated in JSX: they use review-first
`label_overrides` rows resolved server-side (approved → base → key).

## Conventions

Read [ui-conventions.md](ui-conventions.md) **before building or restyling any
page** — the workspace pattern, shared `formPrimitives` controls, card
pickers, motion, drag feedback and the testability contract. The reference
implementation is CV Studio.

## Related

- [UI conventions](ui-conventions.md)
- [API](api.md) — the endpoints the client calls
- [Testing](testing.md) — frontend test setup and mocking rules
