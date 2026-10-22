# GitHub intake

The GitHub intake reads a public GitHub profile's repositories and turns
them into **draft** projects (with achievement highlights) in your profile.
It is review-first: nothing lands as active, and nothing is applied until
you review the drafts in your profile and activate them.

Only public, non-fork repositories are read. The intake uses the instance
GitHub token from **Settings → Tools → Connectors** when one is set (it
raises the API rate limit); public repositories work without a token.
