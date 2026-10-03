from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from collections import Counter
from datetime import UTC, datetime

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLineartProbeCommand,
    LocalImageSdxlLineartPromptPolicy,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_orchestrator import sdxl_probe_inputs as admission
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    SDXL_PROBE_COMMAND_ARTIFACT_TYPE,
    SDXL_PROMPT_POLICY_ARTIFACT_TYPE,
    LocalImageTrainingControlArtifactPublisher,
)

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_corpus_visual_contracts import (
    _authorization_value,
    _object_line_art_values,
)
from tests.unit.test_sdxl_lineart_stack_contract import _stack


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _png(index: int) -> bytes:
    """Small synthetic PNGs; these are not exam crops or actual model invocations."""

    def chunk(name: bytes, raw: bytes) -> bytes:
        return struct.pack(">I", len(raw)) + name + raw + struct.pack(">I", zlib.crc32(name + raw))

    rows = []
    for y in range(96):
        row = bytearray([255] * 96)
        if 4 <= y <= 90:
            row[4] = row[90] = 0
        if y in {4, 90}:
            row[4:91] = b"\0" * 87
        if y == 48:
            row[index + 10] = 0
        rows.append(b"\0" + row)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 96, 96, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _seal(value, identity, prefix, hash_field):
    value[identity] = (
        prefix
        + content_sha256(
            {key: item for key, item in value.items() if key not in {identity, hash_field}}
        )[7:39]
    )
    value[hash_field] = content_sha256(
        {key: item for key, item in value.items() if key != hash_field}
    )


