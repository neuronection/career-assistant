# StepStone / Xing job alerts

StepStone and Xing do not publish anonymous job feeds; both give a
signed-in user an RSS URL for a saved search ("Jobagent" / job alert). This
connector consumes that RSS 2.0 feed and normalizes its items into the
postings pipeline.

The alert URL is personal and often carries a per-user token, so it is
declared as an `x-secret` slot: the value lives only in the source's sealed
secret store and never in `job_sources.config`. The connector reads it from
the injected secret slot at sync time.
