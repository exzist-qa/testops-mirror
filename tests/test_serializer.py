"""Tests for the serializer module.

Covers: determinism, front matter content, section rendering, nested steps,
relpath with and without suites, slugify edge cases, collision handling.
"""

from __future__ import annotations

import yaml

from testops_mirror.models import Link, Step, TestCase
from testops_mirror.serializer import case_relpath, serialize, slugify

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_front_matter(text: str) -> dict:  # type: ignore[type-arg]
    """Extract and parse YAML front matter from a rendered case."""
    assert text.startswith("---\n"), "Missing opening ---"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])  # type: ignore[no-any-return]


def _make_case(**kwargs) -> TestCase:  # type: ignore[type-arg]
    defaults = {"id": "1", "name": "Sample Case"}
    defaults.update(kwargs)
    return TestCase(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_serialize_is_deterministic():
    case = _make_case(
        id="42",
        name="Ship without cargo",
        status="Ready",
        tags=["api", "negative"],
        suite_path=("Shipments", "Negative"),
    )
    assert serialize(case) == serialize(case)


def test_serialize_determinism_on_repeated_calls():
    case = _make_case(
        id="10",
        name="Login",
        tags=["smoke", "auth"],
        custom_fields={"Suite": ["Auth"], "Priority": ["P0"]},
        links=[Link(name="BUG-1", url="https://tracker/BUG-1", type="issue")],
    )
    first = serialize(case)
    second = serialize(case)
    assert first == second


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def test_front_matter_contains_required_fields():
    case = _make_case(id="5", name="My Test")
    fm = _parse_front_matter(serialize(case))
    assert fm["id"] == "5"
    assert fm["name"] == "My Test"
    assert "automated" in fm


def test_front_matter_omits_none_fields():
    case = _make_case(id="1", name="Minimal")
    fm = _parse_front_matter(serialize(case))
    assert "description" not in fm
    assert "status" not in fm
    assert "tags" not in fm
    assert "custom_fields" not in fm
    assert "links" not in fm
    assert "source" not in fm


def test_tags_are_sorted():
    case = _make_case(tags=["zebra", "apple", "mango"])
    fm = _parse_front_matter(serialize(case))
    assert fm["tags"] == ["apple", "mango", "zebra"]


def test_custom_fields_are_sorted():
    case = _make_case(custom_fields={"Z": ["b", "a"], "A": ["x"]})
    fm = _parse_front_matter(serialize(case))
    keys = list(fm["custom_fields"].keys())
    assert keys == sorted(keys)
    assert fm["custom_fields"]["Z"] == ["a", "b"]


def test_source_url_in_front_matter():
    case = _make_case(source_url="https://tms.example.com/cases/1", source_project="42")
    fm = _parse_front_matter(serialize(case))
    assert fm["source"]["url"] == "https://tms.example.com/cases/1"
    assert fm["source"]["project"] == "42"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def test_description_section_rendered():
    case = _make_case(description="Some description text.")
    assert "Some description text." in serialize(case)


def test_precondition_section_rendered():
    case = _make_case(precondition="User must be logged in.")
    body = serialize(case)
    assert "## Preconditions" in body
    assert "User must be logged in." in body


def test_expected_result_section_rendered():
    case = _make_case(expected_result="Returns 200 OK.")
    body = serialize(case)
    assert "## Expected result" in body
    assert "Returns 200 OK." in body


def test_empty_sections_not_rendered():
    case = _make_case()
    body = serialize(case)
    assert "## Preconditions" not in body
    assert "## Steps" not in body
    assert "## Expected result" not in body


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def test_flat_steps_rendered():
    case = _make_case(steps=[Step(name="Open page"), Step(name="Click submit")])
    body = serialize(case)
    assert "1. Open page" in body
    assert "2. Click submit" in body


def test_step_expected_result_rendered():
    case = _make_case(steps=[Step(name="Send request", expected_result="200 OK")])
    body = serialize(case)
    assert "**Expected:** 200 OK" in body


def test_nested_steps_rendered():
    nested = Step(name="Check body", steps=[Step(name="Field error is present")])
    case = _make_case(steps=[Step(name="Send POST"), nested])
    body = serialize(case)
    assert "1. Send POST" in body
    assert "2. Check body" in body
    assert "    1. Field error is present" in body


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_cyrillic():
    result = slugify("Корабль без груза")
    assert result == "korabl-bez-gruza"


def test_slugify_special_chars():
    result = slugify("test!@#$%^&*()case")
    assert result == "test-case"


def test_slugify_max_length():
    long_name = "a" * 100
    result = slugify(long_name, max_len=60)
    assert len(result) <= 60


def test_slugify_empty_result_returns_case():
    assert slugify("!!!") == "case"
    assert slugify("") == "case"


def test_slugify_mixed():
    result = slugify("  --  Тест 123  --  ")
    assert "123" in result
    assert result == result.lower()


# ---------------------------------------------------------------------------
# case_relpath
# ---------------------------------------------------------------------------


def test_relpath_without_suite():
    case = _make_case(id="7", name="My Test")
    path = case_relpath(case)
    assert path == "TC-7-my-test.md"


def test_relpath_with_suite():
    case = _make_case(id="7", name="My Test", suite_path=("Shipments", "Negative"))
    path = case_relpath(case)
    assert path == "Shipments/Negative/TC-7-my-test.md"


def test_relpath_cyrillic_name():
    case = _make_case(id="8", name="Корабль без груза")
    path = case_relpath(case)
    assert path == "TC-8-korabl-bez-gruza.md"


def test_relpath_suite_with_forbidden_chars():
    case = _make_case(id="9", name="test", suite_path=("Suite/Sub:Dir",))
    path = case_relpath(case)
    assert "/" not in path.split("/")[0] or path.startswith("Suite_Sub_Dir")


# ---------------------------------------------------------------------------
# Collision handling
# ---------------------------------------------------------------------------


def test_relpath_no_collision_when_no_existing():
    case = _make_case(id="10", name="New Title")
    path = case_relpath(case, existing_paths=set())
    assert path == "TC-10-new-title.md"


def test_relpath_collision_appends_suffix():
    case = _make_case(id="10", name="New Title")
    existing = {"TC-10-old-title.md"}
    path = case_relpath(case, existing_paths=existing)
    assert path == "TC-10-new-title-2.md"


def test_relpath_collision_increments():
    case = _make_case(id="10", name="New Title")
    existing = {"TC-10-old-title.md", "TC-10-new-title-2.md"}
    path = case_relpath(case, existing_paths=existing)
    assert path == "TC-10-new-title-3.md"


def test_relpath_no_collision_when_same_slug_present():
    case = _make_case(id="10", name="New Title")
    existing = {"TC-10-new-title.md"}
    path = case_relpath(case, existing_paths=existing)
    assert path == "TC-10-new-title.md"
