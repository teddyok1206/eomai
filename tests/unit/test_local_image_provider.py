from __future__ import annotations

import binascii
import hashlib
import json
import stat
import struct
import zlib
from datetime import datetime
from pathlib import Path

import pytest
from eom_image_contracts import (
    LocalImageGenerationRequest,
    LocalImageModelManifest,
    LocalImageRuntime,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_image_provider.model_manifest import SSD1B_REQUIRED_FILES, create_model_manifest
from eom_image_provider.provider import (
    GeneratedBackground,
    ProviderError,
    generate_background,
    verify_model_revision,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "imgmodel_" + "1" * 32
MODEL_REVISION_ID = "imgmodelrev_" + "2" * 32
REQUEST_ID = "imgreq_" + "3" * 32


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def _png() -> bytes:
    width, height = 800, 500
    rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(rows, level=9)),
            _chunk(b"IEND", b""),
        )
    )


def _store(tmp_path: Path) -> tuple[Path, LocalImageModelManifest]:
    root = tmp_path / "models"
    revision = root / MODEL_ID / MODEL_REVISION_ID
    files = revision / "files"
    files.mkdir(parents=True, mode=0o750)
    root.chmod(0o750)
    (root / MODEL_ID).chmod(0o750)
    revision.chmod(0o750)
    files.chmod(0o750)
    model_file = files / "model_index.json"
    model_file.write_text('{"_class_name":"StableDiffusionXLPipeline"}\n', encoding="utf-8")
    model_file.chmod(0o640)
    body = {
        "schema_version": "local-image-model-manifest/1.0",
        "model_id": MODEL_ID,
        "model_revision_id": MODEL_REVISION_ID,
        "provider_family": "diffusers-ssd-1b",
        "runtime_contract_version": "eom-local-image-provider/1.0",
        "state": "APPROVED",
        "upstream": {
            "repo_id": "segmind/SSD-1B",
            "revision": "60987f37e94cd59c36b1cba832b9f97b57395a10",
            "source_url": "https://huggingface.co/segmind/SSD-1B",
            "license_id": "Apache-2.0",
        },
        "files": [
            {
                "relative_path": "model_index.json",
                "size_bytes": model_file.stat().st_size,
                "sha256": "sha256:" + hashlib.sha256(model_file.read_bytes()).hexdigest(),
            }
        ],
        "created_at": "2026-09-01T00:00:00Z",
        "approved_at": "2026-09-01T00:00:01Z",
        "approved_by": "operator:test",
    }
    value = {**body, "manifest_sha256": content_sha256(body)}
    validate_contract("model-manifest", value)
    manifest = LocalImageModelManifest.model_validate(value)
    manifest_path = revision / "manifest.json"
    manifest_path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o640)
    return root, manifest


def _request(manifest: LocalImageModelManifest) -> LocalImageGenerationRequest:
    prompt = "neutral paper texture, muted pale blue and gray, no text, no labels"
    negative = "text, letters, numbers, labels, watermark, face"
    body = {
        "schema_version": "local-image-generation-request/1.0",
        "request_id": REQUEST_ID,
        "idempotency_key": "local-image-smoke:" + "4" * 32,
        "model": {
            "model_id": manifest.model_id,
            "model_revision_id": manifest.model_revision_id,
            "manifest_sha256": manifest.manifest_sha256,
            "provider_family": manifest.provider_family,
            "runtime_contract_version": manifest.runtime_contract_version,
        },
        "prompt": prompt,
        "prompt_sha256": text_sha256(prompt),
        "negative_prompt": negative,
        "negative_prompt_sha256": text_sha256(negative),
        "seed": 20260901,
        "sampler": {
            "contract": "euler-discrete/ssd-1b-v1",
            "inference_steps": 20,
            "guidance_scale": 7.5,
            "dtype": "float16",
        },
        "generation_canvas": {"width_px": 800, "height_px": 504},
        "delivery_canvas": {"width_px": 800, "height_px": 500},
        "output_member": "generated-background.png",
        "timeout_seconds": 600,
    }
    value = {**body, "request_sha256": content_sha256(body)}
    validate_contract("generation-request", value)
    return LocalImageGenerationRequest.model_validate(value)


class FakeBackend:
    def generate(
        self, *, model_directory: Path, request: LocalImageGenerationRequest
    ) -> GeneratedBackground:
        assert model_directory.name == "files"
        assert request.request_id == REQUEST_ID
        return GeneratedBackground(
            png_bytes=_png(),
            runtime=LocalImageRuntime(
                python_version="3.11.15",
                torch_version="2.7.1+cu128",
                diffusers_version="0.35.2",
                transformers_version="4.56.2",
                cuda_version="12.8",
                gpu_name="NVIDIA GeForce RTX 5080",
                compute_capability="12.0",
                peak_gpu_memory_bytes=1024,
            ),
        )


