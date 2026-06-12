"""Orchestrator: connector -> serialize -> plan -> commit."""

from __future__ import annotations

import logging
from collections.abc import Callable

from testops_mirror.connectors.base import TmsConnector
from testops_mirror.gitstore import ChangeSet, GitStore
from testops_mirror.models import TestCase
from testops_mirror.serializer import case_relpath, serialize

logger = logging.getLogger(__name__)


def run_sync(
    connector: TmsConnector,
    store: GitStore,
    project_id: str,
    *,
    dry_run: bool = False,
    on_case: Callable[[TestCase], None] | None = None,
) -> tuple[ChangeSet, str | None]:
    """Pull all test cases and mirror them into the git store.

    Parameters
    ----------
    connector:
        Any object implementing the TmsConnector protocol.
    store:
        Initialised GitStore pointing at the target repository.
    project_id:
        TMS project identifier passed to the connector.
    dry_run:
        If True, compute the plan but do not write files or create commits.
    on_case:
        Optional callback invoked for each fetched TestCase (used by CLI for
        progress reporting).

    Returns
    -------
    (ChangeSet, sha | None)
        The planned change set and the commit SHA (None when dry_run or no changes).
    """
    desired: dict[str, str] = {}
    seen_paths: set[str] = set()

    for case in connector.iter_test_cases(project_id):
        if on_case is not None:
            on_case(case)
        relpath = case_relpath(case, existing_paths=seen_paths)
        seen_paths.add(relpath)
        desired[relpath] = serialize(case)
        logger.debug("Serialized %s -> %s", case.id, relpath)

    logger.info("Fetched %d test cases", len(desired))

    changes = store.plan(desired)

    if dry_run or changes.empty:
        return changes, None

    sha = store.apply(desired, changes)
    return changes, sha
