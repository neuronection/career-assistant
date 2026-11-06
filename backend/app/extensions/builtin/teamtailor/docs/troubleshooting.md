# Teamtailor troubleshooting

**Empty sync.** An unknown company subdomain answers `404`; a valid site
with no open roles returns an empty `items` list.

**Missing salary.** Only postings whose schema.org value declares a range
produce a structured salary; free-text amounts stay in the description.

**Old items keep returning.** The watermark is the oldest published item
date, so older postings are skipped after the first sync.
