from __future__ import annotations

import copy
import struct
import zlib
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes, content_sha256

from scripts.image_trainer.publish_science_campaign_micro_evaluation import (
    ScienceCampaignMicroEvaluationPublicationError,
)
from scripts.image_trainer.publish_science_campaign_micro_evaluation import (
    _load_result as load_evaluation_result,
)
from scripts.image_trainer.publish_science_campaign_micro_evaluation import (
    _members as evaluation_members,
)
from scripts.image_trainer.publish_science_campaign_micro_probe import (
    ScienceCampaignMicroProbePublicationError,
)
from scripts.image_trainer.publish_science_campaign_micro_probe import (
    _load_result as load_training_result,
)
from scripts.image_trainer.publish_science_campaign_micro_probe import (
    _members as training_members,
)
from tests.unit.test_science_campaign_expanded_training_contracts import (
    _expanded_command_value,
    _expanded_evaluation_command_value,
    _expanded_evaluation_result_value,
    _expanded_result_value,
)


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)


def _png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x80\x80\x80" * 800 for _ in range(500))
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", 800, 500, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw, level=9)),
            chunk(b"IEND", b""),
        )
    )


def _training_workspace(root: Path) -> None:
    command = _expanded_command_value()
    result = copy.deepcopy(_expanded_result_value())
    config = content_json_bytes({"lora_alpha": 8, "peft_type": "LORA", "r": 8})
    weights = b"bounded-safetensors-fixture"
    adapter = result["adapter_manifest"]
    assert isinstance(adapter, dict)
    adapter["files"] = [
        {
            "relative_path": "adapter_config.json",
            "size_bytes": len(config),
            "sha256": sha256_bytes(config),
        },
        {
            "relative_path": "adapter_model.safetensors",
            "size_bytes": len(weights),
            "sha256": sha256_bytes(weights),
        },
    ]
    adapter["manifest_sha256"] = content_sha256(
        {key: value for key, value in adapter.items() if key != "manifest_sha256"}
    )
    result["result_sha256"] = content_sha256(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    _write(root / "command.json", content_json_bytes(command))
    _write(root / "result.json", content_json_bytes(result))
    _write(root / "outputs" / "adapter_config.json", config)
    _write(root / "outputs" / "adapter_model.safetensors", weights)
    _write(
        root / "outputs" / "manifests" / "adapter-manifest.json",
        content_json_bytes(adapter),
    )


def _evaluation_workspace(root: Path) -> None:
    command = _expanded_evaluation_command_value()
    result = copy.deepcopy(_expanded_evaluation_result_value())
    png = _png()
    outputs = result["outputs"]
    assert isinstance(outputs, list)
    for output in outputs:
        assert isinstance(output, dict)
        output["sha256"] = sha256_bytes(png)
        output["size_bytes"] = len(png)
        _write(root / str(output["member_path"]), png)
    result["result_sha256"] = content_sha256(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    _write(root / "command.json", content_json_bytes(command))
    _write(root / "result.json", content_json_bytes(result))


def test_campaign_training_publication_validates_exact_file_set(tmp_path: Path) -> None:
    _training_workspace(tmp_path)
    _command, result, result_payload, schema_ref = load_training_result(tmp_path)
    members = training_members(tmp_path, result, result_payload, schema_ref)
    assert tuple(member.file_name for member in members) == (
        "adapter_config.json",
        "adapter_model.safetensors",
        "manifests/adapter-manifest.json",
        "result.json",
    )

    _write(tmp_path / "outputs" / "unexpected.bin", b"unexpected")
    with pytest.raises(
        ScienceCampaignMicroProbePublicationError,
        match="IMAGE_TRAINING_OUTPUT_INVALID",
    ):
        training_members(tmp_path, result, result_payload, schema_ref)


def test_campaign_training_publication_rejects_symlinked_result(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _training_workspace(source)
    _write(target, (source / "result.json").read_bytes())
    (source / "result.json").unlink()
    (source / "result.json").symlink_to(target)

    with pytest.raises(
        ScienceCampaignMicroProbePublicationError,
        match="IMAGE_TRAINING_RESULT_INVALID",
    ):
        load_training_result(source)


def test_campaign_evaluation_publication_validates_pngs_and_exact_pairs(
    tmp_path: Path,
) -> None:
    _evaluation_workspace(tmp_path)
    _command, result, result_payload, schema_ref = load_evaluation_result(tmp_path)
    members = evaluation_members(tmp_path, result, result_payload, schema_ref)
    assert len(members) == 9
    assert members[-1].file_name == "result.json"

    target = tmp_path / result.outputs[0].member_path
    target.write_bytes(b"not-a-png")
    with pytest.raises(
        ScienceCampaignMicroEvaluationPublicationError,
        match="IMAGE_EVALUATION_OUTPUT_INVALID",
    ):
        evaluation_members(tmp_path, result, result_payload, schema_ref)
