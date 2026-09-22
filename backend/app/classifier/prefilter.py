"""Cheap checks that skip obvious noise before any LLM call.

Deliberately conservative: a missed lead costs more than an extra LLM call, so a post is only
skipped when it is clearly not worth classifying.
"""

import re
from dataclasses import dataclass

MIN_CHARS = 12

# If NONE of these appear, the post has nothing to do with work. Broad on purpose.
_WORK_WORDS = re.compile(
    r"hir(e|ing)|recruit|looking\s+for|seeking|wanted|need(ed|s)?\b|require[sd]?\b|vacanc|"
    r"openings?\b|position|\brole\b|\bjob|career|intern|freelanc|contract|\bgig\b|apply|"
    r"opportunit|developer|engineer|\bdev\b|programmer|designer|analyst|scientist|"
    r"architect|consultant|\bteam\b|join\b|remote|onsite|on-site|salary|stipend|ctc|"
    r"\bpay(ing)?\b|budget|walk-?in|referral",
    re.IGNORECASE,
)

# Clear spam that is never a lead for us.
_SPAM = re.compile(
    r"casino|forex\s+signals?|crypto\s+airdrop|airdrop\s+claim|viagra|onlyfans|"
    r"seo\s+backlinks?|buy\s+followers|adult\s+content",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrefilterDecision:
    skip: bool
    reason: str | None = None


def prefilter(text: str) -> PrefilterDecision:
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return PrefilterDecision(True, "too_short")
    if _SPAM.search(stripped):
        return PrefilterDecision(True, "spam_pattern")
    if not _WORK_WORDS.search(stripped):
        return PrefilterDecision(True, "no_work_keywords")
    return PrefilterDecision(False)
