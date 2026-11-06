# Recruitee troubleshooting

**Empty sync.** Recruitee answers `404` for an unknown company subdomain and
returns an empty `offers` list when nothing is published.

**Wrong language.** The connector prefers the English translation; offers
without one fall back to the first available locale.

**Old items keep returning.** The watermark is the oldest published offer
date, so a source that was paused re-imports only genuinely newer offers.
