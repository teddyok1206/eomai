"""Developer navigation stays small, source-linked and outside runtime authority."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / "docs" / "agent-context"


@pytest.fixture(scope="module")
def context_index() -> dict[str, Any]:
    value = json.loads((CONTEXT / "index.json").read_text())
    assert isinstance(value, dict)
    return cast("dict[str, Any]", value)


def repository_path(value: str) -> Path:
    relative = Path(value)
    assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in value
    assert not {".env", ".codex", "staging", "runtime", "artifacts", "backups"}.intersection(
        relative.parts
    )
    result = ROOT / relative
    assert result.resolve().is_relative_to(ROOT) and result.exists()
    return result


def test_context_index_has_a_valid_local_schema(context_index: dict[str, Any]) -> None:
    schema = json.loads((CONTEXT / "index.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(context_index)


def test_topic_ids_and_notes_are_unique_and_complete(context_index: dict[str, Any]) -> None:
    topics = context_index["topics"]
    assert len({topic["id"] for topic in topics}) == len(topics)
    notes = {topic["note"] for topic in topics}
    assert len(notes) == len(topics)
    assert notes == {path.name for path in CONTEXT.glob("*.md") if path.name != "README.md"}


def test_each_topic_resolves_current_source_tests_and_references(
    context_index: dict[str, Any],
) -> None:
    for topic in context_index["topics"]:
        assert (CONTEXT / topic["note"]).is_file()
        for field in ("source_paths", "test_paths", "reference_paths"):
            for value in topic[field]:
                repository_path(value)
        assert all(value.startswith("tests/") for value in topic["test_paths"])


def test_context_files_are_plain_notes_and_metadata_not_runtime_or_user_data() -> None:
    for path in CONTEXT.iterdir():
        assert path.is_file() and not path.is_symlink()
        assert path.suffix in {".md", ".json"}
        assert path.stat().st_size < 64 * 1024


def test_local_note_links_and_entrypoints_resolve() -> None:
    for path in CONTEXT.glob("*.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text()):
            assert "://" not in target
            assert (path.parent / target.split("#", 1)[0]).is_file()
    assert "docs/agent-context/README.md" in (ROOT / "AGENTS.md").read_text()
    assert "docs/agent-context/README.md" in (ROOT / "README.md").read_text()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("유사도", "similarity-embedding"),
        ("임베딩", "similarity-embedding"),
        ("HWPX", "document-output"),
        ("잘림", "item-db-graph"),
        ("슬롯", "chat-identity-slots"),
        ("프리셋", "authoring-review"),
        ("disposable", "development-operations"),
        ("모듈", "system-map"),
    ],
)
def test_frequent_terms_locate_the_intended_topic(
    context_index: dict[str, Any], query: str, expected: str
) -> None:
    matches = {
        topic["id"]
        for topic in context_index["topics"]
        if any(query.casefold() in word.casefold() for word in topic["keywords"])
    }
    assert expected in matches
