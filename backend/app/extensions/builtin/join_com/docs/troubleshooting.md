# JOIN.com troubleshooting

**`422 pageSize invalid`.** The public API accepts page sizes from 1 to 5
only. Set the page size back to 5.

**`Entity not found`.** The numeric company id is wrong (the slug is not an
id). Open the company's JOIN careers page and read the id from its API
response, or use the company's JOIN account page.

**Salaries look 100× too small.** Salary amounts are minor units; if a
source was configured by hand with major units, remove and re-add it so the
connector normalizes the range.