def test_contract_resources_are_canonical_mirrors() -> None:
    for name in (
        "local-image-model-manifest-v1.schema.json",
        "local-image-generation-request-v1.schema.json",
        "local-image-generation-receipt-v1.schema.json",
    ):
        canonical = REPOSITORY_ROOT / "schemas" / "image-provider" / name
        packaged = (
            REPOSITORY_ROOT
            / "packages"
            / "image_contracts"
            / "eom_image_contracts"
            / "schemas"
            / name
        )
        assert canonical.read_bytes() == packaged.read_bytes()


def test_model_manifest_request_and_receipt_are_pointer_pinned(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    request = _request(manifest)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    receipt = generate_background(
        model_store_root=root,
        workspace=workspace,
        request=request,
        backend=FakeBackend(),
    )

    assert receipt.model.model_revision_id == MODEL_REVISION_ID
    assert receipt.model.manifest_sha256 == manifest.manifest_sha256
    assert receipt.request_sha256 == request.request_sha256
    assert receipt.output.sha256 == "sha256:" + hashlib.sha256(_png()).hexdigest()
    assert receipt.output.width_px == 800
    assert receipt.output.height_px == 500
    assert stat.S_IMODE((workspace / "generated-background.png").stat().st_mode) == 0o600
    assert stat.S_IMODE((workspace / "generation-receipt.json").stat().st_mode) == 0o600
    validate_contract("generation-receipt", receipt.model_dump(mode="json"))


def test_model_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    model_file = root / MODEL_ID / MODEL_REVISION_ID / "files" / "model_index.json"
    model_file.write_text("changed\n", encoding="utf-8")
    model_file.chmod(0o640)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL_HASH_MISMATCH"):
        verify_model_revision(root, _request(manifest).model)


def test_model_symlink_fails_closed(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    model_file = root / MODEL_ID / MODEL_REVISION_ID / "files" / "model_index.json"
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o640)
    model_file.unlink()
    model_file.symlink_to(target)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL"):
        verify_model_revision(root, _request(manifest).model)


def test_prompt_and_request_hashes_cannot_be_replayed_with_changed_input(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    value = _request(manifest).model_dump(mode="json")
    value["prompt"] = "changed prompt"
    with pytest.raises(ValueError, match="prompt hash mismatch"):
        LocalImageGenerationRequest.model_validate(value)


def test_existing_output_prevents_an_implicit_regeneration(tmp_path: Path) -> None:
    root, manifest = _store(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "generated-background.png").write_bytes(_png())
    (workspace / "generated-background.png").chmod(0o600)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_OUTPUT_INVALID"):
        generate_background(
            model_store_root=root,
            workspace=workspace,
            request=_request(manifest),
            backend=FakeBackend(),
        )


def test_contract_timestamps_reject_non_utc_values(tmp_path: Path) -> None:
    _, manifest = _store(tmp_path)
    value = manifest.model_dump(mode="json")
    value["approved_at"] = datetime(2026, 9, 1, 9, 0, tzinfo=None).isoformat()
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    value["manifest_sha256"] = content_sha256(body)
    with pytest.raises(ValueError, match="timestamp must be UTC"):
        LocalImageModelManifest.model_validate(value)


def test_reviewed_ssd1b_file_set_creates_one_hash_pinned_manifest(tmp_path: Path) -> None:
    revision = tmp_path / "revision"
    files_root = revision / "files"
    files_root.mkdir(parents=True, mode=0o750)
    revision.chmod(0o750)
    files_root.chmod(0o750)
    for relative in SSD1B_REQUIRED_FILES:
        target = files_root / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        target.parent.chmod(0o750)
        target.write_bytes((relative + "\n").encode())
        target.chmod(0o640)

    manifest = create_model_manifest(
        revision,
        model_id=MODEL_ID,
        model_revision_id=MODEL_REVISION_ID,
        approved_by="operator:test",
    )

    assert tuple(item.relative_path for item in manifest.files) == SSD1B_REQUIRED_FILES
    assert manifest.upstream.revision == "60987f37e94cd59c36b1cba832b9f97b57395a10"
    assert (revision / "manifest.json").is_file()
    assert stat.S_IMODE((revision / "manifest.json").stat().st_mode) == 0o640


def test_ssd1b_manifest_rejects_an_unreviewed_extra_file(tmp_path: Path) -> None:
    revision = tmp_path / "revision"
    files_root = revision / "files"
    files_root.mkdir(parents=True, mode=0o750)
    revision.chmod(0o750)
    files_root.chmod(0o750)
    extra = files_root / "unreviewed.bin"
    extra.write_bytes(b"untrusted\n")
    extra.chmod(0o640)
    with pytest.raises(ProviderError, match="LOCAL_IMAGE_MODEL_UNAVAILABLE"):
        create_model_manifest(
            revision,
            model_id=MODEL_ID,
            model_revision_id=MODEL_REVISION_ID,
            approved_by="operator:test",
        )
