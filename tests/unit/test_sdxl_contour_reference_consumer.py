"""Exact contour lineage through the existing reference owner/worker; no live fit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes, content_sha256, validate_contract
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV4,
    LocalImageSdxlNativeCannyReferenceResultV4,
    native_reference_metadata_pointers,
    parse_reference_command,
    parse_reference_result,
    validate_reference_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider import sdxl_canny_reference as worker
from eom_orchestrator import sdxl_canny_reference_inputs as owner
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_sdxl_canny_reference import _run, _seal
from tests.unit.test_sdxl_geometry_baseline_reuse import _fixture as reuse_fixture
from tests.unit.test_sdxl_geometry_baseline_reuse import _pin
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal as seal_evaluation
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_canny_reference import _fixture as reference_fixture


def _fixture(tmp_path, monkeypatch):
    old, reader, trace, leases = reference_fixture(tmp_path, monkeypatch)
    evaluation, records, _ = reuse_fixture()
    pin, raw = _pin(evaluation, "sdxl-lora-evaluation-command", "a")
    reader.records.update(records)
    reader.records[pin] = raw
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-canny-reference-command/1.4",
        native_evaluation_command=pin.model_dump(mode="json"),
        created_at=max(old.created_at, evaluation.created_at).isoformat().replace("+00:00", "Z"),
    )
    return (
        LocalImageSdxlNativeCannyReferenceCommandV4.model_validate(_seal(value)),
        reader,
        trace,
        leases,
    )


def _stage(tmp_path, monkeypatch):
    command, reader, trace, leases = _fixture(tmp_path, monkeypatch)
    prepared = owner.prepare_sdxl_canny_reference_inputs(object(), command)
    assert trace == ["LINEAGE", "NATIVE_LINEAGE", "PIXELS", "PIXELS"]
    root = tmp_path / "contour-reference"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, reader, leases


def test_schema_package_build_and_closed_predecessor(tmp_path, monkeypatch):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    assert parse_reference_command(command.model_dump(mode="json")) == command
    repo = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        key = "sdxl-canny-reference-" + family + "-v5"
        Draft202012Validator.check_schema(load_schema(key))
        filename = SCHEMA_FILES[key]
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[key]
        assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()
    with pytest.raises(SchemaError):
        validate_contract("sdxl-canny-reference-command-v4", command.model_dump(mode="json"))
    assert (
        SCHEMA_SHA256["sdxl-canny-reference-command-v4"]
        == "sha256:27fb8078901923f4f6fb6a1db304f8182bd7a7bf328c1d03214b14904e888121"
    )
    assert (
        SCHEMA_SHA256["sdxl-canny-reference-result-v4"]
        == "sha256:e29c52ff5bdcc5548f76009851d45955ccb24c12f6ca6749065e6001d999b912"
    )


@pytest.mark.parametrize("version", ["1.2", "1.4", "1.5", "99.0"])
def test_closed_evaluation_family(tmp_path, monkeypatch, version):
    command, _, trace, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    value["native_evaluation_command"]["schema_ref"] = (
        "eom://schemas/image-provider/local-image-sdxl-lora-evaluation-command/" + version
    )
    value = _seal(value)
    with pytest.raises(SchemaError):
        validate_contract("sdxl-canny-reference-command-v5", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeCannyReferenceCommandV4.model_validate(value)
    assert "PIXELS" not in trace


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_exact_new_adapter_metadata_stage_and_side_effect_free_terminal_replay(
    tmp_path, monkeypatch, fault
):
    prepared, root, reader, leases = _stage(tmp_path, monkeypatch)
    assert prepared.sources.native.training_command.schema_version.endswith("/1.3")
    assert prepared.sources.evaluation.schema_version.endswith("/1.6")
    assert owner.sdxl_canny_reference_input_hashes(prepared) == {
        f.member_path: f.sha256 for f in prepared.files
    }
    native = native_reference_metadata_pointers(prepared.command, prepared.sources.evaluation)
    assert len(native) == 7
    for field, path in (
        ("prior_command", "inputs/native-reuse-command.json"),
        ("prior_result", "inputs/native-reuse-result.json"),
    ):
        pin = getattr(prepared.sources.evaluation.baseline_reuse, field)
        assert native[path] == pin
        assert pin in reader.calls
        assert (root / path).read_bytes() == reader.records[pin]
    assert not any("outputs/raw" in pin.member_path for pin in reader.calls)
    result = _run(prepared, root, _Backend(fault))
    assert parse_reference_result(result.model_dump(mode="json")) == result
    assert type(result) is LocalImageSdxlNativeCannyReferenceResultV4
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    validate_reference_result(prepared.command, prepared.sources, result)
    assert result.activation_policy == "FORBIDDEN"
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "sdxl_canny_source_canvas",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(
            worker, name, lambda *a, **k: pytest.fail("terminal replay side effect")
        )
    assert _run(prepared, root, _Backend()) == result
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()
    }
    assert leases == ["ENTER", "EXIT"]


@pytest.mark.parametrize(
    ("field", "fault"),
    [
        (field, fault)
        for field in ("prior_command", "prior_result")
        for fault in ("missing", "hash", "permission")
    ]
    + [("prior_command", "caption"), ("prior_result", "failed")],
)
def test_borrowed_lineage_rejected_before_media(tmp_path, monkeypatch, field, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    evaluation, _, _ = reuse_fixture()
    pin = getattr(evaluation.baseline_reuse, field)
    if fault == "missing":
        del reader.records[pin]
    elif fault == "hash":
        reader.records[pin] += b" "
    elif fault == "permission":
        original = owner.resolve_control_artifact_member

        def denied(engine, pointer, **kwargs):
            if pointer == pin:
                raise PermissionError("borrowed geometry denied")
            return original(engine, pointer, **kwargs)

        monkeypatch.setattr(owner, "resolve_control_artifact_member", denied)
    else:
        value = json.loads(reader.records[pin])
        if fault == "caption":
            value["cases"][0]["training_caption_sha256"] = "sha256:" + "0" * 64
            value = seal_evaluation(value)
        else:
            value.update(
                status="FAILED",
                error_code="SDXL_PROBE_OUTPUT_INVALID",
                outputs=[],
                generation_calls=0,
            )
            value["result_sha256"] = content_sha256(
                {k: v for k, v in value.items() if k != "result_sha256"}
            )
        raw = content_json_bytes(value)
        new_pin = pin.model_copy(update={"sha256": "sha256:" + hashlib.sha256(raw).hexdigest()})
        reader.records[new_pin] = raw
        value = evaluation.model_dump(mode="json")
        value["baseline_reuse"][field] = new_pin.model_dump(mode="json")
        changed = seal_evaluation(value)
        raw = content_json_bytes(changed)
        evaluation_pin = command.native_evaluation_command.model_copy(
            update={"sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}
        )
        reader.records[evaluation_pin] = raw
        value = command.model_dump(mode="json")
        value["native_evaluation_command"] = evaluation_pin.model_dump(mode="json")
        command = parse_reference_command(_seal(value))
    with pytest.raises((KeyError, ValueError, RuntimeError, SchemaError, PermissionError)):
        owner.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace
