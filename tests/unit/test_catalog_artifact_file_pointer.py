from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import sha256_file


class _Session:
    def __init__(self, revision: object | None) -> None:
        self.revision = revision

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, _model: object, _revision_id: str) -> object | None:
        return self.revision


class _ReadMemberSession:
    def __init__(self, *, logical: object, revision: object) -> None:
        self.logical = logical
        self.revision = revision

    def __enter__(self) -> _ReadMemberSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, model: object, _record_id: str) -> object:
        if getattr(model, "__name__", "") == "ArtifactRecord":
            return self.logical
        return self.revision


def _service(
    tmp_path: Path, *, target: Path
) -> tuple[CatalogArtifactService, dict[str, str], SimpleNamespace]:
    digest = sha256_file(target.resolve())
    pointer = {
        "artifact_id": "artifact_" + "1" * 32,
        "revision_id": "rev_" + "2" * 32,
        "content_hash": digest,
        "member": "generated-stimulus.png",
    }
    revision = SimpleNamespace(
        approved=True,
        logical_artifact_id=pointer["artifact_id"],
        content_hash=digest,
        nas_path=str(target.parent),
        manifest={
            "primary_file": pointer["member"],
            "files": [{"file_name": pointer["member"], "sha256": digest}],
        },
    )
    service = object.__new__(CatalogArtifactService)
    service.settings = CatalogSettings(nas_artifact_root=tmp_path / "nas")
    cast(Any, service).sessions = lambda: _Session(revision)
    return service, pointer, revision


def _materialized(tmp_path: Path) -> Path:
    root = tmp_path / "nas" / "artifact" / "revision"
    root.mkdir(parents=True)
    target = root / "generated-stimulus.png"
    target.write_bytes(b"bounded-test-png")
    return target


def _read_member_service(
    tmp_path: Path,
) -> tuple[CatalogArtifactService, dict[str, object], SimpleNamespace]:
    root = tmp_path / "nas" / "artifact" / "revision"
    nested = root / "proposals"
    nested.mkdir(parents=True)
    target = nested / "proposal.json"
    payload = b'{"schema_version":"1.0"}'
    target.write_bytes(payload)
    digest = sha256_file(target)
    pointer: dict[str, object] = {
        "artifact_id": "artifact_" + "3" * 32,
        "revision_id": "rev_" + "4" * 32,
        "member_path": "proposals/proposal.json",
        "sha256": digest,
        "media_type": "application/json",
        "schema_ref": "eom.knowledge.analysis-proposal/1.0",
        "max_bytes": 1024,
    }
    logical = SimpleNamespace(
        approved=True,
        logical_artifact_id=pointer["artifact_id"],
    )
    revision = SimpleNamespace(
        approved=True,
        logical_artifact_id=pointer["artifact_id"],
        nas_path=str(root),
        manifest={
            "files": [
                {
                    "file_name": pointer["member_path"],
                    "sha256": digest,
                    "media_type": pointer["media_type"],
                    "schema_ref": pointer["schema_ref"],
                    "bytes": len(payload),
                }
            ]
        },
    )
    service = object.__new__(CatalogArtifactService)
    service.settings = CatalogSettings(nas_artifact_root=tmp_path / "nas")
    cast(Any, service).sessions = lambda: _ReadMemberSession(
        logical=logical,
        revision=revision,
    )
    return service, pointer, revision


def test_exact_file_pointer_resolves_a_pinned_regular_member(tmp_path: Path) -> None:
    target = _materialized(tmp_path)
    service, pointer, _ = _service(tmp_path, target=target)
    service.verify_file_pointer(**pointer)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("artifact_id", "artifact_" + "9" * 32, "does not resolve"),
        ("content_hash", "sha256:" + "9" * 64, "does not resolve"),
        ("member", "../generated-stimulus.png", "unsafe"),
        ("member", "nested/generated-stimulus.png", "unsafe"),
    ],
)
def test_file_pointer_rejects_missing_stale_hash_or_unsafe_member(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    target = _materialized(tmp_path)
    service, pointer, _ = _service(tmp_path, target=target)
    pointer[field] = value
    with pytest.raises(ValueError, match=message):
        service.verify_file_pointer(**pointer)


def test_file_pointer_rejects_symlink_materialization(tmp_path: Path) -> None:
    target = _materialized(tmp_path)
    service, pointer, _ = _service(tmp_path, target=target)
    payload = target.parent / "payload.png"
    target.rename(payload)
    target.symlink_to(payload)
    with pytest.raises(ValueError, match="materialization"):
        service.verify_file_pointer(**pointer)


def test_file_pointer_rejects_a_manifest_that_does_not_pin_the_primary_member(
    tmp_path: Path,
) -> None:
    target = _materialized(tmp_path)
    service, pointer, revision = _service(tmp_path, target=target)
    revision.manifest["primary_file"] = "another.png"
    with pytest.raises(ValueError, match="manifest"):
        service.verify_file_pointer(**pointer)


def test_read_member_resolves_an_exact_nested_immutable_pointer(tmp_path: Path) -> None:
    service, pointer, _ = _read_member_service(tmp_path)

    assert service.read_member(**pointer) == b'{"schema_version":"1.0"}'


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "sha256:" + "9" * 64),
        ("media_type", "text/plain"),
        ("schema_ref", "eom.knowledge.analysis-proposal/9.9"),
        ("max_bytes", 1),
    ],
)
def test_read_member_rejects_manifest_pointer_mismatch(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    service, pointer, _ = _read_member_service(tmp_path)
    pointer[field] = value

    with pytest.raises(ValueError, match="manifest"):
        service.read_member(**pointer)


def test_read_member_rejects_intermediate_symlink_escape(tmp_path: Path) -> None:
    service, pointer, revision = _read_member_service(tmp_path)
    root = Path(revision.nas_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / "proposals" / "proposal.json"
    escaped = outside / "proposal.json"
    target.replace(escaped)
    (root / "proposals").rmdir()
    (root / "proposals").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        service.read_member(**pointer)
