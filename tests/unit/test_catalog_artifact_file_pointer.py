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
