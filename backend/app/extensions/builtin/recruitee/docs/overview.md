# Recruitee careers feed

Recruitee hosts career sites at `<company>.recruitee.com` and exposes every
published offer at `/api/offers/` without authentication. Each offer carries
a slug, title, description, department, locations, remote/hybrid flags,
tags, salary range and the publish date.

Use this connector when the employer's careers page runs on Recruitee. The
feed is one request; the newest publish date becomes the watermark.
