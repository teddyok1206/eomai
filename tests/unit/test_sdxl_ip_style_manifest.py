"""Pure protocol preparation; no actual model acquisition or worker admission."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest
from eom_image_contracts import (
    SDXL_IP_STYLE_FILES,
    SDXL_IP_STYLE_SCHEMA_REF,
    LocalImageSdxlIpStyleModelManifest,
    SdxlIpStyleLicense,
    SdxlIpStylePreprocessing,
    content_json_bytes,
    content_sha256,
    sdxl_ip_style_model_pointer,
    validate_sdxl_ip_style_model_pointer,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError


def _seal(value):
    value = copy.deepcopy(value)
    value["model_id"] = (
        "imgmodel_"
        + content_sha256(
            {"provider_family": value["provider_family"], "upstream_repo": value["upstream_repo"]}
        )[7:39]
    )
    value["model_revision_id"] = (
        "imgmodelrev_"
        + content_sha256(
            {key: value[key] for key in ("upstream_revision", "license", "preprocessing", "files")}
        )[7:39]
    )
    value.pop("manifest_sha256", None)
    value["manifest_sha256"] = content_sha256(value)
    return value


def _value():
    return _seal(
        dict(
            schema_version="local-image-sdxl-ip-style-model-manifest/1.0",
            provider_family="diffusers-sdxl-ip-adapter-global-vit-h",
            runtime_contract_version="eom-local-image-sdxl-ip-style-runner/1.0",
            state="EVALUATION_ONLY",
            activation_policy="FORBIDDEN",
            upstream_repo="h94/IP-Adapter",
            upstream_revision="018e402774aeeddd60609b4ecdb7e298259dc729",
            supported_base_repo="stabilityai/stable-diffusion-xl-base-1.0",
            license=SdxlIpStyleLicense().model_dump(mode="json"),
            preprocessing=SdxlIpStylePreprocessing().model_dump(mode="json"),
            files=[
                SDXL_IP_STYLE_FILES[name].model_dump(mode="json")
                for name in sorted(SDXL_IP_STYLE_FILES)
            ],
            created_at="2026-10-06T14:00:00Z",
            created_by="tests.ip-style",
        )
    )


def _validate(value):
    validate_contract("sdxl-ip-style-model-manifest", value)
    return LocalImageSdxlIpStyleModelManifest.model_validate(value)


def test_closed_model_manifest_preserves_component_identity_and_notices():
    manifest = _validate(_value())
    pointer = sdxl_ip_style_model_pointer(manifest)
    validate_sdxl_ip_style_model_pointer(pointer, manifest)
    assert pointer.model_id != pointer.model_revision_id
    assert pointer.manifest_sha256 == manifest.manifest_sha256
    assert (
        sum(f.size_bytes for f in manifest.files if f.relative_path.endswith(".safetensors"))
        == 3226764512
    )
    assert not manifest.license.hub_own_license_file
    assert not manifest.license.repack_equivalence_verified
    assert manifest.preprocessing.processor_center_crop is False
    assert manifest.preprocessing.processor_resize is False
    assert not any(
        name.startswith(("base/", "vae/", "controller/")) for name in SDXL_IP_STYLE_FILES
    )
    raw = content_json_bytes(manifest.model_dump(mode="json"))
    assert LocalImageSdxlIpStyleModelManifest.model_validate_json(raw) == manifest


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "local-image-sdxl-ip-style-model-manifest/2.0"),
        ("state", "APPROVED"),
        ("activation_policy", "ALLOWED"),
        ("upstream_repo", "h94/IP-Adapter-FaceID"),
        ("upstream_revision", "main"),
        ("provider_family", "diffusers-sdxl-ip-adapter-plus"),
        ("runtime_contract_version", "eom-local-image-sdxl-ip-style-runner/2.0"),
        ("supported_base_repo", "segmind/SSD-1B"),
        ("created_at", "2026-10-06T14:00:00"),
        ("created_at", "2026-10-06T23:00:00+09:00"),
        ("created_by", "../unsafe"),
        ("extra", "ignored"),
    ],
)
def test_scope_revision_and_time_mismatches_fail(field, value):
    modified = _value()
    modified[field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(modified))


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "size",
        "pickle",
        "plus",
        "duplicate",
        "missing",
        "extra",
        "order",
        "unsafe",
    ],
)
def test_exact_file_closure_is_not_repaired_or_latest_substituted(fault):
    value = _value()
    file = value["files"][0]
    if fault == "hash":
        file["sha256"] = "sha256:" + "0" * 64
    elif fault == "size":
        file["size_bytes"] += 1
    elif fault == "pickle":
        value["files"][-1]["relative_path"] = "sdxl_models/ip-adapter_sdxl_vit-h.bin"
    elif fault == "plus":
        value["files"][-1]["relative_path"] = "sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors"
    elif fault == "duplicate":
        value["files"][1] = copy.deepcopy(file)
    elif fault == "missing":
        value["files"].pop()
    elif fault == "extra":
        value["files"].append(copy.deepcopy(file))
    elif fault == "order":
        value["files"].reverse()
    else:
        file["relative_path"] = "models/../README.md"
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("hub_identifier", "mit"),
        ("hub_own_license_file", True),
        ("code_revision", "main"),
        ("code_license_id", "MIT"),
        ("encoder_origin_license_id", "Apache-2.0"),
        ("repack_equivalence_verified", True),
        ("basis", "UNVERIFIED"),
    ],
)
def test_license_claims_cannot_expand_beyond_recorded_provenance(field, value):
    modified = _value()
    modified["license"][field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(modified))


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy", "CENTER_CROP/1.0"),
        ("processor_resize", True),
        ("processor_center_crop", True),
        ("width_px", 256),
        ("height_px", 256),
        ("resize_interpolation", "NEAREST"),
        ("pillow_version", "latest"),
        ("transformers_version", "latest"),
        ("image_mean", [0.5, 0.5, 0.5]),
        ("image_std", [0.5, 0.5, 0.5]),
        ("rescale_factor", 1.0),
    ],
)
def test_preprocessing_is_explicit_and_does_not_use_ambient_defaults(field, value):
    modified = _value()
    modified["preprocessing"][field] = value
    with pytest.raises((ValueError, SchemaError)):
        _validate(_seal(modified))


@pytest.mark.parametrize("field", ["model_id", "model_revision_id", "manifest_sha256"])
def test_manifest_identity_and_pointer_mismatch_fail_independently(field):
    manifest = _validate(_value())
    value = manifest.model_dump(mode="json")
    value[field] = (
        "sha256:" + "0" * 64
        if field == "manifest_sha256"
        else ("imgmodel_" if field == "model_id" else "imgmodelrev_") + "0" * 32
    )
    with pytest.raises(ValueError):
        LocalImageSdxlIpStyleModelManifest.model_validate(value)
    pointer = sdxl_ip_style_model_pointer(manifest)
    with pytest.raises(ValueError, match="SDXL_IP_STYLE_POINTER_MISMATCH"):
        validate_sdxl_ip_style_model_pointer(
            pointer.model_copy(update={field: value[field]}), manifest
        )


def test_creator_time_affects_manifest_hash_not_logical_or_revision_identity():
    first = _validate(_value())
    changed = first.model_dump(mode="json")
    changed["created_by"] = "tests.other"
    changed["created_at"] = "2026-10-06T14:01:00Z"
    second = _validate(_seal(changed))
    assert first.model_id == second.model_id
    assert first.model_revision_id == second.model_revision_id
    assert first.manifest_sha256 != second.manifest_sha256


def test_file_values_mapping_and_manifest_are_immutable():
    manifest = _validate(_value())
    with pytest.raises(ValueError):
        manifest.state = "APPROVED"
    with pytest.raises(ValueError):
        manifest.files[0].size_bytes = 1
    with pytest.raises(TypeError):
        SDXL_IP_STYLE_FILES["unexpected"] = manifest.files[0]


def test_schema_draft_copies_model_parity_and_hash_are_exact():
    root = Path(__file__).resolve().parents[2]
    name = SCHEMA_FILES["sdxl-ip-style-model-manifest"]
    raw = (root / "schemas/image-provider" / name).read_bytes()
    assert (
        raw == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
    )
    assert (
        "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256["sdxl-ip-style-model-manifest"]
    )
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    generated = LocalImageSdxlIpStyleModelManifest.model_json_schema()
    generated["$id"] = SDXL_IP_STYLE_SCHEMA_REF
    generated["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert schema == generated


def test_contract_has_no_numerical_storage_or_infrastructure_import():
    root = Path(__file__).resolve().parents[2]
    source = root / "packages/image_contracts/eom_image_contracts/sdxl_ip_style.py"
    imported = set()
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {
        "torch",
        "diffusers",
        "PIL",
        "os",
        "pathlib",
        "subprocess",
        "sqlalchemy",
        "eom_orchestrator",
        "eom_image_provider",
    }
