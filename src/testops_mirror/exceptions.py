"""Custom exception hierarchy for testops-mirror.

All exceptions raised by connectors and core modules are subclasses of
TestopsMirrorError so callers can catch them with a single except clause.
"""


class TestopsMirrorError(Exception):
    """Base exception for all testops-mirror errors."""


class AuthError(TestopsMirrorError):
    """Authentication or authorisation failure (401/403)."""


class NotFoundError(TestopsMirrorError):
    """Requested resource does not exist (404)."""


class RateLimitError(TestopsMirrorError):
    """API rate limit exceeded (429)."""


class ConnectorError(TestopsMirrorError):
    """Generic connector-level error (5xx, network, parse)."""
