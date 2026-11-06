# Workable careers feed

Workable hosts career sites at `apply.workable.com/<account>` and exposes
every published job through its public widget API
(`/api/v1/widget/accounts/<account>`) without authentication. Each job
carries a shortcode, title, department, city/state/country, a remote flag,
the employment type and the publish date; the account payload carries the
company's display name, which becomes the posting's organization.

Use this connector when the employer's careers page runs on Workable — the
default for many Greek product companies and startups. The feed is one
request; the newest publish date becomes the watermark.
