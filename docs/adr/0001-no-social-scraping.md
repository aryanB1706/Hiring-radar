# 1. No Automated Scraping of Social Platforms (LinkedIn, Instagram, X)

Date: 2026-11-11

## Status
Accepted

## Context
Hiring Radar aggregates hiring and freelance gig opportunities. Platforms like LinkedIn, Instagram, and X (formerly Twitter) strictly prohibit automated scraping and unauthorized credentialed access in their terms of service, and official search APIs are either heavily restricted, expensive, or nonexistent for third-party automated monitoring.

## Decision
1. We will NOT implement or maintain automated scraping scripts, crawlers, or headless browser automation for LinkedIn, Instagram, or X.
2. We will NOT log in to any platform using automated bots or headless browsers to read content.
3. We will NOT ship even disabled or skeleton scrapers for these platforms.
4. For opportunities found on these platforms, Hiring Radar will strictly support **user-initiated captures** (i.e., when a user manually pastes a link, excerpt, or imports a structured file).
5. All automated collection will be strictly restricted to sanctioned public sources with clear public APIs or RSS feeds (e.g., Hacker News "Who is hiring" via Algolia API, Reddit via official PRAW API adhering to rate limits and User-Agent identification).

## Consequences
- Compliance with platform Terms of Service and legal standards.
- Zero risk of IP blocks, CAPTCHA hurdles, or account bans due to scraping.
- Cleaner, maintainable ingestion architecture without brittle DOM-scraping logic.
