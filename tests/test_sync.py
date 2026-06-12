"""Tests for run_sync orchestrator and TmsConnector protocol."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from testops_mirror.connectors.base import TmsConnector
from testops_mirror.gitstore import GitStore
from testops_mirror.models import TestCase
from testops_mirror.sync import run_sync

# ---------------------------------------------------------------------------
# Stub connector
# ---------------------------------------------------------------------------


def _make_case(tc_id: str, name: str) -> TestCase:
    return TestCase(
        id=tc_id,
        name=name,
        suite_path=("Payments",),
        tags=["api"],
    )


class StubConnector:
    """Minimal connector that yields a fixed list of test cases."""

    def __init__(self, cases: list[TestCase]) -> None:
        self._cases = cases

    def iter_test_cases(self, project_id: str) -> Iterator[TestCase]:
        yield from self._cases


class EmptyConnector:
    """Connector that yields nothing."""

    def iter_test_cases(self, project_id: str) -> Iterator[TestCase]:
        return iter([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> GitStore:
    return GitStore(tmp_path / "repo")


# ---------------------------------------------------------------------------
# TmsConnector protocol
# ---------------------------------------------------------------------------


def test_stub_satisfies_protocol() -> None:
    connector = StubConnector([])
    assert isinstance(connector, TmsConnector)


def test_object_missing_method_does_not_satisfy_protocol() -> None:
    class NotAConnector:
        pass

    assert not isinstance(NotAConnector(), TmsConnector)


# ---------------------------------------------------------------------------
# run_sync — dry_run
# ---------------------------------------------------------------------------


def test_dry_run_returns_changeset_no_sha(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = StubConnector([_make_case("1", "Pay invoice")])

    changes, sha = run_sync(connector, store, "42", dry_run=True)

    assert sha is None
    assert len(changes.added) + len(changes.updated) == 1


def test_dry_run_does_not_write_files(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    store = GitStore(repo_path)
    connector = StubConnector([_make_case("1", "Pay invoice")])

    run_sync(connector, store, "42", dry_run=True)

    md_files = list(repo_path.rglob("*.md"))
    assert md_files == [], "dry_run must not write any files"


# ---------------------------------------------------------------------------
# run_sync — apply (write changes)
# ---------------------------------------------------------------------------


def test_apply_creates_commit(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = StubConnector([_make_case("1", "Pay invoice")])

    _changes, sha = run_sync(connector, store, "42", dry_run=False)

    assert sha is not None
    assert len(sha) == 40


def test_apply_writes_markdown_file(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    store = GitStore(repo_path)
    connector = StubConnector([_make_case("10", "Refund request")])

    run_sync(connector, store, "1", dry_run=False)

    md_files = list(repo_path.rglob("*.md"))
    assert len(md_files) == 1
    assert "refund-request" in md_files[0].name


def test_apply_returns_changeset_with_upserted(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = StubConnector(
        [_make_case("1", "Pay invoice"), _make_case("2", "Cancel subscription")]
    )

    changes, _sha = run_sync(connector, store, "42")

    assert len(changes.added) == 2
    assert changes.empty is False


# ---------------------------------------------------------------------------
# run_sync — no changes (idempotent second run)
# ---------------------------------------------------------------------------


def test_no_changes_on_second_run(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = StubConnector([_make_case("1", "Pay invoice")])

    run_sync(connector, store, "42")
    changes, sha = run_sync(connector, store, "42")

    assert sha is None
    assert changes.empty is True


# ---------------------------------------------------------------------------
# run_sync — on_case callback
# ---------------------------------------------------------------------------


def test_on_case_called_for_each_case(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    cases = [_make_case("1", "Pay invoice"), _make_case("2", "Cancel subscription")]
    connector = StubConnector(cases)
    seen: list[TestCase] = []

    run_sync(connector, store, "42", on_case=seen.append)

    assert len(seen) == 2
    assert {c.id for c in seen} == {"1", "2"}


def test_on_case_none_does_not_raise(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = StubConnector([_make_case("1", "Pay invoice")])

    _changes, sha = run_sync(connector, store, "42", on_case=None)

    assert sha is not None


# ---------------------------------------------------------------------------
# run_sync — empty connector
# ---------------------------------------------------------------------------


def test_empty_connector_returns_empty_changeset(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    connector = EmptyConnector()

    changes, sha = run_sync(connector, store, "42")

    assert changes.empty is True
    assert sha is None
