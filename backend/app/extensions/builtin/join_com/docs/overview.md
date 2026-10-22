# JOIN.com careers feed

JOIN.com publishes each company's open roles through a public JSON API at
`join.com/api/public/companies/<id>/jobs`. The feed carries the title,
category, city and country, workplace type, employment type and — when the
employer shows it — a salary range with a currency and frequency.

Use this connector when the employer's career page is hosted on JOIN.com.
The API identifies companies by a numeric id while the public page uses a
slug, so the source asks for both: the id selects the feed, the slug builds
the posting URL (`join.com/companies/<slug>/<idParam>`).
