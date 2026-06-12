"""Base protocol for TMS connectors.

Any new connector must implement :class:`TmsConnector` — a single method
``iter_test_cases`` that yields canonical :class:`~testops_mirror.models.TestCase`
objects.  No connector-specific types should leak outside the connector module.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from testops_mirror.models import TestCase


@runtime_checkable
class TmsConnector(Protocol):
    """Structural protocol for TMS connectors.

    To add a new connector, implement this method and wire it up in the CLI.
    See CONTRIBUTING.md for details.
    """

    def iter_test_cases(self, project_id: str) -> Iterator[TestCase]:
        """Yield all test cases for *project_id* as canonical TestCase objects.

        Must raise:
        - :class:`~testops_mirror.exceptions.AuthError` on 401/403
        - :class:`~testops_mirror.exceptions.ConnectorError` on unrecoverable errors
        """
        ...
