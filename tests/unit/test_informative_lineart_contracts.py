from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import (
    InformativeLineartPointer,
    InformativeLineartUpstream,
    LocalImageInformativeLineartManifest,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_informative_lineart_pointer,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value.pop("manifest_sha256", None)
    value["extractor_id"] = (
        "imgextractor_"
        + content_sha256(
            {
                "provider_family": value["provider_family"],
                "repo_id": value["upstream"]["repo_id"],
                "weight_filename": value["upstream"]["weight_filename"],
            }
        )[7:39]
    )
    value["extractor_revision_id"] = (
        "imgextractorrev_"
        + content_sha256(
            {
                "upstream": value["upstream"],
                "conversion_policy": value["conversion_policy"],
                "architecture": value["architecture"],
                "runtime_contract_version": value["runtime_contract_version"],
                "files": value["files"],
            }
        )[7:39]
    )
    return {**value, "manifest_sha256": content_sha256(value)}


def _manifest() -> dict[str, Any]:
    return _seal(
        {
            "schema_version": "local-image-informative-lineart-manifest/1.0",
            "provider_family": "informative-drawings-style1",
            "runtime_contract_version": "eom-informative-lineart-extractor/1.0",
            "state": "EVALUATION_ONLY",
            "activation_policy": "FORBIDDEN",
            "created_at": "2026-10-03T22:00:00Z",
            "created_by": "test.extractor",
            "conversion_policy": "TORCH_WEIGHTS_ONLY_CPU_TO_SAFETENSORS/1.0",
            "architecture": "RGB_INSTANCE_NORM_RESNET3_SIGMOID/1.0",
            "upstream": {
                "repo_id": "carolineec/informativedrawings",
                "repo_type": "space",
                "revision": "bd4b4299be505803e036203a39c02024b4cfee11",
                "source_url": "https://huggingface.co/spaces/carolineec/informativedrawings",
                "license_id": "MIT",
                "license_record_sha256": (
                    "sha256:7cb79f3b0f9354c7f47a1ab56b09c0e3bd6c8d96243555be5e28ea79d6e6c8a7"
                ),
                "architecture_source_sha256": (
                    "sha256:4e989aff7a9f4491e9bf463dff0b7c35f84b52b34a0bf4ca918b525fa7d593d0"
                ),
                "weight_filename": "model.pth",
                "weight_bytes": 17173511,
                "weight_sha256": (
                    "sha256:c686ced2a666b4850b4bb6ccf0748031c3eda9f822de73a34b8979970d90f0c6"
                ),
            },
            "files": [
                {
                    "relative_path": name,
                    "size_bytes": 17173000 if name == "model.safetensors" else 64,
                    "sha256": "sha256:" + hashlib.sha256(name.encode()).hexdigest(),
                }
                for name in ("LICENSE", "config.json", "model.safetensors", "upstream.json")
            ],
        }
    )


def _pointer(manifest: LocalImageInformativeLineartManifest) -> InformativeLineartPointer:
    return InformativeLineartPointer(
        extractor_id=manifest.extractor_id,
        extractor_revision_id=manifest.extractor_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        provider_family=manifest.provider_family,
        runtime_contract_version=manifest.runtime_contract_version,
    )


def test_schema_model_canonical_identity_and_pinned_pointer() -> None:
    value = _manifest()
    validate_contract("informative-lineart-manifest", value)
    manifest = LocalImageInformativeLineartManifest.model_validate(value)
    assert manifest.model_dump(mode="json") == value
    validate_informative_lineart_pointer(_pointer(manifest), manifest)
    assert (
        LocalImageInformativeLineartManifest.model_validate_json(content_json_bytes(value))
        == manifest
    )
    assert manifest.extractor_id != manifest.extractor_revision_id
    assert manifest.manifest_sha256 not in {file.sha256 for file in manifest.files}
    with pytest.raises(ValidationError):
        manifest.state = "APPROVED"  # type: ignore[misc]


def test_manifest_factory_preserves_existing_identity_hash_and_canonical_utc() -> None:
    existing = LocalImageInformativeLineartManifest.model_validate(_manifest())
    assert InformativeLineartUpstream.pinned() == existing.upstream
    created = LocalImageInformativeLineartManifest.create(
        files=existing.files,
        created_at=datetime(2026, 10, 3, 22, tzinfo=UTC),
        created_by=existing.created_by,
    )
    assert created == existing
    assert created.model_dump(mode="json")["created_at"] == "2026-10-03T22:00:00Z"


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 10, 3, 22),
        datetime(2026, 10, 3, 22, tzinfo=timezone(timedelta(hours=9))),
    ],
)
def test_manifest_factory_rejects_non_utc_before_sealing(created_at: datetime) -> None:
    existing = LocalImageInformativeLineartManifest.model_validate(_manifest())
    with pytest.raises(ValidationError, match="UTC"):
        LocalImageInformativeLineartManifest.create(
            files=existing.files,
            created_at=created_at,
            created_by=existing.created_by,
        )


