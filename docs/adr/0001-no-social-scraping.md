# 0001. No scraping of LinkedIn, Instagram or X

Status: accepted

## Context
The people we serve find leads on LinkedIn, Instagram and X. Those platforms' terms forbid automated
collection and logging in with a bot account to read content, and their official APIs do not offer
post search for this purpose. Scraping them would risk account bans, legal exposure and brittle code.

## Decision
- We do not scrape these platforms and we never log in to a platform to read content.
- We collect only from sources that allow it: Hacker News (Algolia API), Reddit (official API via
  PRAW), RSS/Atom feeds and other public job boards (robots.txt respected, rate limited, identified
  by a real User-Agent).
- For LinkedIn, Instagram and X we support user-initiated capture only: the user pastes a link and
  text (`POST /api/captures`) or imports a CSV (`POST /api/captures/csv`). A future browser
  extension would also be triggered by the user, on a page they are viewing.
- `LinkedInAdapter` and `InstagramAdapter` exist as skeletons for the `SourceAdapter` interface.
  They are disabled and cannot be enabled: `fetch()` raises `DisabledSourceError` pointing here.

## Consequences
- Smaller coverage: leads that live only on those platforms arrive only when a person adds them.
- No ban risk for us or for users, and no dependence on scraper upkeep.
- A reviewer can see the policy in code (the disabled adapters and the tests that enforce them), not
  only in prose.
- Revisiting this needs a new ADR, for example if a platform offers a permitted API.
