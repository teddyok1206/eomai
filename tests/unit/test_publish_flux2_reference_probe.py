from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import content_json_bytes, content_sha256

from scripts.image_candidate import publish_reference_probe
from tests.unit.test_flux2_reference_probe_contracts import (
    _command_value,
    _manifest_value,
    _plan_value,
    _result_value,
)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _png(width: int, height: int, gray: int) -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes((gray, gray, gray)) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _rebuild_case(case: dict[str, Any], reference: bytes, conditioning: bytes) -> None:
    case["visual_reference"]["sha256"] = _sha256(reference)
    case["visual_reference"]["size_bytes"] = len(reference)
    case["conditioning"]["sha256"] = _sha256(conditioning)
    case["conditioning"]["size_bytes"] = len(conditioning)
    case.pop("case_id")
    case["case_id"] = "imgflux2case_" + content_sha256(case)[7:39]


def _rebuild_plan(plan: dict[str, Any]) -> None:
    plan["cases"].sort(key=lambda value: value["case_id"])
    plan.pop("plan_id")
    plan.pop("plan_sha256")
    identity = {
        key: value for key, value in plan.items() if key not in {"created_at", "created_by"}
    }
    plan["plan_id"] = "imgflux2probe_" + content_sha256(identity)[7:39]
    plan["plan_sha256"] = content_sha256(plan)


def _completed_workspace(tmp_path: Path) -> Path:
    manifest = _manifest_value()
    plan = _plan_value(manifest)
    staged: dict[str, tuple[bytes, bytes]] = {}
    for ordinal, case in enumerate(plan["cases"], start=1):
        reference = _png(800, 504, 245 - ordinal)
        conditioning = _png(800, 504, 235 - ordinal)
        _rebuild_case(case, reference, conditioning)
        staged[case["subject_key"]] = (reference, conditioning)
    _rebuild_plan(plan)
    command = _command_value(plan)
    result = _result_value(manifest, plan, command)
    result_outputs = {(value["case_id"], value["kind"]): value for value in result["outputs"]}

    workspace = tmp_path / command["run_id"]
    references = workspace / "inputs" / "references"
    outputs = workspace / "outputs"
    references.mkdir(parents=True)
    outputs.mkdir()
    for case in plan["cases"]:
        reference, conditioning = staged[case["subject_key"]]
        case_id = case["case_id"]
        (references / f"{case_id}.png").write_bytes(reference)
        (references / f"{case_id}-conditioning.png").write_bytes(conditioning)
        candidate = _png(800, 500, 210)
        (outputs / f"{case_id}-candidate.png").write_bytes(candidate)
        (outputs / f"{case_id}-conditioning.png").write_bytes(conditioning)
        for kind, payload in (("CANDIDATE", candidate), ("CONDITIONING", conditioning)):
            declared = result_outputs[(case_id, kind)]
            declared["sha256"] = _sha256(payload)
            declared["size_bytes"] = len(payload)
    result.pop("result_sha256")
    result["result_sha256"] = content_sha256(result)

    (workspace / "command.json").write_bytes(content_json_bytes(command))
    (workspace / "inputs" / "probe-plan.json").write_bytes(content_json_bytes(plan))
    (workspace / "inputs" / "model-manifest.json").write_bytes(content_json_bytes(manifest))
    (outputs / "result.json").write_bytes(content_json_bytes(result))
    for path in workspace.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    workspace.chmod(0o700)
    return workspace


