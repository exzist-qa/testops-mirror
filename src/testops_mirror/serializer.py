"""Serialize TestCase instances to Markdown files with YAML front matter.

Invariants enforced here:
- Determinism: identical input always produces identical bytes.
- Stable file names: TC-{id}-{slug}.md, slug is cosmetic only.
- Collision handling: if a different slug exists for the same ID, append -2, -3, ...
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

import yaml

from testops_mirror.models import Step, TestCase

# Characters illegal in directory names on Windows/Linux/macOS
_DIR_FORBIDDEN = re.compile(r'[/\\:*?"<>|]')

# Transliteration table for common Cyrillic characters
_CYRILLIC: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "j",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def slugify(text: str, max_len: int = 60) -> str:
    """Convert arbitrary text to a URL-safe slug.

    Transliterates Cyrillic, lowercases, strips everything outside [a-z0-9-],
    collapses hyphens, trims to *max_len* characters.  Returns ``"case"`` if
    the result would otherwise be empty.
    """
    result = text.lower()

    # Transliterate Cyrillic
    result = "".join(_CYRILLIC.get(ch, ch) for ch in result)

    # Decompose accented characters and drop combining marks
    result = unicodedata.normalize("NFKD", result)
    result = "".join(ch for ch in result if not unicodedata.combining(ch))

    # Replace non-alphanumeric with hyphens
    result = re.sub(r"[^a-z0-9]+", "-", result)

    # Collapse and strip leading/trailing hyphens
    result = result.strip("-")

    # Truncate at a word boundary when possible
    if len(result) > max_len:
        truncated = result[:max_len]
        last_hyphen = truncated.rfind("-")
        result = truncated[:last_hyphen] if last_hyphen > 0 else truncated
        result = result.strip("-")

    return result or "case"


def _clean_dir_name(name: str) -> str:
    """Remove characters that are forbidden in directory names."""
    return _DIR_FORBIDDEN.sub("_", name).strip()


def case_relpath(case: TestCase, existing_paths: set[str] | None = None) -> str:
    """Compute the relative path for *case* inside the ``cases/`` directory.

    Format: ``{suite_folders}/TC-{id}-{slug}.md``

    Collision handling: if *existing_paths* already contains a path with the
    same ``TC-{id}-`` prefix but a different slug, append ``-2``, ``-3``, ...
    until the name is unique.
    """
    slug = slugify(case.name)
    dir_parts = [_clean_dir_name(part) for part in case.suite_path if part]
    base_stem = f"TC-{case.id}-{slug}"

    def _build(stem: str) -> str:
        filename = f"{stem}.md"
        parts = [*dir_parts, filename]
        return str(PurePosixPath(*parts)) if parts else filename

    candidate = _build(base_stem)
    if existing_paths is None:
        return candidate

    # Check for existing file with same ID but different slug
    prefix = f"TC-{case.id}-"
    conflicting = {
        p for p in existing_paths if p != candidate and PurePosixPath(p).stem.startswith(prefix)
    }
    if not conflicting:
        return candidate

    # Generate unique suffix
    counter = 2
    while True:
        stem = f"{base_stem}-{counter}"
        candidate = _build(stem)
        if candidate not in existing_paths:
            return candidate
        counter += 1


def _render_steps(steps: list[Step], indent: int = 0) -> list[str]:
    """Render a (possibly nested) step list as numbered Markdown lines."""
    lines: list[str] = []
    prefix = "    " * indent
    for i, step in enumerate(steps, 1):
        lines.append(f"{prefix}{i}. {step.name}")
        if step.expected_result:
            lines.append(f"{prefix}    - **Expected:** {step.expected_result}")
        if step.steps:
            lines.extend(_render_steps(step.steps, indent + 1))
    return lines


def serialize(case: TestCase) -> str:
    """Render *case* as a Markdown string with YAML front matter.

    The output is deterministic: same input → same bytes every time.
    """
    # --- Build front matter dict (fixed key order, skip None/empty) ---
    fm: dict[str, Any] = {}
    fm["id"] = case.id
    fm["name"] = case.name

    if case.status is not None:
        fm["status"] = case.status

    fm["automated"] = case.automated

    if case.tags:
        fm["tags"] = sorted(case.tags)

    if case.custom_fields:
        fm["custom_fields"] = {k: sorted(v) for k, v in sorted(case.custom_fields.items())}

    if case.links:
        fm["links"] = [
            {
                k: v
                for k, v in {"name": lnk.name, "url": lnk.url, "type": lnk.type}.items()
                if v is not None
            }
            for lnk in case.links
        ]

    if case.source_url or case.source_project:
        source: dict[str, str] = {}
        if case.source_url:
            source["url"] = case.source_url
        if case.source_project:
            source["project"] = case.source_project
        fm["source"] = source

    front_matter = yaml.safe_dump(
        fm,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip("\n")

    # --- Build Markdown body ---
    body_lines: list[str] = [f"# {case.name}", ""]

    if case.description:
        body_lines += [case.description, ""]

    if case.precondition:
        body_lines += ["## Preconditions", "", case.precondition, ""]

    if case.steps:
        body_lines.append("## Steps")
        body_lines.append("")
        body_lines.extend(_render_steps(case.steps))
        body_lines.append("")

    if case.expected_result:
        body_lines += ["## Expected result", "", case.expected_result, ""]

    body = "\n".join(body_lines).rstrip("\n") + "\n"

    return f"---\n{front_matter}\n---\n\n{body}"
