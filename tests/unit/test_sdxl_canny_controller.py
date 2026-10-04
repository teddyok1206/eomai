"""Controller provenance/security tests; tiny fixtures are not actual weight acceptance."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts.models import ModelFile, content_json_bytes, content_sha256
from eom_image_contracts.sdxl_canny_controlnet import (
    SDXL_CANNY_CONTROLLER_FILES,
    LocalImageSdxlCannyControllerManifest,
    SdxlCannyControllerLicense,
    sdxl_canny_controller_pointer,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from eom_image_provider import sdxl_canny_controller_io as resolution
from eom_image_provider.provider import ProviderError
from jsonschema import ValidationError as SchemaError

from scripts.image_provider import download_sdxl_canny_controller as acquisition
from scripts.image_provider import install_sdxl_canny_controller as installation


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _manifest():
    value = dict(
        schema_version="local-image-sdxl-canny-controller-manifest/1.0",
        provider_family="diffusers-sdxl-controlnet-canny",
        runtime_contract_version="eom-local-image-sdxl-canny-runner/1.0",
        state="EVALUATION_ONLY",
        activation_policy="FORBIDDEN",
        upstream_repo="diffusers/controlnet-canny-sdxl-1.0",
        upstream_revision="eb115a19a10d14909256db740ed109532ab1483c",
        source_url="https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0",
        supported_base_repo="stabilityai/stable-diffusion-xl-base-1.0",
        license=SdxlCannyControllerLicense().model_dump(mode="json"),
        files=[
            SDXL_CANNY_CONTROLLER_FILES[name].model_dump(mode="json")
            for name in sorted(SDXL_CANNY_CONTROLLER_FILES)
        ],
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        created_by="tests.controller",
    )
    return LocalImageSdxlCannyControllerManifest.model_validate(_seal(value))


def _seal(value):
    value = copy.deepcopy(value)
    value["model_id"] = (
        "imgmodel_"
        + content_sha256(
            {
                "provider_family": value["provider_family"],
                "upstream_repo": value["upstream_repo"],
            }
        )[7:39]
    )
    value["model_revision_id"] = (
        "imgmodelrev_"
        + content_sha256(
            {
                "upstream_revision": value["upstream_revision"],
                "license": value["license"],
                "files": value["files"],
            }
        )[7:39]
    )
    value.pop("manifest_sha256", None)
    value["manifest_sha256"] = content_sha256(value)
    return value


def _metadata():
    return {
        "config.json": json.dumps(
            {
                "_class_name": "ControlNetModel",
                "addition_embed_type": "text_time",
                "conditioning_channels": 3,
                "in_channels": 4,
                "cross_attention_dim": 2048,
                "projection_class_embeddings_input_dim": 2816,
            }
        ).encode(),
        "README.md": b"---\nlicense: openrail++\nbase_model: runwayml/stable-diffusion-v1-5\n---\n",
        "hub-license-identifiers.md": (
            b"| Open Rail++-M License | `openrail++` | <!-- license: "
            b"https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0"
            b"/blob/main/LICENSE.md -->"
        ),
        "LICENSE.standard.md": b"CreativeML Open RAIL++-M License dated July 26, 2023",
    }


def _validate_metadata(metadata):
    resolution.validate_sdxl_canny_controller_metadata(
        config=metadata["config.json"],
        card=metadata["README.md"],
        mapping=metadata["hub-license-identifiers.md"],
        license_text=metadata["LICENSE.standard.md"],
    )


def test_manifest_closed_pointer_and_license_provenance():
    manifest = _manifest()
    validate_contract("sdxl-canny-controller-manifest", manifest.model_dump(mode="json"))
    pointer = sdxl_canny_controller_pointer(manifest)
    assert pointer.model_id != pointer.model_revision_id
    assert pointer.manifest_sha256 == manifest.manifest_sha256
    assert not manifest.license.controller_own_license_file
    assert manifest.license.basis == "HUB_DECLARATION_WITH_HUB_LINKED_STANDARD_TEXT"
    assert {file.relative_path for file in manifest.files} == {
        "config.json",
        "README.md",
        "LICENSE.standard.md",
        "hub-license-identifiers.md",
        "diffusion_pytorch_model.fp16.safetensors",
    }
    assert not any(
        "base/" in file.relative_path or "vae/" in file.relative_path for file in manifest.files
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("upstream_revision", "main"),
        ("upstream_repo", "runwayml/stable-diffusion-v1-5"),
        ("activation_policy", "ALLOWED"),
        ("state", "ACTIVE"),
        ("created_at", "2026-10-04T16:00:00"),
        ("created_at", "2026-10-04T16:00:00+09:00"),
        ("gpu_offload", True),
    ],
)
def test_manifest_rejects_scope_and_mutable_identity(field, value):
    changed = _manifest().model_dump(mode="json")
    changed[field] = value
    changed = _seal(changed)
    with pytest.raises((ValueError, SchemaError)):
        validate_contract("sdxl-canny-controller-manifest", changed)
        LocalImageSdxlCannyControllerManifest.model_validate(changed)


@pytest.mark.parametrize(
    "fault",
    [
        "weight_hash",
        "weight_size",
        "pickle",
        "missing",
        "extra",
        "duplicate",
        "order",
        "revision",
        "logical",
        "manifest",
        "license_own",
        "license_basis",
        "license_identifier",
    ],
)
def test_exact_controller_files_identity_and_license(fault):
    value = _manifest().model_dump(mode="json")
    if fault.startswith("weight_"):
        member = next(
            file for file in value["files"] if file["relative_path"].endswith("safetensors")
        )
        member["sha256" if fault == "weight_hash" else "size_bytes"] = (
            "sha256:" + "0" * 64 if fault == "weight_hash" else 10
        )
    elif fault == "pickle":
        value["files"][-2]["relative_path"] = "diffusion_pytorch_model.bin"
    elif fault == "missing":
        value["files"].pop()
    elif fault == "extra":
        value["files"].append(
            dict(relative_path="extra.txt", size_bytes=1, sha256="sha256:" + "0" * 64)
        )
    elif fault == "duplicate":
        value["files"][1] = value["files"][0]
    elif fault == "order":
        value["files"].reverse()
    elif fault.startswith("license_"):
        field = {
            "license_own": "controller_own_license_file",
            "license_basis": "basis",
            "license_identifier": "declared_identifier",
        }[fault]
        value["license"][field] = True if fault == "license_own" else "MIT"
    else:
        field = {
            "revision": "model_revision_id",
            "logical": "model_id",
            "manifest": "manifest_sha256",
        }[fault]
        value[field] = (
            "sha256:" + "0" * 64
            if fault == "manifest"
            else ("imgmodelrev_" if fault == "revision" else "imgmodel_") + "0" * 32
        )
    if fault not in {"revision", "logical", "manifest"}:
        value = _seal(value)
    with pytest.raises((ValueError, SchemaError)):
        validate_contract("sdxl-canny-controller-manifest", value)
        LocalImageSdxlCannyControllerManifest.model_validate(value)


@pytest.mark.parametrize(
    "fault",
    [
        "sd15",
        "channels",
        "class",
        "card",
        "mapping_missing",
        "mapping_duplicate",
        "mapping_unlinked",
        "text",
    ],
)
def test_license_and_architecture_metadata_fail_closed(fault):
    metadata = _metadata()
    if fault in {"sd15", "channels", "class"}:
        config = json.loads(metadata["config.json"])
        key = {
            "sd15": "cross_attention_dim",
            "channels": "conditioning_channels",
            "class": "_class_name",
        }[fault]
        config[key] = 768 if fault == "sd15" else 1 if fault == "channels" else "RemoteCode"
        metadata["config.json"] = json.dumps(config).encode()
    elif fault == "card":
        metadata["README.md"] = b"---\nlicense: mit\n---\n"
    elif fault == "mapping_missing":
        metadata["hub-license-identifiers.md"] = b"Missing"
    elif fault == "mapping_duplicate":
        metadata["hub-license-identifiers.md"] *= 2
        metadata["hub-license-identifiers.md"] = (
            _metadata()["hub-license-identifiers.md"]
            + b"\n"
            + _metadata()["hub-license-identifiers.md"]
        )
    elif fault == "mapping_unlinked":
        metadata["hub-license-identifiers.md"] = b"| Open Rail++-M License | `openrail++` |"
    else:
        metadata["LICENSE.standard.md"] = b"MIT"
    with pytest.raises(ValueError):
        _validate_metadata(metadata)


def test_card_wrong_frontmatter_does_not_select_wrong_architecture():
    _validate_metadata(_metadata())


def test_acquisition_metadata_preflight_never_downloads_weights_or_creates_folder(
    tmp_path, monkeypatch
):
    parent = tmp_path / "eom-sdxl-canny-download.synthetic"
    parent.mkdir(mode=0o700)
    destination = parent / "controller"
    monkeypatch.setattr(acquisition, "_destination", lambda path: None)
    trace = []

    def download(name, target):
        assert target is None and not name.endswith("safetensors")
        trace.append(name)
        return _metadata()[name]

    monkeypatch.setattr(acquisition, "_download", download)
    acquisition.acquire_sdxl_canny_controller(destination, preflight_only=True)
    assert set(trace) == set(_metadata()) and not destination.exists()


def test_bad_metadata_stops_before_weight_call_and_candidate_write(tmp_path, monkeypatch):
    monkeypatch.setattr(acquisition, "_destination", lambda path: None)

    def download(name, target):
        assert target is None and not name.endswith("safetensors")
        return b"---\nlicense: mit\n---\n" if name == "README.md" else _metadata()[name]

    monkeypatch.setattr(acquisition, "_download", download)
    destination = tmp_path / "controller"
    with pytest.raises(ValueError):
        acquisition.acquire_sdxl_canny_controller(destination)
    assert not destination.exists()


class _Response(io.BytesIO):
    def __init__(self, body, *, url="https://huggingface.co/data", encoding="identity"):
        super().__init__(body)
        self.url = url
        self.headers = {"Content-Encoding": encoding}


@pytest.mark.parametrize("fault", ["ok", "hash", "short", "oversize", "redirect", "encoding"])
def test_bounded_stream_hash_encoding_and_redirect(tmp_path, monkeypatch, fault):
    raw = b"abc"
    expected = ModelFile(relative_path="README.md", size_bytes=3, sha256=_sha(raw))
    monkeypatch.setattr(acquisition, "SDXL_CANNY_CONTROLLER_FILES", {"README.md": expected})
    body = {"hash": b"abd", "short": b"ab", "oversize": b"abcd"}.get(fault, raw)
    response = _Response(
        body,
        url="http://unsafe.invalid" if fault == "redirect" else "https://huggingface.co/data",
        encoding="gzip" if fault == "encoding" else "identity",
    )
    monkeypatch.setattr(acquisition, "urlopen", lambda url, timeout: response)
    target = tmp_path / "candidate.txt"
    if fault == "ok":
        assert acquisition._download("README.md", target) is None
        assert target.read_bytes() == raw and target.stat().st_mode & 0o777 == 0o600
    else:
        with pytest.raises(ValueError):
            acquisition._download("README.md", target)
        if fault in {"redirect", "encoding"}:
            assert not target.exists()


def test_no_destination_replay_or_symlink_overwrite(tmp_path):
    with pytest.raises(ValueError, match="DESTINATION"):
        acquisition._destination(tmp_path / "controller")
    with pytest.raises(ValueError, match="REQUIRES_OPERATOR"):
        installation.install_sdxl_canny_controller(tmp_path, tmp_path, "sha256:" + "0" * 64)


def _installed_fixture(tmp_path, monkeypatch):
    manifest = _manifest()
    revision = tmp_path / manifest.model_id / manifest.model_revision_id
    revision.mkdir(parents=True, mode=0o700)
    (revision.parent).chmod(0o700)
    (revision / "manifest.json").write_bytes(content_json_bytes(manifest.model_dump(mode="json")))
    for file in manifest.files:
        (revision / file.relative_path).write_bytes(
            _metadata().get(file.relative_path, b"WEIGHT_STUB")
        )
    for path in revision.iterdir():
        path.chmod(0o600)
    trace = []

    def verify(root, path, *, size_bytes, sha256, expected_owner_uid):
        expected = SDXL_CANNY_CONTROLLER_FILES[path]
        assert (size_bytes, sha256) == (expected.size_bytes, expected.sha256)
        trace.append(path)

    monkeypatch.setattr(resolution, "verify_staged_member", verify)
    # This fixture exercises closure/pointer/permissions, not actual tensor-byte verification.
    return manifest, revision, trace


def test_resolution_exact_pin_and_member_set_without_tensor_loading(tmp_path, monkeypatch):
    manifest, revision, trace = _installed_fixture(tmp_path, monkeypatch)
    resolved = resolution.resolve_sdxl_canny_controller(
        tmp_path, sdxl_canny_controller_pointer(manifest), expected_owner_uid=os.geteuid()
    )
    assert resolved.root == revision and trace == sorted(SDXL_CANNY_CONTROLLER_FILES)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "symlink",
        "writable",
        "manifest_hash",
        "pointer_hash",
        "pointer_revision",
        "manifest_format",
    ],
)
def test_resolution_missing_stale_permission_and_hash_negatives(tmp_path, monkeypatch, fault):
    manifest, revision, _ = _installed_fixture(tmp_path, monkeypatch)
    pointer = sdxl_canny_controller_pointer(manifest)
    if fault == "missing":
        (revision / "README.md").unlink()
    elif fault == "extra":
        (revision / "extra.txt").write_bytes(b"unexpected")
    elif fault == "symlink":
        (revision / "README.md").unlink()
        (revision / "README.md").symlink_to(tmp_path / "outside")
        # Production verify_staged_member rejects symlinks; don't use the tiny weight-fixture stub.
        monkeypatch.setattr(
            resolution,
            "verify_staged_member",
            lambda *a, **kw: (_ for _ in ()).throw(ProviderError("STAGED_MEMBER_INVALID")),
        )
    elif fault == "writable":
        revision.chmod(0o770)
    elif fault.startswith("pointer_"):
        value = pointer.model_dump(mode="json")
        value["manifest_sha256" if fault == "pointer_hash" else "model_revision_id"] = (
            "sha256:" + "0" * 64 if fault == "pointer_hash" else "imgmodelrev_" + "0" * 32
        )
        pointer = type(pointer).model_validate(value)
    else:
        raw = content_json_bytes(manifest.model_dump(mode="json"))
        if fault == "manifest_hash":
            raw = raw.replace(manifest.manifest_sha256.encode(), ("sha256:" + "0" * 64).encode())
        else:
            raw += b"\n"
        (revision / "manifest.json").write_bytes(raw)
    with pytest.raises(ProviderError, match=r"SDXL_PROBE_(MODEL_INVALID|HASH_MISMATCH)"):
        resolution.resolve_sdxl_canny_controller(tmp_path, pointer, expected_owner_uid=os.geteuid())


def test_schema_generated_copies_and_hash_pins():
    root = Path(__file__).resolve().parents[2]
    name = SCHEMA_FILES["sdxl-canny-controller-manifest"]
    raw = (root / "schemas/image-provider" / name).read_bytes()
    packaged = root / "packages/image_contracts/eom_image_contracts/schemas" / name
    assert (
        raw == packaged.read_bytes()
        and _sha(raw) == SCHEMA_SHA256["sdxl-canny-controller-manifest"]
    )
    generated = LocalImageSdxlCannyControllerManifest.model_json_schema()
    generated["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    generated["$id"] = "eom://schemas/image-provider/local-image-sdxl-canny-controller-manifest/1.0"
    assert json.loads(raw) == generated