def _fixture(*, partition="TRAIN", fault=None):
    plans, results, plan_pointers, result_pointers, inventory, review, crops = copy.deepcopy(
        _object_line_art_values()
    )
    authorization = _authorization_value()
    records = {}

    def record(pointer, value):
        raw = content_json_bytes(value)
        pointer["sha256"] = _sha(raw)
        records[ImageEvaluationArtifactMember.model_validate(pointer)] = raw
        return pointer

    record(crops["training_authorization"], authorization)
    for index, pilot in enumerate(inventory["pilot_results"]):
        if fault == "old_result" and index == 0:
            results[index]["plan_sha256"] = "sha256:" + "f" * 64
            results[index]["result_sha256"] = content_sha256(
                {key: item for key, item in results[index].items() if key != "result_sha256"}
            )
        record(plan_pointers[index], plans[index])
        record(result_pointers[index], results[index])
        pilot["pilot_plan"] = plan_pointers[index]
        pilot["pilot_result"] = result_pointers[index]
        pilot["pilot_plan_file_sha256"] = plan_pointers[index]["sha256"]
        pilot["pilot_result_file_sha256"] = result_pointers[index]["sha256"]
        pilot["pilot_result_semantic_sha256"] = results[index]["result_sha256"]
    _seal(inventory, "inventory_id", "imgsciviscampaigninventory_", "inventory_sha256")
    record(review["pattern_inventory"], inventory)
    review["pattern_inventory_semantic_sha256"] = inventory["inventory_sha256"]
    _seal(review, "review_id", "imgscivislineartreview_", "review_sha256")
    record(crops["line_art_suitability_review"], review)
    crops["pattern_inventory"] = review["pattern_inventory"]
    crops["pattern_inventory_semantic_sha256"] = inventory["inventory_sha256"]
    crops["line_art_suitability_review_sha256"] = review["review_sha256"]
    images = {}
    for index, member in enumerate(crops["members"]):
        raw = _png(index)
        member["sha256"], member["size_bytes"] = _sha(raw), len(raw)
        if fault == "crop_geometry" and index == 0:
            member["crop_bounding_box"]["right"] += 1
            member["width_px"] += 1
        if fault == "oversized" and member["partition"] == partition:
            member["size_bytes"] = 16 * 1024**2 + 1
        member["sample_id"] = (
            "imgscivislineartcrop_"
            + content_sha256(
                {
                    key: item
                    for key, item in member.items()
                    if key not in {"sample_id", "member_path"}
                }
            )[7:39]
        )
        member["member_path"] = "crops/" + member["sample_id"] + ".png"
        images[member["member_path"]] = raw
    crops["members"].sort(key=lambda member: member["sample_id"])
    _seal(crops, "crop_set_id", "imgscivislineartcropset_", "crop_set_sha256")
    crop_pointer = record(
        {
            "artifact_id": "artifact_" + "a" * 32,
            "artifact_revision_id": "rev_" + "b" * 32,
            "member_path": "manifests/science-object-line-art-crop-set.json",
            "schema_ref": "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0",
            "media_type": "application/json",
        },
        crops,
    )
    cases = []
    for index, member in enumerate(
        [item for item in crops["members"] if item["partition"] == partition][:2]
    ):
        pointer = {
            **crop_pointer,
            "member_path": member["member_path"],
            "schema_ref": "eom://schemas/image-provider/local-image-science-visual-crop/1.0",
            "media_type": "image/png",
            "sha256": member["sha256"],
        }
        records[ImageEvaluationArtifactMember.model_validate(pointer)] = images[
            member["member_path"]
        ]
        if fault == "revision" and index == 1:
            pointer["artifact_revision_id"] = "rev_" + "f" * 32
        if fault == "dimension" and index == 1:
            width = member["width_px"] + 1
        else:
            width = member["width_px"]
        if fault == "duplicate_reference" and index == 1:
            pointer = cases[0]["reference_image"]
        case = {
            "depiction_key": "TEST_OBJECT_"
            + ("0" if fault == "duplicate_depiction" else str(index)),
            "reference_image": pointer,
            "reference_width_px": width,
            "reference_height_px": member["height_px"],
            "prompt_en": "Black and white scientific illustration of a test object.",
            "negative_prompt_en": "text, watermark, color, decorative background",
            "seeds": [1, 2],
        }
        case["prompt_sha256"] = text_sha256(case["prompt_en"])
        case["negative_prompt_sha256"] = text_sha256(case["negative_prompt_en"])
        case["case_id"] = "imgsdxlcase_" + content_sha256(case)[7:39]
        case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
        cases.append(case)
    cases.sort(key=lambda case: case["case_id"])
    policy = {
        "schema_version": "local-image-sdxl-lineart-prompt-policy/1.0",
        "crop_set": crop_pointer,
        "training_authorization": crops["training_authorization"],
        "experiment_authorization": {
            "approved_at": "2026-10-04T06:00:00Z"
            if fault == "future_approval"
            else "2026-10-03T06:00:00Z",
            "approved_by": "fixture.operator",
            "approval_message_sha256": _sha(b"fixture approval"),
            "permitted_uses": ["INTERNAL_SDXL_COMPARISON"],
            "external_export": "FORBIDDEN",
            "automatic_activation": "FORBIDDEN",
        },
        "experiment_partition": "TRAIN",
        "catalog_policy_revision": "local-gpu-image-prompt-policy/1.7",
        "sources": [
            {"role": role, "source_name": authority["logical_name"], "sha256": authority["sha256"]}
            for role, authority in zip(
                ("AUTHORING_GUIDANCE", "EDITOR_HANDOFF", "ILLUSTRATION_GUIDANCE"),
                plans[0]["guidance_authorities"],
                strict=True,
            )
        ],
        "cases": cases,
    }
    if fault == "authorization":
        policy["training_authorization"] = {
            **policy["training_authorization"],
            "artifact_revision_id": "rev_" + "f" * 32,
        }
    if fault == "crop_schema":
        policy["crop_set"] = {
            **crop_pointer,
            "schema_ref": "eom://schemas/image-provider/unrelated/1.0",
        }
    policy_pointer = record(
        {
            "artifact_id": "artifact_" + "c" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "member_path": "manifests/sdxl-lineart-prompt-policy.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-lineart-prompt-policy/1.0",
            "media_type": "application/json",
        },
        policy,
    )
    stack = _stack()
    command = {
        "schema_version": "local-image-sdxl-lineart-probe-command/1.0",
        "run_id": "imgsdxlproberun_" + "e" * 32,
        "created_at": "2026-10-03T06:00:00Z",
        "model": {
            key: stack[key]
            for key in (
                "model_id",
                "model_revision_id",
                "manifest_sha256",
                "provider_family",
                "runtime_contract_version",
            )
        },
        "prompt_policy": policy_pointer,
        "style_track": "OBJECT_LINE_ART",
        "conditioning_policy": "FIT_GRAYSCALE_INVERT_832X512/1.0",
        "inference_steps": 20,
        "guidance_scale": 7.0,
        "adapter_conditioning_scale": 0.8,
        "budget": {"maximum_duration_ms": 30000, "maximum_peak_gpu_memory_bytes": 2**30},
        "cases": cases,
    }
    command["command_sha256"] = content_sha256(command)
    return LocalImageSdxlLineartProbeCommand.model_validate(command), policy, records


class _Reader:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def __call__(self, _engine, pointer, *, maximum_bytes):
        self.calls.append(pointer)
        raw = self.records.get(pointer)
        if raw is None:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_POINTER_INVALID")
        if _sha(raw) != pointer.sha256:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_HASH_MISMATCH")
        assert 0 < len(raw) <= maximum_bytes
        return raw


def test_exact_pinned_source_admission_is_read_only_bounded_and_deterministic(monkeypatch):
    command, _policy, records = _fixture()
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    result = admission.prepare_sdxl_probe_inputs(object(), command)
    assert result.command == command
    assert len(result.files) == 4
    assert tuple(item.member_path for item in result.files) == tuple(
        sorted(item.member_path for item in result.files)
    )
    assert all(item.sha256 == _sha(item.payload) for item in result.files)
    assert max(Counter(reader.calls).values()) == 1
    assert all(pointer.media_type in {"application/json", "image/png"} for pointer in reader.calls)
    assert json.loads(result.files[0].payload) == command.model_dump(mode="json")
    again = admission.prepare_sdxl_probe_inputs(object(), command)
    assert again == result


