"""Git-backed storage for mirrored test cases.

All test-case files live under the ``cases/`` subdirectory of the managed
repository.  The store is intentionally TMS-agnostic: it operates on
(relpath -> content) mappings produced by the serializer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from git import Actor, InvalidGitRepositoryError, Repo

logger = logging.getLogger(__name__)

CASES_DIR = "cases"
DEFAULT_AUTHOR_NAME = "testops-mirror"
DEFAULT_AUTHOR_EMAIL = "testops-mirror@localhost"


@dataclass
class ChangeSet:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.updated or self.deleted)

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.updated:
            parts.append(f"{len(self.updated)} updated")
        if self.deleted:
            parts.append(f"{len(self.deleted)} deleted")
        return ", ".join(parts) if parts else "no changes"


class GitStore:
    """Manage a ``cases/`` directory inside a Git repository."""

    def __init__(
        self,
        repo_path: str | Path,
        author_name: str = DEFAULT_AUTHOR_NAME,
        author_email: str = DEFAULT_AUTHOR_EMAIL,
    ) -> None:
        self._root = Path(repo_path)
        self._author = Actor(author_name, author_email)
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            self._repo = Repo(self._root)
        except InvalidGitRepositoryError:
            self._repo = Repo.init(self._root)
            logger.info("Initialised new git repository at %s", self._root)

    @property
    def cases_dir(self) -> Path:
        return self._root / CASES_DIR

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self, desired: dict[str, str]) -> ChangeSet:
        """Compare *desired* (relpath -> content) against the working tree.

        Returns a :class:`ChangeSet` describing what needs to change.
        All lists in the result are sorted for deterministic output.
        """
        existing = self._read_existing()

        desired_keys = set(desired)
        existing_keys = set(existing)

        added = sorted(desired_keys - existing_keys)
        deleted = sorted(existing_keys - desired_keys)
        updated = sorted(k for k in desired_keys & existing_keys if desired[k] != existing[k])

        return ChangeSet(added=added, updated=updated, deleted=deleted)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply(
        self,
        desired: dict[str, str],
        changes: ChangeSet,
        message: str | None = None,
    ) -> str | None:
        """Write/delete files according to *changes* and create a git commit.

        Returns the commit SHA, or ``None`` if *changes* is empty.
        """
        if changes.empty:
            return None

        for relpath in changes.added + changes.updated:
            abs_path = self.cases_dir / relpath
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(desired[relpath], encoding="utf-8")

        for relpath in changes.deleted:
            abs_path = self.cases_dir / relpath
            if abs_path.exists():
                abs_path.unlink()

        self._prune_empty_dirs()

        self._repo.git.add(str(self.cases_dir))

        if message is None:
            ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
            message = f"sync: {changes.summary()} ({ts})"

        commit = self._repo.index.commit(
            message,
            author=self._author,
            committer=self._author,
        )
        logger.info("Created commit %s: %s", commit.hexsha[:8], message)
        return str(commit.hexsha)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_existing(self) -> dict[str, str]:
        """Return all *.md files under cases/ as {relpath: content}."""
        if not self.cases_dir.exists():
            return {}
        result: dict[str, str] = {}
        for md_file in self.cases_dir.rglob("*.md"):
            relpath = str(md_file.relative_to(self.cases_dir))
            result[relpath] = md_file.read_text(encoding="utf-8")
        return result

    def _prune_empty_dirs(self) -> None:
        """Remove empty subdirectories under cases/ (bottom-up)."""
        if not self.cases_dir.exists():
            return
        for dirpath in sorted(self.cases_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and dirpath != self.cases_dir:
                try:
                    dirpath.rmdir()
                except OSError:
                    pass
