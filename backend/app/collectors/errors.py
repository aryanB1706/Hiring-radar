class CollectorError(Exception):
    """Base class for collector problems."""


class DisabledSourceError(CollectorError):
    """The adapter exists but is disabled by policy (platform terms)."""


class AdapterConfigError(CollectorError):
    """The adapter cannot run as configured (missing credentials, no feeds, ...)."""


class RobotsDisallowedError(CollectorError):
    """robots.txt forbids fetching this URL for our user agent."""


class SourceNotEnabledError(CollectorError):
    """The source row exists but is switched off in the database."""
