from enum import StrEnum


class SourceKind(StrEnum):
    HN = "hn"
    REDDIT = "reddit"
    RSS = "rss"
    GITHUB = "github"
    SEARCH = "search"
    MANUAL_PASTE = "manual_paste"
    CSV_IMPORT = "csv_import"
    LINKEDIN_USER_CAPTURE = "linkedin_user_capture"


class PartyKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class LeadType(StrEnum):
    HIRING = "hiring"
    FREELANCE_GIG = "freelance_gig"
    INTERNSHIP = "internship"
    NOT_A_LEAD = "not_a_lead"


class LeadStatus(StrEnum):
    NEW = "new"
    QUALIFYING = "qualifying"
    QUALIFIED = "qualified"
    NEEDS_HUMAN = "needs_human"
    REJECTED = "rejected"
    CONTACTED = "contacted"


class AgentRole(StrEnum):
    ANALYST = "analyst"
    OUTREACH = "outreach"
    ADMIN = "admin"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"
    BUDGET_EXCEEDED = "budget_exceeded"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class FeedbackLabel(StrEnum):
    GOOD = "good"
    BAD = "bad"
