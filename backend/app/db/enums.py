"""Database enumeration types."""

from enum import StrEnum


class SourceKind(StrEnum):
    HN = "hn"
    REDDIT = "reddit"
    MANUAL_PASTE = "manual_paste"
    CSV_IMPORT = "csv_import"
    USER_CAPTURE = "user_capture"


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


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class AuditOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING = "pending"
    EXECUTED = "executed"
    ERROR = "error"
