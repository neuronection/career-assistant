# Teamtailor careers feed

Teamtailor career sites publish a JSON Feed 1.1 document at
`<company>.teamtailor.com/jobs.json`. Each item carries the title, URL,
publish date and an embedded schema.org `JobPosting` with the description,
location, employment type and salary — no key or token is needed.

Use this connector when the employer's careers page runs on Teamtailor. The
newest `date_published` becomes the watermark.
