from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
from eom_catalog_service.content_pack_files import build_pack, compile_pack, inspect_bundle
from eom_content_pack import (
    ContentPackError,
    ContentPackState,
    render_prompt,
    require_transition,
)
from eom_identifiers import sha256_file

PACK = Path(__file__).resolve().parents[2] / "content/packs/generic-placeholder/0.1.0"


def _copy_pack(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(PACK, target)
    return target


def test_placeholder_pack_compiles_and_bundle_is_deterministic(tmp_path: Path) -> None:
    compiled = compile_pack(PACK)
    assert compiled.manifest.pack.key == "generic-placeholder"
    assert len(compiled.profiles) == 4
    first = build_pack(PACK, tmp_path / "first")
    second = build_pack(PACK, tmp_path / "second")
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.bundle_path.read_bytes() == second.bundle_path.read_bytes()
    assert inspect_bundle(first.bundle_path)["source_tree_sha256"] == compiled.source_tree_sha256


def test_pack_rejects_symlink_unsupported_file_secret_and_duplicate_yaml(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    (pack / "link.md").symlink_to(pack / "prompt-templates/authoring.md")
    with pytest.raises(ContentPackError, match="linked"):
        compile_pack(pack)
    (pack / "link.md").unlink()

    (pack / "payload.py").write_text("PLACEHOLDER_CONTENT", encoding="utf-8")
    with pytest.raises(ContentPackError, match="unsupported file type"):
        compile_pack(pack)
    (pack / "payload.py").unlink()

    (pack / "credential.txt").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nPLACEHOLDER", encoding="utf-8"
    )
    with pytest.raises(ContentPackError, match="secret"):
        compile_pack(pack)
    (pack / "credential.txt").unlink()

    (pack / "taxonomies/tags.yaml").write_text("key: one\nkey: two\n", encoding="utf-8")
    with pytest.raises(Exception, match="duplicate"):
        compile_pack(pack)


def test_pack_rejects_missing_reference_and_unsafe_prompt_expression(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    (pack / "rubrics/review-rubric.yaml").unlink()
    with pytest.raises(ContentPackError, match="missing file"):
        compile_pack(pack)

    pack = _copy_pack(tmp_path / "second")
    prompt = pack / "prompt-templates/authoring.md"
    prompt.write_text("{% for item in items %}{{ workflow.id }}{% endfor %}", encoding="utf-8")
    with pytest.raises(ContentPackError, match="unsupported template"):
        compile_pack(pack)


def test_restricted_prompt_renderer_requires_declared_scalar_context() -> None:
    template = "Workflow {{ workflow.id }} uses {{ pack.release_id }}."
    rendered = render_prompt(
        template,
        {"workflow": {"id": "workflow_placeholder"}, "pack": {"release_id": "packrel_x"}},
        ("workflow.id", "pack.release_id"),
    )
    assert rendered.text == "Workflow workflow_placeholder uses packrel_x."
    assert rendered.prompt_hash.startswith("sha256:")
    with pytest.raises(ContentPackError, match="missing"):
        render_prompt(template, {"workflow": {"id": "x"}}, ("workflow.id", "pack.release_id"))
    with pytest.raises(ContentPackError, match="declared context"):
        render_prompt(template, {}, ("workflow.id",))


def test_bundle_inspector_rejects_duplicate_entry(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.eompack"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pack.yaml", b"one")
        archive.writestr("pack.yaml", b"two")
    with pytest.raises(ContentPackError, match="duplicate"):
        inspect_bundle(path)


def test_content_pack_state_machine() -> None:
    require_transition(ContentPackState.DRAFT, ContentPackState.VALIDATED)
    require_transition(ContentPackState.VALIDATED, ContentPackState.RELEASED)
    require_transition(ContentPackState.RELEASED, ContentPackState.DEPRECATED)
    require_transition(ContentPackState.DEPRECATED, ContentPackState.RETIRED)
    with pytest.raises(ContentPackError):
        require_transition(ContentPackState.RELEASED, ContentPackState.DRAFT)


def test_source_files_remain_unchanged_by_build(tmp_path: Path) -> None:
    before = {
        path.relative_to(PACK): sha256_file(path) for path in PACK.rglob("*") if path.is_file()
    }
    build_pack(PACK, tmp_path)
    after = {
        path.relative_to(PACK): sha256_file(path) for path in PACK.rglob("*") if path.is_file()
    }
    assert before == after
