"""Canonical TMS-agnostic data models.

These models are the single source of truth between connectors and the
serializer. No connector-specific fields belong here.
"""

from __future__ import annotations

from pydantic import BaseModel


class Step(BaseModel):
    name: str
    expected_result: str | None = None
    steps: list[Step] = []


# Required for Pydantic v2 self-referential model
Step.model_rebuild()


class Link(BaseModel):
    name: str | None = None
    url: str
    type: str | None = None  # "issue" | "tms" | ...


class TestCase(BaseModel):
    # pytest must not collect this as a test class
    __test__ = False

    id: str
    name: str
    description: str | None = None
    precondition: str | None = None
    expected_result: str | None = None
    status: str | None = None
    automated: bool = False
    tags: list[str] = []
    custom_fields: dict[str, list[str]] = {}
    links: list[Link] = []
    suite_path: tuple[str, ...] = ()
    steps: list[Step] = []
    source_url: str | None = None
    source_project: str | None = None
