# Extension troubleshooting

Source and extension problems, decoded. Every error the app surfaces is
a typed code with a short detail — this table maps the ones you'll
actually see. (Deep diagnostics for extension authors live in the
[connector SDK docs](../dev/sdk/troubleshooting-and-faq.md).)

## A source sync failed

| You see | Why | What to do |
|---|---|---|
| `net-denied` on a **Remotive** source | Remotive's `robots.txt` disallows its API path; the app respects robots by default (see [the caveat](add-a-job-source.md#the-remotive-robots-caveat-honestly)) | An admin who accepts Remotive's API terms can lift the check for the deployment (`CAREER_CONNECTOR_RESPECT_ROBOTS`) |
| `net-denied` elsewhere | The address is blocked by the app's SSRF guard (private/internal ranges) or a redirect left the board's declared domains | Use the public API endpoint; report genuinely wrong verdicts — never widen scopes to work around it |
| `rate-limited` | The board throttled the fetch (429); the app already honored the retry hint | Wait for the next sync; lower the source's item cap if it recurs |
| `needs-secret` | The source needs a credential that isn't filled | Fill the credential slot in the source's config (Settings → Tools → Connectors) |
| `auth` | The board rejected the credential (401/403) | Check the token; re-save the slot (`***` keeps the stored value) |
| `provider` / `unreachable` | The board errored or the network failed | Usually transient — the next sync retries; check the board's status page if it persists |
| `protocol` | The feed's shape changed (the board moved something) | Wait for an app update — wire drift is fixed connector-side; report it |
| Source status **failing** with pins untouched | Repeated failed fetches mark the source; nothing you installed changed | Fix the underlying error; the source recovers on the next successful check |

## An imported extension

| You see | Why | What to do |
|---|---|---|
| Update badge **re-consent required** | A new version changed capabilities, config fields or code — no auto-apply exists | Review the diff shown and choose **Apply update (re-consent)**, or leave it |
| Source **degraded**, update shows **digest drift** | The same release now contains different bytes — the tampered-source signal | Verify the repository (was the tag force-moved?); only then re-consent. Ignore it and nothing changes |
| Instance **disabled** after a crash (self-disabled) | Sandboxed code that misbehaved is switched off by the app, with the reason shown — other sources keep running | Fix or trust the extension, then explicitly re-enable it; if it self-disables again, that's your answer |
| `needsConsent` from reconcile | The fleet list names an extension nobody has consented to on this instance | Consent once through the import dialog; the list then manages the pin |
| The MCP option is missing entirely | The external-script tier is off by default on the instance | An admin can enable it (`CAREER_CONNECTOR_PLUGINS_ALLOWLIST`) — it's an opt-in because its perimeter is wider |
| A mini-app page vanished | Its instance was disabled — the route only exists while enabled | Re-enable the instance, or remove it via tombstone |

## Chat tools

| You see | Why | What to do |
|---|---|---|
| "Needs your enablement" on a tool | State-changing tools are inert until you enable that specific one | Flip the toggle in the chat tools dialog if you want it |
| A confirmation card instead of an action | Destructive tools always card — grants cannot bypass this | Review the exact arguments and confirm, or dismiss |

## Related

- [Add a job source](add-a-job-source.md) and
  [Import extensions from git](import-extensions-from-git.md)
- [Postings and search](postings-and-search.md) — what lands after a
  healthy sync
- [Troubleshooting](troubleshooting.md) — app-wide problems
