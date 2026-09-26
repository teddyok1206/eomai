from __future__ import annotations

import hashlib
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    _safe_read_beneath,
    resolve_control_artifact_member,
)


class _Rows:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> Self:
        return self

    def one_or_none(self) -> dict[str, object]:
        return self._row


class _Connection:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object, _parameters: object = None) -> _Rows:
        if str(statement).startswith("SET TRANSACTION"):
            return _Rows({})
        return _Rows(self._row)


class _Engine:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def connect(self) -> _Connection:
        return _Connection(self._row)


def _pointer(payload: bytes) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        member_path="manifests/review.json",
        schema_ref="eom://schemas/image-provider/test-review/1.0",
        media_type="application/json",
        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def test_resolve_control_artifact_member_checks_pointer_manifest_and_bytes(
    tmp_path: Path,
) -> None:
    payload = b'{"status":"ok"}\n'
    member = tmp_path / "manifests" / "review.json"
    member.parent.mkdir()
    member.write_bytes(payload)
    member.chmod(0o600)
    pointer = _pointer(payload)
    row: dict[str, object] = {
        "nas_path": str(tmp_path),
        "manifest": {
            "files": [
                {
                    "file_name": pointer.member_path,
                    "schema_ref": pointer.schema_ref,
                    "media_type": pointer.media_type,
                    "sha256": pointer.sha256,
                }
            ]
        },
        "revision_approved": True,
        "artifact_approved": True,
    }

    resolved = resolve_control_artifact_member(
        _Engine(row),  # type: ignore[arg-type]
        pointer,
        maximum_bytes=1024,
    )

    assert resolved == payload


def test_resolve_control_artifact_member_rejects_manifest_hash_drift(tmp_path: Path) -> None:
    payload = b'{"status":"ok"}\n'
    member = tmp_path / "manifests" / "review.json"
    member.parent.mkdir()
    member.write_bytes(payload)
    member.chmod(0o600)
    pointer = _pointer(payload)
    row: dict[str, object] = {
        "nas_path": str(tmp_path),
        "manifest": {
            "files": [
                {
                    "file_name": pointer.member_path,
                    "schema_ref": pointer.schema_ref,
                    "media_type": pointer.media_type,
                    "sha256": "sha256:" + "f" * 64,
                }
            ]
        },
        "revision_approved": True,
        "artifact_approved": True,
    }

    with pytest.raises(ControlArtifactResolutionError, match="CONTROL_ARTIFACT_MEMBER_INVALID"):
        resolve_control_artifact_member(
            _Engine(row),  # type: ignore[arg-type]
            pointer,
            maximum_bytes=1024,
        )


def test_safe_read_beneath_rejects_symlink_member(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"{}\n")
    target.chmod(0o600)
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "review.json").symlink_to(target)

    with pytest.raises(ControlArtifactResolutionError, match="CONTROL_ARTIFACT_MEMBER_MISSING"):
        _safe_read_beneath(tmp_path, "manifests/review.json", maximum_bytes=1024)
