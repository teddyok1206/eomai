from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service.registry_service import RegistryService
from eom_identifiers import sha256_file
from eom_item_registry import ComponentPointer, RegistryError, RegistryErrorCode
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_assessment_item_content import item_content


class FakeSession:
    def __init__(self, values: dict[tuple[type[object], str], object]) -> None:
        self.values = values

    def get(self, model: type[object], key: str) -> object | None:
        return self.values.get((model, key))


def _revision(root: Path, artifact_id: str, revision_id: str, primary: str) -> SimpleNamespace:
    file_path = root / primary
    digest = sha256_file(file_path)
    return SimpleNamespace(
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        content_hash=digest,
        approved=True,
        nas_path=str(root),
        manifest={
            "primary_file": primary,
            "files": [{"file_name": primary, "sha256": digest, "bytes": file_path.stat().st_size}],
        },
    )


def _fixture(tmp_path: Path) -> tuple[ComponentPointer, SimpleNamespace, FakeSession]:
    image_root = tmp_path / "image"
    image_root.mkdir()
    image_file = image_root / "diagram.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nTEST_ONLY")
    intake_manifest = image_root / "intake-manifest.json"
    intake_manifest.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    image_id = "artifact_" + "1" * 32
    image_revision_id = "rev_" + "2" * 32
    image_revision = _revision(image_root, image_id, image_revision_id, intake_manifest.name)
    image_revision.manifest["files"].append(
        {
            "file_name": image_file.name,
            "sha256": sha256_file(image_file),
            "bytes": image_file.stat().st_size,
        }
    )

    content_value = item_content()
    body = content_value["body"]
    assert isinstance(body, list) and isinstance(body[2], dict)
    artifact = body[2]["artifact"]
    assert isinstance(artifact, dict)
    artifact["sha256"] = sha256_file(image_file)
    artifact["artifact_member"] = image_file.name

    content_root = tmp_path / "content"
    content_root.mkdir()
    content_file = content_root / "assessment-item-content.json"
    content_file.write_text(json.dumps(content_value, ensure_ascii=False), encoding="utf-8")
    content_id = "artifact_" + "4" * 32
    content_revision_id = "rev_" + "5" * 32
    content_revision = _revision(content_root, content_id, content_revision_id, content_file.name)
    pointer = ComponentPointer(
        component_type="ITEM_CONTENT",
        ordinal=0,
        schema_ref="eom.assessment.item-content/1.0",
        media_type="application/json",
        artifact_id=content_id,
        artifact_revision_id=content_revision_id,
        sha256=content_revision.content_hash,
        logical_name="assessment-item-content.json",
    )
    session = FakeSession(
        {
            (ArtifactRecord, image_id): SimpleNamespace(approved=True),
            (ArtifactRevisionRecord, image_revision_id): image_revision,
        }
    )
    return pointer, content_revision, session


def test_registry_validates_canonical_content_and_nested_media_pointer(tmp_path: Path) -> None:
    pointer, revision, session = _fixture(tmp_path)
    RegistryService._validate_item_content_component(session, pointer, revision)  # type: ignore[arg-type]


def test_registry_rejects_stale_nested_media_pointer(tmp_path: Path) -> None:
    pointer, revision, session = _fixture(tmp_path)
    media = session.values[(ArtifactRevisionRecord, "rev_" + "2" * 32)]
    assert isinstance(media, SimpleNamespace)
    media.manifest["files"][1]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(RegistryError) as raised:
        RegistryService._validate_item_content_component(  # type: ignore[arg-type]
            session, pointer, revision
        )
    assert raised.value.code is RegistryErrorCode.ITEM_COMPONENT_INVALID


def test_registry_rejects_unsafe_content_primary_file(tmp_path: Path) -> None:
    pointer, revision, session = _fixture(tmp_path)
    revision.manifest = {"primary_file": "../outside.json"}
    with pytest.raises(RegistryError) as raised:
        RegistryService._validate_item_content_component(  # type: ignore[arg-type]
            session, pointer, revision
        )
    assert raised.value.code is RegistryErrorCode.ITEM_COMPONENT_INVALID


def test_registry_rejects_nested_symlink_and_media_type_mismatch(tmp_path: Path) -> None:
    pointer, revision, session = _fixture(tmp_path)
    content_root = Path(revision.nas_path)
    content_file = content_root / str(revision.manifest["primary_file"])
    nested = content_root / "nested"
    nested.mkdir()
    moved = nested / content_file.name
    content_file.replace(moved)
    link = content_root / "linked"
    link.symlink_to(nested, target_is_directory=True)
    revision.manifest = {
        "primary_file": f"linked/{moved.name}",
        "files": [
            {
                "file_name": f"linked/{moved.name}",
                "sha256": sha256_file(moved),
                "bytes": moved.stat().st_size,
            }
        ],
    }
    with pytest.raises(RegistryError) as raised:
        RegistryService._validate_item_content_component(  # type: ignore[arg-type]
            session, pointer, revision
        )
    assert raised.value.code is RegistryErrorCode.ITEM_COMPONENT_INVALID

    media_root = tmp_path / "media"
    media_root.mkdir()
    pointer, revision, session = _fixture(media_root)
    media = session.values[(ArtifactRevisionRecord, "rev_" + "2" * 32)]
    assert isinstance(media, SimpleNamespace)
    media_path = Path(media.nas_path) / "diagram.png"
    media_path.write_bytes(b"NOT_AN_IMAGE")
    media.manifest["files"][1]["sha256"] = sha256_file(media_path)
    media.manifest["files"][1]["bytes"] = media_path.stat().st_size
    value = item_content()
    body = value["body"]
    assert isinstance(body, list) and isinstance(body[2], dict)
    artifact = body[2]["artifact"]
    assert isinstance(artifact, dict)
    artifact["sha256"] = sha256_file(media_path)
    content_path = Path(revision.nas_path) / str(revision.manifest["primary_file"])
    content_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    revision.content_hash = sha256_file(content_path)
    revision.manifest["files"][0]["sha256"] = revision.content_hash
    revision.manifest["files"][0]["bytes"] = content_path.stat().st_size
    pointer = pointer.model_copy(update={"sha256": revision.content_hash})
    with pytest.raises(RegistryError) as raised:
        RegistryService._validate_item_content_component(  # type: ignore[arg-type]
            session, pointer, revision
        )
    assert raised.value.code is RegistryErrorCode.ITEM_COMPONENT_INVALID