def _completed_workspace_v2(tmp_path: Path) -> Path:
    manifest = _manifest_value()
    plan = _plan_value(manifest)
    plan["schema_version"] = "local-image-flux2-reference-probe-plan/1.1"
    plan["layout_lock"] = {
        "contract": "local-image-reference-layout-lock/1.0",
        "foreground_luma_threshold": 245,
        "source_canvas_width_px": 800,
        "source_canvas_height_px": 504,
        "delivery_canvas_width_px": 800,
        "delivery_canvas_height_px": 500,
        "source_to_delivery_y_policy": "SCALE_HALF_OPEN_OUTWARD",
        "candidate_crop_policy": "TIGHT_FOREGROUND_BBOX",
        "placement_policy": "EXACT_REFERENCE_BBOX",
        "resize_filter": "LANCZOS",
        "background_policy": "WHITE",
        "empty_foreground_policy": "FAIL_CLOSED",
    }
    staged: dict[str, tuple[bytes, bytes]] = {}
    for ordinal, case in enumerate(plan["cases"], start=1):
        reference = _png(800, 504, 245 - ordinal)
        conditioning = _png(800, 504, 235 - ordinal)
        _rebuild_case(case, reference, conditioning)
        staged[case["subject_key"]] = (reference, conditioning)
    _rebuild_plan(plan)
    command = _command_value(plan)
    command["schema_version"] = "local-image-flux2-reference-probe-command/1.1"
    command["plan"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-flux2-reference-probe-plan/1.1"
    )
    command["plan"]["sha256"] = content_sha256(plan)
    command["plan_sha256"] = content_sha256(plan)
    command_identity = {
        key: value for key, value in command.items() if key not in {"run_id", "command_sha256"}
    }
    command["run_id"] = "imgflux2proberun_" + content_sha256(command_identity)[7:39]
    command["command_sha256"] = content_sha256(
        {key: value for key, value in command.items() if key != "command_sha256"}
    )

    outputs: list[dict[str, Any]] = []
    measurements: list[dict[str, Any]] = []
    workspace = tmp_path / command["run_id"]
    references = workspace / "inputs" / "references"
    output_root = workspace / "outputs"
    references.mkdir(parents=True)
    output_root.mkdir()
    for case in plan["cases"]:
        reference, conditioning = staged[case["subject_key"]]
        case_id = case["case_id"]
        raw = _png(800, 500, 210)
        locked = _png(800, 500, 200)
        (references / f"{case_id}.png").write_bytes(reference)
        (references / f"{case_id}-conditioning.png").write_bytes(conditioning)
        for kind, suffix, payload, height in (
            ("RAW_CANDIDATE", "raw-candidate", raw, 500),
            ("LOCKED_CANDIDATE", "locked-candidate", locked, 500),
            ("CONDITIONING", "conditioning", conditioning, 504),
        ):
            (output_root / f"{case_id}-{suffix}.png").write_bytes(payload)
            outputs.append(
                {
                    "case_id": case_id,
                    "kind": kind,
                    "relative_path": f"outputs/{case_id}-{suffix}.png",
                    "media_type": "image/png",
                    "size_bytes": len(payload),
                    "sha256": _sha256(payload),
                    "width_px": 800,
                    "height_px": height,
                }
            )
        bbox = {"x_min": 100, "y_min": 100, "x_max": 300, "y_max": 300}
        measurements.append(
            {
                "case_id": case_id,
                "elapsed_milliseconds": 1000,
                "peak_gpu_memory_bytes": 13_000_000_000,
                "reference_bbox": dict(bbox),
                "raw_candidate_bbox": {"x_min": 0, "y_min": 0, "x_max": 800, "y_max": 500},
                "locked_candidate_bbox": dict(bbox),
                "raw_area_ratio_milli": 10000,
                "locked_area_ratio_milli": 1000,
                "raw_center_distance_milli": 100,
                "locked_center_distance_milli": 0,
                "layout_status": "PASS",
            }
        )
    outputs.sort(key=lambda value: (value["case_id"], value["kind"]))
    measurements.sort(key=lambda value: value["case_id"])
    result = _result_value(manifest, plan, command)
    result.update(
        schema_version="local-image-flux2-reference-probe-result/1.1",
        outputs=outputs,
        measurements=measurements,
    )
    result.pop("result_sha256")
    result["result_sha256"] = content_sha256(result)
    (workspace / "command.json").write_bytes(content_json_bytes(command))
    (workspace / "inputs" / "probe-plan.json").write_bytes(content_json_bytes(plan))
    (workspace / "inputs" / "model-manifest.json").write_bytes(content_json_bytes(manifest))
    (output_root / "result.json").write_bytes(content_json_bytes(result))
    for path in workspace.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    workspace.chmod(0o700)
    return workspace


def test_flux2_publication_revalidates_exact_completed_file_set(tmp_path: Path) -> None:
    workspace = _completed_workspace(tmp_path)

    command, plan, manifest, loaded, result_payload = publish_reference_probe._load(workspace)
    members = publish_reference_probe._members(
        workspace,
        command,
        plan,
        loaded,
        result_payload,
    )

    assert loaded.status == "SUCCEEDED"
    assert manifest.activation_policy == "FORBIDDEN"
    assert len(members) == 7
    assert members[0].file_name.endswith(".png")
    assert members[-1].file_name == "result.json"


def test_flux2_publication_rejects_output_drift_and_unexpected_member(tmp_path: Path) -> None:
    workspace = _completed_workspace(tmp_path)
    command, plan, _manifest, loaded, result_payload = publish_reference_probe._load(workspace)
    candidate = next(value for value in loaded.outputs if value.kind == "CANDIDATE")
    candidate_path = workspace / candidate.relative_path
    original = candidate_path.read_bytes()
    drift = bytearray(original)
    drift[-1] ^= 1
    candidate_path.write_bytes(drift)

    with pytest.raises(publish_reference_probe.Flux2ProbePublicationError):
        publish_reference_probe._members(workspace, command, plan, loaded, result_payload)

    candidate_path.write_bytes(original)
    (workspace / "outputs" / "unexpected.png").write_bytes(b"not canonical")
    with pytest.raises(
        publish_reference_probe.Flux2ProbePublicationError,
        match="FLUX2_PROBE_OUTPUT_INVALID",
    ):
        publish_reference_probe._members(workspace, command, plan, loaded, result_payload)


def test_flux2_layout_lock_publication_revalidates_all_three_outputs(
    tmp_path: Path,
) -> None:
    workspace = _completed_workspace_v2(tmp_path)

    loaded_command, plan, manifest, loaded, result_payload = publish_reference_probe._load(
        workspace
    )
    members = publish_reference_probe._members(
        workspace,
        loaded_command,
        plan,
        loaded,
        result_payload,
    )

    assert manifest.activation_policy == "FORBIDDEN"
    assert len(members) == 10
    result_member = next(member for member in members if member.file_name == "result.json")
    assert result_member.schema_ref.endswith("local-image-flux2-reference-probe-result/1.1")
