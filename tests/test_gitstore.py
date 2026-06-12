"""Tests for the GitStore module.

All tests use real git repositories created in pytest's tmp_path — no mocks.
"""

from __future__ import annotations

from pathlib import Path

from git import Repo

from testops_mirror.gitstore import ChangeSet, GitStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _commit_count(repo_path: Path) -> int:
    repo = Repo(repo_path)
    try:
        return sum(1 for _ in repo.iter_commits())
    except Exception:
        return 0


def _make_store(tmp_path: Path) -> GitStore:
    return GitStore(tmp_path / "repo")


# ---------------------------------------------------------------------------
# ChangeSet
# ---------------------------------------------------------------------------


def test_changeset_empty_when_no_lists():
    assert ChangeSet().empty


def test_changeset_not_empty_with_added():
    assert not ChangeSet(added=["a.md"]).empty


def test_changeset_summary_all():
    cs = ChangeSet(added=["a"], updated=["b", "c"], deleted=["d"])
    assert "1 added" in cs.summary()
    assert "2 updated" in cs.summary()
    assert "1 deleted" in cs.summary()


def test_changeset_summary_empty():
    assert ChangeSet().summary() == "no changes"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_gitstore_inits_new_repo(tmp_path: Path):
    GitStore(tmp_path / "new_repo")
    assert (tmp_path / "new_repo" / ".git").exists()


def test_gitstore_opens_existing_repo(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    Repo.init(repo_dir)
    store = GitStore(repo_dir)
    assert store._root == repo_dir


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def test_plan_all_added_on_empty_repo(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "content A", "TC-2-bar.md": "content B"}
    cs = store.plan(desired)
    assert sorted(cs.added) == ["TC-1-foo.md", "TC-2-bar.md"]
    assert cs.updated == []
    assert cs.deleted == []


def test_plan_detects_update(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "v1"}
    store.apply(desired, store.plan(desired))

    desired2 = {"TC-1-foo.md": "v2"}
    cs = store.plan(desired2)
    assert cs.updated == ["TC-1-foo.md"]
    assert cs.added == []
    assert cs.deleted == []


def test_plan_detects_delete(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "v1", "TC-2-bar.md": "v2"}
    store.apply(desired, store.plan(desired))

    cs = store.plan({"TC-1-foo.md": "v1"})
    assert cs.deleted == ["TC-2-bar.md"]


# ---------------------------------------------------------------------------
# Apply — first sync
# ---------------------------------------------------------------------------


def test_first_sync_creates_commit(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "hello"}
    changes = store.plan(desired)
    sha = store.apply(desired, changes)

    assert sha is not None
    assert _commit_count(store._root) == 1


def test_first_sync_writes_files(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "hello world"}
    store.apply(desired, store.plan(desired))

    assert (store.cases_dir / "TC-1-foo.md").read_text() == "hello world"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_second_sync_no_changes_returns_none(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "hello"}
    store.apply(desired, store.plan(desired))

    sha2 = store.apply(desired, store.plan(desired))
    assert sha2 is None


def test_second_sync_no_changes_no_new_commit(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "hello"}
    store.apply(desired, store.plan(desired))
    before = _commit_count(store._root)

    store.apply(desired, store.plan(desired))
    assert _commit_count(store._root) == before


# ---------------------------------------------------------------------------
# Update + delete in one sync
# ---------------------------------------------------------------------------


def test_update_and_delete_single_commit(tmp_path: Path):
    store = _make_store(tmp_path)
    initial = {
        "TC-1-foo.md": "old content",
        "TC-2-bar.md": "to be deleted",
    }
    store.apply(initial, store.plan(initial))

    desired = {"TC-1-foo.md": "new content"}
    cs = store.plan(desired)
    sha = store.apply(desired, cs)

    assert sha is not None
    assert _commit_count(store._root) == 2
    assert not (store.cases_dir / "TC-2-bar.md").exists()
    assert (store.cases_dir / "TC-1-foo.md").read_text() == "new content"


# ---------------------------------------------------------------------------
# Empty directory pruning
# ---------------------------------------------------------------------------


def test_empty_dirs_pruned_after_delete(tmp_path: Path):
    store = _make_store(tmp_path)
    initial = {"Suite/Sub/TC-1-foo.md": "content"}
    store.apply(initial, store.plan(initial))

    desired: dict[str, str] = {}
    store.apply(desired, store.plan(desired))

    assert not (store.cases_dir / "Suite").exists()


def test_non_empty_dir_not_pruned(tmp_path: Path):
    store = _make_store(tmp_path)
    initial = {
        "Suite/TC-1-foo.md": "content A",
        "Suite/TC-2-bar.md": "content B",
    }
    store.apply(initial, store.plan(initial))

    desired = {"Suite/TC-1-foo.md": "content A"}
    store.apply(desired, store.plan(desired))

    assert (store.cases_dir / "Suite").exists()
    assert not (store.cases_dir / "Suite" / "TC-2-bar.md").exists()


# ---------------------------------------------------------------------------
# Rename = delete + add
# ---------------------------------------------------------------------------


def test_rename_is_delete_and_add(tmp_path: Path):
    store = _make_store(tmp_path)
    initial = {"TC-1-old-title.md": "content"}
    store.apply(initial, store.plan(initial))

    desired = {"TC-1-new-title.md": "content"}
    cs = store.plan(desired)
    assert cs.deleted == ["TC-1-old-title.md"]
    assert cs.added == ["TC-1-new-title.md"]

    store.apply(desired, cs)
    assert not (store.cases_dir / "TC-1-old-title.md").exists()
    assert (store.cases_dir / "TC-1-new-title.md").exists()


# ---------------------------------------------------------------------------
# Custom commit message
# ---------------------------------------------------------------------------


def test_custom_commit_message(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "x"}
    store.apply(desired, store.plan(desired), message="feat: initial mirror")

    repo = Repo(store._root)
    assert repo.head.commit.message == "feat: initial mirror"


def test_default_commit_message_contains_summary(tmp_path: Path):
    store = _make_store(tmp_path)
    desired = {"TC-1-foo.md": "x"}
    store.apply(desired, store.plan(desired))

    repo = Repo(store._root)
    msg = repo.head.commit.message
    assert "sync:" in msg
    assert "added" in msg
