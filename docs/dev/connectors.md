# Connector SDK

Posting sources are a **registry extension point** — the only way to add one.
Connectors are pure normalizers: `fetch(config, state) -> ConnectorResult`
with no DB and no AI access. Everything downstream (mapping, fit, feed,
alerts) is connector-agnostic.

## The contract

`app/connectors/base.py` defines the whole surface:

- **`RawPosting`** — the only type a connector may emit. It is normalized and
  **pre-taxonomy**: `skills_raw` are free-text mentions that core maps to the
  skills ontology. It carries title, org, location, url, dates, salary,
  seniority, employment/contract type, onsite policy, work hours, travel,
  education and an arbitrary `raw` bag.
- **`ConnectorResult`** — `postings`, `next_state` (the incremental cursor)
  and `partial_errors` (non-fatal problems).
- **`ConnectorCapabilities`** — network scopes, whether credentials are
  required, incremental support, `max_requests_per_minute` and whether URL
  fetching is allowed.
- **`PostingConnector`** — the protocol: `key`, `title`, `docs_url`,
  `capabilities`, `fixture_payload`, `config_model()`, `fetch(...)` and
  `validate_config(...)`.

### Transport and politeness

Connectors **never open sockets themselves**. The runtime injects an
`HttpTransport` (a polite GET returning status/body/etag/last-modified), so
isolation, conditional GET, per-source caps and rate limiting stay in one
place. For URL kinds, `robots.txt` is respected. Legal and operational
constraints are part of the contract: declare your rate limit; the runtime
enforces it.

## Built-in engines

`app/connectors/builtin/__init__.py` ships first-party connectors:

| Key | Engine |
|---|---|
| `ats_api` | Public applicant-tracking-system job APIs |
| `jsonld` | `schema.org/JobPosting` structured data |
| `rss` | Job feeds |
| `csv` | Exported spreadsheets |
| `manual_url` | A single posting you point at |

## The plugin registry

`app/connectors/registry.py`:

- Built-ins auto-register at import.
- Third-party plugins arrive via the **entry-point group
  `career_assistant.connectors`** and are **admin-opt-in** via
  `CONNECTOR_PLUGINS_ALLOWLIST`.
- `register_connector`, `get_connector`, `list_connectors` are the API;
  `reset_registry` exists for tests.

A plugin that is not allowlisted is simply not registered.

## Writing a connector

1. Subclass `PostingConnector` with a unique `key`.
2. Define `config_model()` (a pydantic model) and return validated JSONB from
   `validate_config`.
3. Implement `fetch(config, state, *, transport)` to emit `RawPosting`s and
   update `next_state`.
4. Provide a `fixture_payload` so the contract tests can run offline.
5. Register it (built-in) or ship it as an entry point (plugin).

## Testing

`app/connectors/testing.py` provides `ConnectorContractTests` — a reusable
contract suite every connector should pass (normalization, idempotency,
`next_state` round-trips, partial errors). Run it against your
`fixture_payload` so connector tests never hit the network.

## Related

- [Data model](data-model.md) — `job_sources`, `job_postings`
- [AI layer](ai-layer.md) — the posting extraction pass that runs after ingest
- [Adding features](adding-features.md#add-a-connector) — the recipe