@pytest.mark.parametrize("field", ["extractor_id", "extractor_revision_id", "manifest_sha256"])
def test_tampered_identity_and_hash_are_rejected(field: str) -> None:
    value = _manifest()
    value[field] = value[field][:-1] + ("a" if value[field][-1] != "a" else "b")
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartManifest.model_validate(value)


@pytest.mark.parametrize("field", ["extractor_id", "extractor_revision_id", "manifest_sha256"])
def test_different_or_stale_pointer_is_not_resolved_as_latest(field: str) -> None:
    manifest = LocalImageInformativeLineartManifest.model_validate(_manifest())
    pointer = _pointer(manifest)
    value = pointer.model_dump(mode="json")
    value[field] = value[field][:-1] + ("a" if value[field][-1] != "a" else "b")
    with pytest.raises(ValueError, match="pinned manifest"):
        validate_informative_lineart_pointer(
            InformativeLineartPointer.model_validate(value), manifest
        )


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "reordered", "pickle", "code", "traversal"]
)
def test_complete_sorted_safe_member_set(change: str) -> None:
    value = _manifest()
    if change == "missing":
        value["files"].pop()
    elif change == "duplicate":
        value["files"][1] = dict(value["files"][0])
    elif change == "reordered":
        value["files"].reverse()
    else:
        value["files"][2]["relative_path"] = {
            "pickle": "model.pth",
            "code": "app.py",
            "traversal": "../model.safetensors",
        }[change]
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartManifest.model_validate(_seal(value))


@pytest.mark.parametrize("member", ["LICENSE", "config.json", "model.safetensors", "upstream.json"])
def test_declared_byte_bounds(member: str) -> None:
    value = _manifest()
    file = {entry["relative_path"]: entry for entry in value["files"]}[member]
    file["size_bytes"] = 32 * 1024**2 + 1 if member == "model.safetensors" else 64 * 1024 + 1
    with pytest.raises(ValidationError, match="byte limit"):
        LocalImageInformativeLineartManifest.model_validate(_seal(value))


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("repo_id", "lllyasviel/Annotators"),
        ("repo_type", "model"),
        ("revision", "main"),
        ("license_id", "other"),
        ("weight_filename", "model2.pth"),
        ("weight_bytes", 17173512),
        ("weight_sha256", "sha256:" + "a" * 64),
        ("architecture_source_sha256", "sha256:" + "a" * 64),
        ("license_record_sha256", "sha256:" + "a" * 64),
    ],
)
def test_author_weight_architecture_and_license_provenance_is_fixed(
    field: str, replacement: object
) -> None:
    value = _manifest()
    value["upstream"][field] = replacement
    value = _seal(value)
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartManifest.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("informative-lineart-manifest", value)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("state", "APPROVED"),
        ("activation_policy", "AUTOMATIC"),
        ("conversion_policy", "TORCH_PICKLE_LOAD"),
        ("architecture", "RESNET9"),
        ("provider_family", "diffusers-ssd-1b"),
        ("runtime_contract_version", "eom-informative-lineart-extractor/2.0"),
    ],
)
def test_evaluation_only_architecture_and_restricted_conversion(
    field: str, replacement: str
) -> None:
    value = _manifest()
    value[field] = replacement
    value = _seal(value)
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartManifest.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("informative-lineart-manifest", value)


@pytest.mark.parametrize("created_at", ["2026-10-03T22:00:00", "2026-10-03T22:00:00+09:00"])
def test_manifest_timestamp_requires_utc(created_at: str) -> None:
    value = _manifest()
    value["created_at"] = created_at
    with pytest.raises(ValidationError, match="UTC"):
        LocalImageInformativeLineartManifest.model_validate(_seal(value))


def test_runtime_file_change_creates_successor_revision_without_changing_logical_identity() -> None:
    original = LocalImageInformativeLineartManifest.model_validate(_manifest())
    value = original.model_dump(mode="json")
    value["files"][2]["sha256"] = "sha256:" + "b" * 64
    successor = LocalImageInformativeLineartManifest.model_validate(_seal(value))
    assert successor.extractor_id == original.extractor_id
    assert successor.extractor_revision_id != original.extractor_revision_id
    assert successor.manifest_sha256 != original.manifest_sha256
    with pytest.raises(ValueError):
        validate_informative_lineart_pointer(_pointer(original), successor)


def test_canonical_and_wheel_schemas_are_exact_and_binary_values_are_not_admitted() -> None:
    root = Path(__file__).resolve().parents[2]
    filename = "local-image-informative-lineart-manifest-v1.schema.json"
    assert (root / "schemas/image-provider" / filename).read_bytes() == (
        root / "packages/image_contracts/eom_image_contracts/schemas" / filename
    ).read_bytes()
    value = _manifest()
    value["image_bytes"] = "untrusted-binary-payload"
    with pytest.raises(ValidationError):
        LocalImageInformativeLineartManifest.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("informative-lineart-manifest", value)
