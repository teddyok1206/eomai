from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import (
    LocalImageSdxlLineartStack,
    SdxlLineartComponentManifest,
    content_sha256,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _seal_component(value: dict[str, Any]) -> dict[str, Any]:
    value.pop("manifest_sha256", None)
    value["component_id"] = (
        "imgstackcomponent_"
        + content_sha256({"role": value["role"], "repo_id": value["upstream"]["repo_id"]})[7:39]
    )
    value["component_revision_id"] = (
        "imgstackcomponentrev_"
        + content_sha256({"upstream": value["upstream"], "files": value["files"]})[7:39]
    )
    return {**value, "manifest_sha256": content_sha256(value)}


def _component(role: str) -> dict[str, Any]:
    upstreams = {
        "BASE": ("stabilityai/stable-diffusion-xl-base-1.0", "CreativeML-Open-RAIL++-M"),
        "LINEART_ADAPTER": ("TencentARC/t2i-adapter-lineart-sdxl-1.0", "Apache-2.0"),
        "VAE": ("madebyollin/sdxl-vae-fp16-fix", "MIT"),
    }
    repo, license_id = upstreams[role]
    paths: tuple[str, ...]
    if role == "BASE":
        paths = (
            "model_index.json",
            "scheduler/scheduler_config.json",
            "text_encoder/config.json",
            "text_encoder/model.fp16.safetensors",
            "text_encoder_2/config.json",
            "text_encoder_2/model.fp16.safetensors",
            "unet/config.json",
            "unet/diffusion_pytorch_model.fp16.safetensors",
            "tokenizer/tokenizer_config.json",
            "tokenizer/vocab.json",
            "tokenizer/merges.txt",
            "tokenizer_2/tokenizer_config.json",
            "tokenizer_2/vocab.json",
            "tokenizer_2/merges.txt",
        )
    else:
        paths = (
            "config.json",
            "diffusion_pytorch_model.fp16.safetensors"
            if role == "LINEART_ADAPTER"
            else "diffusion_pytorch_model.safetensors",
        )
    return _seal_component(
        {
            "role": role,
            "upstream": {
                "repo_id": repo,
                "revision": "a" * 40,
                "source_url": "https://huggingface.co/" + repo,
                "license_id": license_id,
            },
            "files": [
                {"relative_path": path, "size_bytes": 20, "sha256": _sha(role + path)}
                for path in sorted(paths)
            ],
        }
    )


def _seal_stack(value: dict[str, Any]) -> dict[str, Any]:
    value.pop("manifest_sha256", None)
    value["model_id"] = (
        "imgmodel_"
        + content_sha256(
            {
                "provider_family": value["provider_family"],
                "base_repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
            }
        )[7:39]
    )
    value["model_revision_id"] = (
        "imgmodelrev_" + content_sha256({"components": value["components"]})[7:39]
    )
    return {**value, "manifest_sha256": content_sha256(value)}


def _stack() -> dict[str, Any]:
    return _seal_stack(
        {
            "schema_version": "local-image-sdxl-lineart-stack/1.0",
            "provider_family": "diffusers-sdxl-t2i-lineart",
            "runtime_contract_version": "eom-local-image-sdxl-lineart-runner/1.0",
            "state": "EVALUATION_ONLY",
            "activation_policy": "FORBIDDEN",
            "created_at": "2026-10-03T06:00:00Z",
            "created_by": "test.sdxl.stack",
            "components": [_component(role) for role in ("BASE", "LINEART_ADAPTER", "VAE")],
        }
    )


def test_stack_schema_model_canonical_hash_and_component_identity() -> None:
    value = _stack()
    validate_contract("sdxl-lineart-stack", value)
    stack = LocalImageSdxlLineartStack.model_validate(value)
    assert stack.model_dump(mode="json") == value
    assert len({component.component_id for component in stack.components}) == 3
    assert stack.model_id != stack.model_revision_id
    assert stack.state == "EVALUATION_ONLY" and stack.activation_policy == "FORBIDDEN"
    assert LocalImageSdxlLineartStack.model_validate_json(stack.model_dump_json()) == stack


@pytest.mark.parametrize("field", ["model_id", "model_revision_id", "manifest_sha256"])
def test_wrong_stack_identity_is_rejected(field: str) -> None:
    value = _stack()
    value[field] = value[field][:-1] + ("a" if value[field][-1] != "a" else "b")
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartStack.model_validate(value)


@pytest.mark.parametrize("field", ["component_id", "component_revision_id", "manifest_sha256"])
def test_wrong_component_identity_is_rejected(field: str) -> None:
    value = _component("BASE")
    value[field] = value[field][:-1] + ("a" if value[field][-1] != "a" else "b")
    with pytest.raises(ValidationError):
        SdxlLineartComponentManifest.model_validate(value)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unordered"])
def test_role_set_is_fixed_complete_and_ordered(mutation: str) -> None:
    value = _stack()
    if mutation == "missing":
        value["components"].pop()
    elif mutation == "duplicate":
        value["components"][2] = value["components"][1]
    else:
        value["components"].reverse()
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartStack.model_validate(_seal_stack(value))
    if mutation != "unordered":
        with pytest.raises(JsonSchemaValidationError):
            validate_contract("sdxl-lineart-stack", value)


@pytest.mark.parametrize("field", ["repo_id", "source_url", "license_id"])
def test_role_upstream_and_license_cannot_be_substituted(field: str) -> None:
    value = _stack()
    value["components"][0]["upstream"][field] = value["components"][1]["upstream"][field]
    value["components"][0] = _seal_component(value["components"][0])
    value = _seal_stack(value)
    with pytest.raises(ValidationError, match="role/upstream/license"):
        LocalImageSdxlLineartStack.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("sdxl-lineart-stack", value)


@pytest.mark.parametrize("file_change", ["missing", "duplicate", "unordered", "pickle", "code"])
def test_required_local_members_and_safe_formats(file_change: str) -> None:
    value = _component("BASE")
    if file_change == "missing":
        value["files"] = value["files"][:-1]
    elif file_change == "duplicate":
        value["files"].append(value["files"][-1])
    elif file_change == "unordered":
        value["files"].reverse()
    else:
        path = "unsafe.bin" if file_change == "pickle" else "unsafe.py"
        value["files"].append({"relative_path": path, "size_bytes": 20, "sha256": _sha(path)})
        value["files"].sort(key=lambda file: file["relative_path"])
    with pytest.raises(ValidationError):
        SdxlLineartComponentManifest.model_validate(_seal_component(value))


@pytest.mark.parametrize("path", ["/p.json", "../p.json", "p/../p.json", "p//p.json", "p.json/"])
def test_schema_and_model_reject_unsafe_model_paths(path: str) -> None:
    value = _stack()
    value["components"][0]["files"][0]["relative_path"] = path
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("sdxl-lineart-stack", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartStack.model_validate(value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("state", "APPROVED"),
        ("activation_policy", "ALLOWED"),
        ("provider_family", "diffusers-ssd-1b"),
        ("created_at", "2026-10-03T06:00:00+09:00"),
        ("created_at", "2026-10-03T06:00:00"),
    ],
)
def test_evaluation_only_architecture_and_utc_are_enforced(field: str, replacement: str) -> None:
    value = _stack()
    value[field] = replacement
    with pytest.raises(ValidationError):
        LocalImageSdxlLineartStack.model_validate(_seal_stack(value))


def test_upstream_revision_or_file_change_creates_a_distinct_immutable_revision() -> None:
    before = LocalImageSdxlLineartStack.model_validate(_stack())
    value = _stack()
    value["components"][0]["upstream"]["revision"] = "b" * 40
    value["components"][0] = _seal_component(value["components"][0])
    after = LocalImageSdxlLineartStack.model_validate(_seal_stack(value))
    assert before.model_id == after.model_id
    assert before.model_revision_id != after.model_revision_id
    assert before.manifest_sha256 != after.manifest_sha256
    assert before.components[0].component_id == after.components[0].component_id
    assert before.components[0].component_revision_id != after.components[0].component_revision_id
    assert before.components[1:] == after.components[1:]


def test_schema_model_required_fields_and_release_resource_alignment() -> None:
    root = Path(__file__).resolve().parents[2]
    name = "local-image-sdxl-lineart-stack-v1.schema.json"
    import json

    raw = (root / "schemas/image-provider" / name).read_bytes()
    assert (
        raw == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
    )
    schema = json.loads(raw)
    assert set(schema["required"]) == set(
        LocalImageSdxlLineartStack.model_json_schema()["required"]
    )
    assert set(schema["$defs"]["component"]["required"]) == set(
        SdxlLineartComponentManifest.model_json_schema()["required"]
    )
    for script in (
        "api/deploy_release.sh",
        "image_provider/build_release.sh",
        "image_trainer/build_release.sh",
    ):
        assert name in (root / "scripts" / script).read_text()