@pytest.mark.parametrize("partition", ["VALIDATION", "HOLDOUT"])
def test_reserved_partitions_never_materialize_as_diagnostic_inputs(monkeypatch, partition):
    command, _policy, records = _fixture(partition=partition)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    with pytest.raises(admission.SdxlProbeAdmissionError, match="REFERENCE_SOURCE_INVALID"):
        admission.prepare_sdxl_probe_inputs(object(), command)
    assert not any(pointer.media_type == "image/png" for pointer in reader.calls)


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("revision", "SDXL_PROBE_REFERENCE_SOURCE_INVALID"),
        ("dimension", "SDXL_PROBE_REFERENCE_SOURCE_INVALID"),
        ("duplicate_reference", "SDXL_PROBE_REFERENCE_SOURCE_INVALID"),
        ("duplicate_depiction", "SDXL_PROBE_REFERENCE_SOURCE_INVALID"),
        ("future_approval", "SDXL_PROBE_PROMPT_PROVENANCE_INVALID"),
        ("authorization", "SDXL_PROBE_AUTHORIZATION_POINTER_INVALID"),
        ("crop_schema", "SDXL_PROBE_SOURCE_CONTRACT_INVALID"),
        ("crop_geometry", "SDXL_PROBE_SOURCE_LINEAGE_INVALID"),
        ("old_result", "SDXL_PROBE_SOURCE_LINEAGE_INVALID"),
        ("oversized", "SDXL_PROBE_REFERENCE_SOURCE_INVALID"),
    ],
)
def test_invalid_lineage_fails_before_any_png_materialization(monkeypatch, fault, expected):
    command, _policy, records = _fixture(fault=fault)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    with pytest.raises(admission.SdxlProbeAdmissionError, match="^" + expected + "$"):
        admission.prepare_sdxl_probe_inputs(object(), command)
    assert not any(pointer.media_type == "image/png" for pointer in reader.calls)


@pytest.mark.parametrize("fault", ["missing", "hash"])
def test_resolution_errors_are_preserved_without_latest_or_replacement(monkeypatch, fault):
    command, _policy, records = _fixture()
    if fault == "missing":
        del records[command.prompt_policy]
    else:
        records[command.prompt_policy] += b" "
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    with pytest.raises(ControlArtifactResolutionError):
        admission.prepare_sdxl_probe_inputs(object(), command)
    assert reader.calls == [command.prompt_policy]


def test_metadata_publication_reuses_existing_orchestrator_idempotent_owner():
    command, policy, _records = _fixture()
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(publisher, source_commit="a" * 40)
    policy = LocalImageSdxlLineartPromptPolicy.model_validate(policy)
    pointer = adapter.commit_sdxl_prompt_policy(
        policy, created_at=datetime(2026, 10, 3, 6, tzinfo=UTC)
    )
    assert publisher.arguments["artifact_type"] == SDXL_PROMPT_POLICY_ARTIFACT_TYPE
    assert pointer.sha256 == _sha(content_json_bytes(policy.model_dump(mode="json")))
    identity = publisher.arguments["idempotency_key"]
    adapter.commit_sdxl_prompt_policy(policy, created_at=datetime(2026, 10, 3, 6, tzinfo=UTC))
    assert publisher.arguments["idempotency_key"] == identity
    pointer = adapter.commit_sdxl_probe_command(command)
    assert publisher.arguments["artifact_type"] == SDXL_PROBE_COMMAND_ARTIFACT_TYPE
    assert pointer.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))


def test_track_mismatch_is_rejected_before_pointer_resolution(monkeypatch):
    command, _policy, records = _fixture()
    value = command.model_dump(mode="json")
    value["style_track"] = "RASTER_TEXTURE_SCENE"
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    command = LocalImageSdxlLineartProbeCommand.model_validate(value)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    with pytest.raises(admission.SdxlProbeAdmissionError, match="SOURCE_CONTRACT_INVALID"):
        admission.prepare_sdxl_probe_inputs(object(), command)
    assert reader.calls == []


def test_policy_cannot_be_published_before_experiment_approval():
    _command, policy, _records = _fixture()
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(publisher, source_commit="a" * 40)
    with pytest.raises(ValueError, match="publication precedes approval"):
        adapter.commit_sdxl_prompt_policy(
            LocalImageSdxlLineartPromptPolicy.model_validate(policy),
            created_at=datetime(2026, 10, 3, 5, tzinfo=UTC),
        )
    assert publisher.arguments == {}


def test_policy_naive_publication_time_fails_before_persistence():
    _command, policy, _records = _fixture()
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(publisher, source_commit="a" * 40)
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        adapter.commit_sdxl_prompt_policy(
            LocalImageSdxlLineartPromptPolicy.model_validate(policy),
            created_at=datetime(2026, 10, 3, 6),
        )
    assert publisher.arguments == {}
